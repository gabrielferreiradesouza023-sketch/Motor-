# BATCH-02 — Calibração realista e blindagem pré-dinheiro real

**Dono:** Codex  |  **Revisor:** Claude  |  **Aprovação final:** humano
**Tarefas:** T-31 → T-39 (em `ops/board/todo/`)  |  **Base:** `main` após PR #27

## Por que este batch existe
A F0–F8 está na `main` e verde, mas a revisão (Claude) encontrou três lacunas antes de
qualquer real:
1. O aceite de 50 seeds usa um vencedor irreal (fixo em `o0-a0`, checkout→compra 30%).
   Não sabemos como as regras se comportam com números de mercado.
2. Aprovação humana é só um arquivo; qualquer agente pode forjá-la.
3. O freio de pânico não pausa nada real.

## Ordem e dependências
```
T-31 simulador realista ─► T-32 grid de calibração ─► T-33 proposta (humano decide)
T-34 aprovação assinada ─► T-35 guarda central ─► T-36 escritor de pausa ─┐
T-37 testes de propriedade ─► T-38 cobertura no CI                        ├─► T-39 preflight
                                                    (T-34 + T-36) ────────┘
```
Executar nesta ordem: T-31, T-32, T-33, T-34, T-35, T-36, T-37, T-38, T-39.

## Regras de execução (além de AGENTS.md)
1. **Uma branch, um PR:** `codex/batch-02`, a partir da `main` atualizada. Abra o PR para
   `main` como **draft** logo após a T-31, para o CI rodar a cada push. Um commit
   convencional por tarefa (`feat: T-3X ...`), mais commits de LOCK. Não abrir um PR por
   tarefa (a pilha de 24 PRs do batch anterior gerou retrabalho de merge).
2. **LOCK por tarefa:** escrever `codex | T-3X | <timestamp UTC>` em `ops/LOCK`, commit + push
   antes de começar; liberar (arquivo vazio) ao mover a tarefa para `review`.
3. **Quadro:** `todo → doing → review` por tarefa, com seção "Evidência de conclusão".
4. **Gates por tarefa:** `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`
   (com render: exporte `CHROMIUM_PATH` se necessário), `uv run arb doctor`, e
   `npm --prefix worker test` se tocar no Worker. **CI do PR verde antes da próxima tarefa.**
5. **Proibido neste batch:** alterar `config/rules.yaml` (T-33 só propõe), `LIVE_MODE=true`,
   chamar APIs reais, criar contas/credenciais, ler `.env`, gerar ou ler
   `APPROVAL_SIGNING_KEY` real, deploy, mensagens reais, merge do próprio PR.
6. **Modelos:** qualquer mudança em `arb.models` exige ADR e `arb contracts export`
   (o CI falha se `contracts/` divergir).
7. **Bloqueio:** se uma tarefa exigir decisão humana ou violar a regra 5, pare nela,
   registre no `HANDOFF.md` em "Bloqueios" e siga para a próxima tarefa independente
   (ex.: T-33 bloqueada não impede T-34).
8. **Fim do batch:** atualizar `ops/HANDOFF.md` (feito, falta, riscos, decisões pendentes
   do humano), marcar o PR como "ready for review", liberar o LOCK.

## Definição de pronto do batch
- PR `codex/batch-02` com CI verde (gates + worker).
- `docs/validation/sim-profiles.json`, `calibration-grid.json` e `calibration-proposal.md`.
- Aprovação sem assinatura válida recusada em todos os caminhos de escrita.
- Escritor de pausa testado só com MockTransport; `arb preflight` funcional.
- Nenhuma alteração em `rules.yaml`; nenhum efeito externo real.
