# BATCH-07 — Ligar o motor em modo observação

**Dono:** Codex  |  **Revisor:** Claude  |  **Aprovação final e merge:** humano (delegável ao Claude)
**Tarefas:** T-84 → T-88  |  **Base:** `main` com BATCH-06 (#37) mergeado
**Tamanho:** médio. Tudo em simulação; nenhum gasto, conta ou API real.

## Por que este batch existe
Em 2026-10-10 o humano decidiu começar a operar com a campanha de fumaça (criada e operada
por ele, teto baixo). O motor já tem `smoke register/report`, `sync meta` (GET, roda em
simulação) e `observed profile`, mas:
1. Não existe um go/no-go para "observar": `arb readiness` só responde à pergunta "posso
   gastar com o motor?" (não, por T-55). → T-84.
2. A rotina diária são vários comandos e o alerta de teto só aparece no relatório; o humano
   precisa de um comando único, com código de saída claro para "pause agora". → T-85.
3. Os runbooks estão espalhados (operador, piloto, host, incidentes). → T-86.
4. Decisões humanas de 2026-10-10 que mudam ADRs propostos:
   - **1A:** gasto extra do Portão C (além do teto do G3) exige arquivo aprovado em
     `ops/approvals/`. → T-87.
   - **2A:** antes de 20 vendas próprias, refund = max(declarado, `settings.refund_rate`). → T-88.
   - Aceite dos ADR-039 a 043 com esses ajustes. C e CAPI continuam desligados. → T-87, T-88.

## Decisões já tomadas (não reabrir; registrar nos ADRs)
- Modo observação: `LIVE_MODE=false`; motor nunca escreve na fumaça (ADR-042 continua valendo).
- Tetos da fumaça (decisão humana, valores ficam fora do código): cartão R$300, spend_cap da
  conta R$300, limite da campanha R$220, teto local `--cap-cents 25000` (bruto).
- Portão C e CAPI desligados até o laboratório. Aceitar ADR não liga nada.

## Ordem e dependências
T-84 (readiness observe) → T-85 (smoke daily) → T-86 (runbook dia 1, valida comandos das
anteriores) → T-87 (Portão C com aprovação) → T-88 (piso de refund + aceites).
T-87 e T-88 são independentes de T-84..T-86, mas seguem esta ordem por causa do LOCK.
