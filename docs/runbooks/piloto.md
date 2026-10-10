# Piloto — da fumaça humana ao laboratório simulado

Este roteiro usa o checkout revisado. **O motor não está pronto para dinheiro real.**
Execute as leituras reais pessoalmente no seu host, com as permissões e V-06 verificados;
o Codex valida esta sequência somente com banco sintético e HTTP simulado.
No Windows, use WSL/Linux conforme [guia do operador](operador.md) e [host](host.md).
Não leia `.env` nem transfira chave privada ao motor/cloud. Mantenha LIVE_MODE=false.

Antes: humano cria e opera a campanha de fumaça no Gerenciador, dentro do limite escolhido,
com defesa no cartão e na conta. O orçamento de R$ 200 do planejamento é uma decisão sua;
o `cap-cents` abaixo é um alerta local, não instala limite na Meta e não cria campanha.
A oferta deve existir no banco local. Não registre a campanha de fumaça como teste de F6.

Substitua as variáveis por informações verificadas, não pelos IDs sintéticos dos testes:
`CAMPANHA`, `CONJUNTO`, `ANUNCIO`, `OFERTA`, `GEO`, `TETO_CENTAVOS`, `BANCO`, `DESDE`, `ATE`,
`CSV`, `MAPA_CSV`, `PERFIL`, `ROOT`, `BANCO_LAB`, `FATURA_PLATAFORMA`, `FATURA_TOTAL`,
`FATURA_REF`. DESDE/ATE são datas locais inclusivas no fuso configurado; BANCO_LAB é um
arquivo novo e separado. PERFIL fica em reports e nunca aponta ao banco/config ou a symlink.
Tokens e chave permanecem no host/máquina assinadora; não colar segredos nos comandos/relatórios.

## 1. Registrar a campanha criada pelo humano

```sh
uv run arb smoke register --campaign "${CAMPANHA}" --adset "${CONJUNTO}" --ad "${ANUNCIO}" --offer "${OFERTA}" --geo "${GEO}" --cap-cents "${TETO_CENTAVOS}" --database "${BANCO}"
```

É um cadastro local auditado actor=human, não escrita Meta. IDs duplicados são recusados:
não repetir o registro para tentar criar outra campanha. Smoke nunca recebe pause/scale/
ativação automática, inclusive por freios ou dados atrasados. Ao alerta de teto, **você pausa
manualmente**; o motor registra o gasto nos freios das outras campanhas.

## 2. Leitura diária e vendas

Repetir a janela diária ou reconsultar a janela acumulada: sync reconcilia deltas sem duplicar.
Só executar contra a Meta pessoalmente, com token somente leitura e versão verificada.

```sh
uv run arb sync meta --since "${DESDE}" --until "${ATE}" --database "${BANCO}"
uv run arb sales import "${CSV}" --mapping "${MAPA_CSV}" --database "${BANCO}"
```

O CSV usa seu mapeamento declarativo validado (V-01), não um formato do Hotmart inventado.
Transações repetidas não duplicam receita. Venda sem rastreio aparece como não casada:
conferir parâmetro V-02, alias curto e fluxo da ponte; nunca atribuir receita por palpite.
Dados da ponte entram pelo sync events descrito no guia do operador, depois de validar o
Worker no host; não é preciso chamar Worker publicado para testar este roteiro.

## 3. Relatório e fatura, quando disponível

```sh
uv run arb smoke report --campaign "${CAMPANHA}" --database "${BANCO}" --output reports/smoke.json --report-file reports/smoke.md
```

Ver gasto bruto **estimado** pelo imposto configurado, CPM, CTR, hook, ponte→checkout, vendas
casadas e não casadas (estas são do banco inteiro), alerta de teto e V-02/V-04. Observado
não significa aceite assinado nem F6. A campanha humana permanece operada pelo humano.

Somente se a fatura existir e seus totais corresponderem ao gasto acumulado da fumaça:

```sh
uv run arb smoke invoice --campaign "${CAMPANHA}" --platform-cents "${FATURA_PLATAFORMA}" --total-cents "${FATURA_TOTAL}" --evidence-ref "${FATURA_REF}" --database "${BANCO}"
uv run arb smoke report --campaign "${CAMPANHA}" --database "${BANCO}" --output reports/smoke.json --report-file reports/smoke.md
```

