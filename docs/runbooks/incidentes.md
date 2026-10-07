# Incidentes — BATCH-03

Operador humano: pare o supervisor/agendamento antes de investigar e preserve relatórios.
Não edite Actions, checkpoints ou marcadores por SQL. `--read-meta` faz somente GET e exige
host humano autorizado, versão V-06 validada e segredos provisionados fora dos agentes.
Nenhum desses comandos foi executado contra APIs reais neste batch. Simulação é o padrão;
este runbook não habilita live nem aumenta exposição.

## Pausa incerta
<!-- drill: pause_uncertain -->

1. Liste intenção/resultado; não repita pausa enquanto houver pendência.

```sh
uv run arb ops pending --database data/engine.db --json
```

2. No host autorizado, reconcilie por leitura. PAUSED confirma pausa; ACTIVE confirma
que não foi pausado. Desconhecido/erro preserva pendência: mantenha processos parados,
revise a conta e pause manualmente na Meta quando necessário. Panic em simulação não
altera o estado observado remoto.

```sh
uv run arb ops reconcile --database data/engine.db --read-meta --json
uv run arb preflight --database data/engine.db --json
```

## Intenção órfã após queda
<!-- drill: orphan_intent -->

1. Inspecione antes de retomar. Ausência de resultado não prova ausência de efeito.

```sh
uv run arb ops pending --database data/engine.db --json
```

2. Reconcilie observação conhecida no host humano. Desconhecido continua bloqueado.
Lookup de criação só foi exercitado no FakeMeta; não há lookup Graph de criação.

```sh
uv run arb ops reconcile --database data/engine.db --read-meta --json
```

## Ciclo interrompido
<!-- drill: interrupted_cycle -->

1. Resolva pendências e quarentena antes de qualquer retomada.

```sh
uv run arb ops pending --database data/engine.db --json
uv run arb preflight --database data/engine.db --json
```

2. `scheduler once` usa o último slot vencido. Só retoma o checkpoint se esse slot for
o ciclo interrompido; ciclo completo não repete efeitos. Confira timestamp no estado/
relatório do ciclo. **Se já venceu outro slot, não use once para afirmar que retomou o
antigo:** mantenha supervisor parado e peça tarefa revisada de retomada explícita por slot.
A CLI não possui `scheduler resume`. Não marque complete por SQL. Offline sem fonte
congela/alerta; o comando não cria integração.

```sh
uv run arb scheduler once --database data/engine.db --output reports
```

## Backup corrompido
<!-- drill: corrupt_backup -->

1. Ensaie em cópia descartável. Exit não zero / status failed bloqueia preflight. Preserve
o backup inválido; selecione outro íntegro. Drill seleciona o .db mais recente do diretório.

```sh
uv run arb db drill --backups data/backups --json
```

2. Restaure o arquivo validado em **destino novo**; substitua a data pelo backup verificado.
Se mudar de pasta, prepare backup e drill nela antes de operar. Nunca sobrescreva o banco.

```sh
uv run arb db restore data/backups/engine-2026-10-05.db --database data/recovered.db
uv run arb doctor
```

## Restore contém entidade ativa
<!-- drill: restore_active -->

1. Restore entra em quarentena. Backup anterior à pausa pode conter active: não conecte
a cópia ao supervisor. Panic pausa entidades locais; para remotas em simulação retorna
remote_pause_pending e preserva estado observado. Confirme/efetue pausa manual na Meta.

```sh
uv run arb panic --database data/recovered.db
uv run arb ops pending --database data/recovered.db --json
```

2. Reconcilie pendências no host autorizado e libere só com PAUSED comprovado. Release
não reativa entidades nem concede aprovação de exposição.

```sh
uv run arb ops reconcile --database data/recovered.db --read-meta --json
uv run arb db release --database data/recovered.db --read-meta
```

## Token expirado ou inválido (190) na leitura
<!-- drill: token_190 -->

1. Preserve pendências: erro 190 não confirma pausa. Humano rotaciona token no gerenciador
de segredos do host, sem chat/log/repositório. Recrie cliente e repita apenas leitura
autorizada; não envie valores a agentes.

```sh
uv run arb ops pending --database data/engine.db --json
uv run arb ops reconcile --database data/engine.db --read-meta --json
```

## Quarentena antes da volta ao supervisor
<!-- drill: quarantine -->

1. Release exige tty e confirmação humana, sem --yes. ACTIVE/desconhecido/pendência
impede liberar. Se não há entidades remotas, omita --read-meta.

```sh
uv run arb db release --database data/recovered.db --read-meta
```

2. Prepare backup do dia UTC e drill válido; confira preflight no host autorizado antes
de decidir retomar. Presença de nomes de credenciais não valida seus valores. Preflight
verde não assina planos nem comprova F5/F6 reais.

```sh
uv run arb db backup --database data/recovered.db --output data/backups
uv run arb db drill --backups data/backups --json
uv run arb preflight --database data/recovered.db --read-meta --json
```

## Evidência do ensaio

Os sete marcadores estão vinculados aos cenários reais do drill sintético. Seeds 7, 42 e
101 verificam assinatura/exposição, auditoria, unicidade, pausa após kill, quarentena e
totais. Cada invariante tem teste de violação plantada. O comando abaixo usa banco,
configuração, chave sintética e pseudo-terminal temporários, sem banco/credenciais do
humano. JSON compara com referências versionadas em docs/validation.

```sh
uv run arb drill run --seed 42 --json
```

A retomada do drill usa run_cycle com o slot original; não prova seleção de slot antigo
pela CLI. Dinheiro real continua bloqueado: executor Graph, F5/F6, V-01 a V-06,
cartão/spend_cap e host persistente dependem de aceites humanos.
