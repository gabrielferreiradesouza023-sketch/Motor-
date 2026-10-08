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