Invoice guarda números e referência textual local; não abre arquivo nem envia fatura.
Se gasto acumulado já mudou, V-04 volta a pendente: atualizar evidência humana, não inventar
imposto. Não compartilhar fatura completa, tokens, IDs privados ou dados pessoais.

## 4. Perfil observado e calibração

```sh
uv run arb observed profile --since "${DESDE}" --until "${ATE}" --database "${BANCO}" --output "${PERFIL}"
uv run arb sim calibrate --profile-file "${PERFIL}" --seeds 1 --workers 1 --output reports/pilot-calibration.json --report reports/pilot-calibration.html
uv run arb sim confirm-report --seeds 0-1 --workers 1 --output reports/pilot-confirmation.json --report reports/pilot-confirmation.md
```

Os comandos curtos validam a sequência. Para uma decisão, usar muitas seeds (p.ex. o relatório
versionado 0–99), conferir estabilidade e amostra. Não substituir PERFIL pelo banco nem usar
saída da calibração como seu arquivo de entrada. Saídas não pertencem a config.

`insufficient_data` exige mais observação: não calibrar sobre zeros nem fabricar dados.
O perfil mede tráfego/funil por geo com amostras e intervalos; os quatro papéis usam a mesma
distribuição observada, sem inventar segmentos. Comissão/refund/orçamento do laboratório
continuam hipóteses existentes; janela não é coorte e vendas/reembolsos podem atrasar.

confirm-report compara os **perfis hipotéticos existentes** com/sem C; não é automaticamente
um relatório da janela observada. Consultar [relatório de confirmação](../validation/confirmation-report.md):
falsos positivos não zeram e confirmação custa dinheiro simulado. O nome winner de um perfil
não prova vencedor verdadeiro: classificação usa economia esperada do modelo.

## 5. Decisões humanas e prontidão

Revisar ADR-039 (Portão C), ADR-041 (CAPI), ADR-043 (produtor), além dos contratos e dos
ADRs de observação/fumaça. Todos estão **Proposto — aguarda aceite humano**. Não aceitar
ADRs automaticamente nem mudar rules.yaml pelo roteiro. Gate C continua desligado;
CAPI precisa de decisão humana, pixel correspondente, token/versão verificados e instalação
fora do Codex. Dados do produtor são declaração/evidência a conferir, não autorização de gasto.

Preencher V-01–V-06 e limites com registros **assinados** na sua máquina, conforme o guia
do operador. Fumaça não é aceite F6; kits reais F5/F6/rastreio e host persistente continuam
pendentes. Evidência sem assinatura, vencida ou de outra operação não libera o motor.

```sh
uv run arb preflight --database "${BANCO}" --root "${ROOT}" --json
uv run arb readiness --root "${ROOT}" --json
```

Saída esperada no estado do repositório: **não pronto**, exit 1 com pendências. Não ignorar
essa saída para lançar algo real. Preflight acima não chama APIs; `--read-meta` é reservado
para validação pessoal no host, fora deste teste. Executor Graph de exposição continua ausente.

## 6. Laboratório somente simulado

```sh
uv run arb sim run --seed 42 --budget 2400 --profile planted --database "${BANCO_LAB}"
```

Este budget é um parâmetro hipotético da simulação, não aporte/cartão/orçamento real. Rodar
em banco novo separado; não usar o banco operacional e não sobrescrever histórico.
Resultado determinístico não comprova mercado. Dinheiro real exige todas as pendências e
aprovações explícitas; continuar sem exposição enquanto readiness disser não pronto.

## O que o motor não faz por você

- Criar ou operar a campanha de fumaça, escolher limite, pausar manualmente ao teto.
- Aceitar ADR, escolher versão/permissão da Graph ou ligar/deployar CAPI.
- Verificar a declaração escrita do produtor e o formato real do CSV/rastreio.
- Definir limite do cartão, spend_cap da conta ou instalar serviço/host persistente.
- Guardar sua chave privada, assinar evidências por você ou fazer merge do próprio PR.

Compartilhe com Claude só evidências redigidas e relatórios sem segredos. Em resultado
incerto, usar [incidentes](incidentes.md); não repetir efeito externo por tentativa.

Rotina diária de observação: `arb smoke daily --help` (coleta GET, relatórios datados e pausa manual). O roteiro do dia 1 será documentado em `dia-1.md`.
