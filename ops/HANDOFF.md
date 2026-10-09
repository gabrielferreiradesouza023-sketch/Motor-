# HANDOFF — BATCH-06

## Estado atual
- Base main `35dbab563916bcc3bb428836c3b47d3c1301c5c5`: #36/BATCH-05 mergeado, T-72–T-76 em review na main.
- Branch `codex/batch-06`. Planejamento exato recebido do humano publicado em `f1f8b82`.
- T-77 concluída; PR draft [#37](https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/37) aberto. CI gates+worker verde no head `d96e41e` antes de pegar T-78. Ordem T-78 → T-83; CI verde por tarefa antes da próxima.
- Sem merge; Claude revisa, humano decide. Motor não pronto para dinheiro real.

## Feito e evidências
- T-77: C opcional (None), referência de gasto no primeiro G3 pass no mesmo entity/geo, posterior Gamma-Poisson, candidatos sem escala, biblioteca/controles somente C/T quando ligado. Contratos regenerados; ADR-039 proposto.
- Comparação independente contra código de main: 9 summaries (seeds 0/7/42 × 3 perfis) e 8 células de calibração byte-idênticos (`/tmp/b06-compat.py`).
- 32 testes novos: referência Decimal 80 dígitos, violações/amostras/tetos/stale/zero custo, contexto/geo, escala local, scheduler e biblioteca.
- Houve um outlier de 220 ms no teste existente de auditoria (<200 ms). Repetição intacta: pending 5.08 ms e last_increase 7.22 ms; suíte completa repetida verde, nenhum limite/teste removido ou alterado.

## Falta
- T-78–T-83 e respectivos gates/CI; relatório de falsos positivos no corpo do PR; handoff final e ready.

## Bloqueios
- Nenhum bloqueio de software até T-77. Operação real segue bloqueada por V-01–V-06, cartão/spend_cap, host persistente, aceites F5/F6/rastreio assinados e executor Graph T-55.
- ADRs deste batch permanecem Proposto — aguarda aceite humano. C desativado, rules.yaml intocado.

## Riscos e revisão
- Posterior assume taxa constante e comissão/refund esperados; probabilidade não garante lucro e múltiplas avaliações podem produzir falsos positivos. Relatório T-78 medirá hipóteses, não mercado.
- Referência C é vinculada à entidade/geo; não transferir confirmação para outra identidade/contexto implicitamente. Fluxo de exposição Graph continua indisponível.
- Nenhuma API real, .env, privada real, conta, gasto, mensagem, deploy ou serviço instalado.
- Revisão: Claude revisa PR inteiro e ADRs propostos; humano aceita/rejeita ADRs e decide merge em separado.

### BATCH-06 T-77 — review
32 testes novos; referência posterior Decimal, candidato/kill/pass/stale, contexto/geo, escala, scheduler e biblioteca; 9 summaries e 8 células byte-idênticos à main. Gates locais: 1000 testes, 90.81% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.

### BATCH-06 T-78 — review
19 testes novos; perdedor de sorte barrado com C, vencedor preservado, entradas/destinos inválidos recusados; relatório 0-99 gerado duas vezes byte-idêntico. Realistic: FP 31/871 sem C, 18/871 com C15000; acerto 17/29→16/29. Gates locais: 1019 testes, 90.91% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.

### BATCH-06 T-79 — review
28 testes novos; CPM/CTR/hook/funil contra referências, Wilson Decimal, data de conta, replay/test excluídos, janela/amostra insuficiente sem parâmetros, leitura sem alteração SQLite e calibração do YAML. Módulo observed 100%; compatibilidade 9 summaries/8 células preservada. Gates locais: 1047 testes, 91.37% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.

### BATCH-06 T-80 — review
4 testes Python novos; 8 testes Node novos (Worker: 11/11, zero skips, capi.ts 100% linhas/branches/funções, npm typecheck verde). Pixel e POST compartilham nonce medido no Chromium; replay envia uma vez, falhas HTTP/timeout preservam D1 e 202. Ruff, pytest com cobertura, gate de dinheiro, doctor, contratos e detect-secrets verdes; drill 42 byte-idêntico. ADR-041 proposto, padrão HTML/Worker preservado. Gates locais: 1051 testes, 91.39% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.

### BATCH-06 T-81 — review
28 testes novos; subset afetado 119 verdes antes dos 2 casos adicionais de reparenting. Registro atomicamente auditado human; FakeMeta + MockTransport: 3 dias só GET, CSV sintético, zero escritas. Proteções de pausa/ativação/escala/journal/F6, ancestral e ciclo; alerta no teto; relatório sem dupla contagem, vendas não casadas sem atribuição; saída não sobrescreve SQLite. Ruff, pytest, gate de dinheiro (25 módulos), doctor, contratos e detect-secrets verdes; drill 42 byte-idêntico. Banco local recebeu backup + migração 011 para satisfazer doctor; nenhuma migração antiga alterada. ADR-042 proposto. Gates locais: 1079 testes, 91.65% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.

### BATCH-06 T-82 — review
23 testes novos; conjunto afetado 82 verdes. CSV antigo, ranking 54.15/44.97/44.09, serialização sem None novos e tetos antigos preservados; 9 resumos + 8 células de calibração byte-idênticos à main 35dbab5. Permissão negada elimina e bloqueia plano; evidência ausente alerta; prova de mercado declarada e conversão diagnóstica explicadas. Refund por oferta: até 19 transações produtor, com 20 próprio; replays/testes/outras ofertas não inflam amostra. Referências: comissão 6000, refund .2 -> receita 9600/2 vendas e teto G3 14400. Ruff, cobertura/gate dinheiro, doctor, contratos e detect-secrets verdes; drill 42 byte-idêntico. ADR-043 proposto e 3 contratos regenerados; exemplo sintético separado, config/rules e CSV antigo intactos. Gates locais: 1102 testes, 91.75% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.

## BATCH-06 — Entrega para revisão (T-77–T-83)

PR: https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/37
Branch codex/batch-06; base origin/main 35dbab563916bcc3bb428836c3b47d3c1301c5c5 (BATCH-05 #36 mergeado).
Planejamento materializado verbatim em f1f8b82. Um commit de implementação por tarefa, mais LOCK commitado/push antes de cada tarefa. Cards em review; LOCK vazio ao publicar T-83.

### Feito e evidência por tarefa

| Tarefa | Status | Commit implementação | Testes Python adicionados | Suíte na tarefa | Evidência |
|---|---|---|---:|---:|---|
| T-77 | review | d96e41e | 32 | 1000 passed, 0 skips | C opcional; posterior contra Decimal; bloqueia candidato/escala |
| T-78 | review | 886f1d4 | 19 | 1019 passed, 0 skips | 100 seeds × 12 linhas; JSON/MD de duas execuções idênticos |
| T-79 | review | 55c677c | 28 | 1047 passed, 0 skips | perfil local por geo; janela/fuso, Wilson, test:true, modo ro |
| T-80 | review | 789ca51 | 4 | 1051 passed, 0 skips | mais 8 testes Node; 11/11 Worker, capi.ts 100%; nonce no Chromium |
| T-81 | review | f01e41e | 28 | 1079 passed, 0 skips | 3 dias GET + CSV + zero escritas; guardas fumaça/F6/hierarquia |
| T-82 | review | 9b77332 | 23 | 1102 passed, 0 skips | CSV/hash/tetos antigos iguais; refund próprio com 20 únicas |
| T-83 | review | neste commit | 9 | 1111 passed, 0 skips | 12 comandos extraídos do Markdown; 42 testes no subset; origem preservada |

Gates finais: 1111 testes sem skips; cobertura combinada 92.2354% (linhas+branches); 25 módulos de dinheiro >=95%. Ruff check/format, check_coverage, doctor, contratos, detect-secrets verdes; drill seed 42 byte-idêntico ao JSON versionado. npm typecheck e Worker: 11/11, zero skips, capi.ts 100% linhas/branches/funções.
Comandos: `uv run ruff check`; `uv run ruff format --check`; `uv run pytest --cov=arb --cov-branch --cov-report=json:data/coverage.json`; `uv run python scripts/check_coverage.py data/coverage.json`; `uv run arb doctor`; `uv run arb drill run --seed 42 --json` + cmp; `npm --prefix worker test` na T-80.
CI gates + worker confirmado verde em cada HEAD T-77–T-82 antes da tarefa seguinte. Para o HEAD T-83, conferir Checks e corpo do PR; só converter de draft para ready após ambos verdes. Não foi feito merge.

### Cobertura final de dinheiro (linhas + branches)

| Módulo | Cobertura |
|---|---:|
| arb.rules | 100.0000% |
| arb.metrics | 100.0000% |
| arb.launcher | 97.9622% |
| arb.safety | 100.0000% |
| arb.meta.pause | 100.0000% |
| arb.ledger | 100.0000% |
| arb.reconcile | 100.0000% |
| arb.quarantine | 100.0000% |
| arb.db.checkpoint | 97.7011% |
| arb.scout.approve | 100.0000% |
| arb.creative.approve | 100.0000% |
| arb.launcher.scale | 97.0588% |
| arb.remote | 99.4366% |
| arb.remote.journal | 100.0000% |
| arb.remote.launch | 95.8333% |
| arb.drill | 100.0000% |
| arb.tracker.ids | 100.0000% |
| arb.permissions | 100.0000% |
| arb.accept | 96.9925% |
| arb.accept_pause | 100.0000% |
| arb.accept_tracking | 100.0000% |
| arb.readiness | 100.0000% |
| arb.validation | 97.4684% |
| arb.sim.observed | 100.0000% |
| arb.smoke | 100.0000% |

### Bugs encontrados e corrigidos

- Relatório da fumaça contava anúncio reparentado em duas campanhas: atribui ao root observado uma vez, preservando proteção dos IDs originais; teste com referência 6000/6780 centavos e pais ausentes/cíclicos.
- Testes da T-83 reproduziram overwrite do SQLite por observed profile e overwrite de perfil/JSON/HTML na calibração. Recusa antes da escrita, inclusive hardlink/symlink/config, com integridade dos bytes de origem. T-81 também recusa destino do relatório igual ao banco.
- Doctor inicialmente detectou catálogo local sem 011: backup do banco antes da migração nova; doctor passou depois. Nenhuma migração antiga alterada.

### Bloqueios e decisões humanas

Os kits e capacidades estão implementados/testados em simulação; os pontos abaixo bloqueiam aceite/exposição reais, não foram contornados.
- Humano/Claude: revisar PR #37 e merge humano; BATCH-05 #36 já está na main. Ordem: revisão dos contratos/ADRs e T-77→T-83 no mesmo PR, então decisão/merge humano. Nenhum PR anterior de planejamento pendente para esta base.
- Humano: ADR-039/040/041/042/043 seguem **Proposto — aguarda aceite humano**. C permanece None, CAPI false, regras/pesos/CSV antigo/settings intactos. Não ativar por conclusão de testes.
- Humano no próprio host: campanha de fumaça, dados reais locais, evidências assinadas F5/F6/rastreio, V-01–V-06, cartão/spend_cap e instalação/disponibilidade do serviço. Nenhuma privada real no cloud.
- Provedor/humano: versão/permissões, formato de vendas e rastreio, dados/evidência escrita do produtor; não foram inventados. T-79/81/82 aguardam entradas reais para aprendizagem/aceite.
- Executor Graph de exposição T-55 segue ausente (somente FakeMeta); não há liberação para lançamento/aumento real.

### Riscos e limites

- Relatório T-78 usa hipóteses existentes, não dados de mercado: C reduz falsos positivos mas não os zera e aumenta custo; repetidas olhadas, Poisson/prior e amostras/coortes exigem julgamento humano.
- Perfis observados medem tráfego/funil; comissão/refund/orçamento do laboratório continuam hipóteses. Intervalos condicionais e atraso de vendas/reembolsos impedem chamar isso de ROI garantido.
- C confirma mesmo entity/geo; não transfere confirmação implicitamente entre entidades/geos. Planejar transferência explicitamente antes de exposição.
- CAPI best effort após D1, sem retry automático; falha pode perder medição remota, nunca recibo. Pixel/GRAPH_VERSION devem ser correspondentes/verificados pelo humano; registro não prova entrega CAPI.
- Smoke é operado pelo humano: teto só alerta, não pausa; gasto ainda conta nos freios das outras campanhas. Observado/invoice não equivale a aceite assinado.
- Não foi feita API real, deploy, gasto, conta, serviço, mensagem, leitura .env ou privada real. Falha temporária do exec-server foi recuperada, alterações preservadas.

### Prontidão final

Saída real de `uv run arb readiness --json` / `uv run arb readiness`: **não pronto**, ready=false, exit 1. Evidências F5/F6/rastreio sem assinatura são recusadas.

| Pendência | Motivo real |
|---|---|
| preflight | Preflight pendente: credentials, graph_version, meta_spend_cap, card_limit, backup_drill, scheduler_lock |
| drill_recent | Drill de backup ausente/falho ou mais antigo que 48h |
| f5 | evidência não assinada |
| f6_pause | evidência não assinada |
| tracking | evidência não assinada |
| V-01 | Validação do provedor ainda não registrada pelo humano |
| V-02 | Validação do provedor ainda não registrada pelo humano |
| V-03 | Validação do provedor ainda não registrada pelo humano |
| V-04 | Validação do provedor ainda não registrada pelo humano |
| V-05 | Validação do provedor ainda não registrada pelo humano |
| V-06 | Validação do provedor ainda não registrada pelo humano |
| graph_executor | T-55: executor de exposição Graph ausente; somente FakeMeta |
| card_limit | Limite do cartão não confirmado ou preflight/teto pendente |
| spend_cap | spend_cap real não confirmado dentro do teto |
| persistent_host | Host persistente ainda não confirmado |
| service_package | Pacote de serviço ausente/inválido; nenhuma instalação executada |
| service_installed | Instalação/disponibilidade do serviço ainda não confirmada pelo humano |

Não pronto para dinheiro real. Próxima operação é revisão do Claude/humano, não merge automático ou execução real.

### BATCH-06 T-83 — review
9 testes novos; 12 comandos do roteiro português executados contra SQLite sintético + MockTransport (somente GET), subset afetado 42 passed. Regressões reproduzidas antes da correção: observed profile sobrescrevia banco; calibração sobrescrevia entrada/saída. Recusa aliases/hardlinks/symlinks/config antes de escrever; bytes de origem preservados. Ruff, cobertura/gate dinheiro (25 módulos), doctor, contratos e detect-secrets verdes; drill 42 byte-idêntico. Readiness real não pronto, ready=false, 17 pendências; evidência sem assinatura recusada. HANDOFF final inclui tabela, riscos/bloqueios e ordem Claude/humano; nenhum merge. Gates locais: 1111 testes, 92.24% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.


## Revisão bloqueante do PR #37 — T-77 (2026-10-09)

Reprodução confirmada antes da correção: os dois casos novos falhavam com ValueError e interrompiam o ciclo antes das pausas. O avaliador agora sinaliza ConfirmationUnavailable exclusivamente para C desligado ou baseline ausente/inválido. O scheduler isola essa condição por entidade, registra gC.unavailable/insufficient_data com motivo e métricas e pausa a família sem promover candidato ou inventar teto/resultado estatístico. Outros erros não são capturados por esse tratamento.

Evidências: `uv run pytest -q tests/test_gate_c.py tests/test_scheduler.py`: 38 passed. Dois testes de regressão (rollback da configuração C e ausência de baseline) verificam ciclo completo, pausa da entidade C e da outra entidade com sinal ruim, ausência de transação pendente e repetição sem duplicar decisões/ações. Gates completos: ruff check/format, pytest com cobertura: 1113 passed, zero skips; cobertura combinada 92.2468142186452%; check_coverage sem falhas nos 25 grupos de dinheiro (rules 100%); doctor OK; contratos sem drift; detect-secrets verde; drill seed 42 byte-idêntico. CI do novo commit será acompanhado antes da entrega. LOCK liberado ao devolver T-77 a review; merge continua reservado ao humano após revisão do Claude.

### Bloqueios — decisões humanas complementares

- Refund do produtor: sugestão do revisor de usar max(taxa declarada, 15%) até 20 vendas próprias, para reduzir otimismo do produtor. Humano decide alteração da política/ADR-043; comportamento atual preservado nesta correção.
- Campanha de fumaça: não recebe pausa automática, inclusive sob freios/dados atrasados. Humano deve configurar teto de gasto na própria Meta antes de ligar o piloto. O teto local continua apenas alertando; nenhuma campanha real foi criada ou ativada.

O motor continua não pronto para dinheiro real; esta correção não fecha os aceites F5/F6, limites externos ou demais pendências registradas acima.
