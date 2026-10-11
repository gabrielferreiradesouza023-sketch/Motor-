# BATCH-08 — Operar a fumaça em 12/10

**Dono:** Codex  |  **Revisor:** Claude  |  **Merge:** Claude (delegado pelo humano)
**Tarefas:** T-89 → T-93  |  **Base:** `main` com BATCH-07 (#38) mergeado
**Tamanho:** pequeno/médio. Tudo em simulação; nenhum gasto, conta, mensagem ou API real.

## Por que este batch existe
1. `arb smoke daily` reaproveita `sync` de conta inteira: qualquer anúncio da conta que não
   seja da fumaça (antigo, pausado, ou o post de aquecimento) derruba a coleta com exit 3.
   Reproduzido em 2026-10-11 contra 0df45a9. Bloqueia a operação. → T-89.
2. O spend_cap de R$300 é da **conta**, não da campanha. O daily só mostra o gasto da fumaça;
   o humano não vê quanto o resto da conta já consumiu do mesmo limite. → T-89.
3. `readiness --scope observe` diz o que falta, mas não o comando que resolve. → T-90.
4. Para importar vendas reais o humano precisa montar o mapa CSV sem expor dado de comprador.
   → T-91.
5. Runbook e ADRs precisam refletir 1–4 e o aceite delegado de ADR-044..046. → T-92, T-93.

## Decisões já tomadas (não reabrir)
- Modo observação; motor nunca pausa a fumaça (ADR-042). Tetos: cartão R$300, spend_cap da
  conta R$300, limite da campanha R$220, teto local `--cap-cents 25000` (bruto).
- Aquecimento (post de engajamento) pode rodar na mesma conta da fumaça; o motor ignora
  essas entidades na reconciliação, mas conta o gasto delas contra o spend_cap da conta.
- Portão C e CAPI desligados. ADR-044, 045 e 046 passam a **Aceito** por decisão delegada
  ao Claude em 2026-10-11, revisável pelo humano.

## Ordem
T-89 (bloqueante) → T-90 → T-91 → T-92 (runbook valida T-89..T-91) → T-93 (ADRs + handoff).
