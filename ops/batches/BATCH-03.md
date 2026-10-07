# BATCH-03 — Robustez operacional: idempotência, reconciliação, retomada e ensaio geral

**Dono:** Codex  |  **Revisor:** Claude  |  **Aprovação final e merge:** humano
**Tarefas:** T-42 → T-57 (em `ops/board/todo/`)  |  **Base:** ver "Base de trabalho"

## Por que este batch existe
Com F0–F8, BATCH-02, Ed25519 (T-40) e a chave pública do humano (T-41) na `main`, o motor
verifica aprovações e pausa com auditoria. A revisão do código atual encontrou lacunas que
precisam estar fechadas **antes** de qualquer aceite real:
1. Intenção de pausa órfã (queda entre intent e resultado) não é detectada nem bloqueia novo POST.
2. Resultado `uncertain` não tem reconciliação: não há caminho para fechá-lo lendo a Meta.
3. O scheduler só alerta `remote_pause_pending` para entidades Meta; não usa o escritor de pausa.
4. Restore pode trazer entidades ativas pausadas depois do backup (ADR-015), sem quarentena.
5. Aprovações `new_offer` não são consumidas; ângulos/criativos não têm aprovação assinada;
   escala (`scale`) não tem proposta nem execução.
6. Não existe porta de escrita remota testável nem ensaio ponta a ponta com falhas.

Isto **não** torna o motor apto a dinheiro real: F5/F6 reais, V-01–V-06 e o executor Graph
(T-55, bloqueado) continuam pendentes.

## Base de trabalho
- Se o PR de planejamento do Claude (branch `claude/inspiring-davinci-o0loro`) **já estiver
  mergeado**: `codex/batch-03` a partir da `main` atualizada.
- Se **não** estiver: `codex/batch-03` a partir de `origin/claude/inspiring-davinci-o0loro`,
  PR para `main`. Ordem de revisão: PR do planejamento primeiro, depois o PR do batch
  (o diff do batch encolhe sozinho após o merge do planejamento).

## Ordem e dependências
```
T-42 ledger ─► T-43 reconcile ─► T-44 scheduler pausa remota ─► T-45 matriz de queda
                     └──────────► T-46 quarentena ─► T-47 backup/drill ─► T-51 escala
T-48 matriz de ingestão (independente)
T-49 new_offer ─► T-50 creative_set
T-52 porta remota + FakeMeta ─► T-53 idempotência ponta a ponta (requer T-51)
T-55 contrato Graph (documental, independente após T-52)
T-54 drill completo (requer T-45, T-46, T-47, T-48, T-49, T-50, T-53)
T-56 painel/preflight (requer T-42, T-46, T-47) ─► T-57 runbook (requer T-54)
```
Executar nesta ordem: T-42, T-43, T-44, T-45, T-46, T-47, T-48, T-49, T-50, T-51, T-52,
T-53, T-55, T-54, T-56, T-57. Se uma tarefa bloquear, seguir para a próxima cuja dependência
esteja satisfeita; voltar às bloqueadas no fim.

## Regras de execução (além de AGENTS.md)
1. **Uma branch, um PR:** `codex/batch-03`. PR para `main` como **draft** logo após a T-42.
   Um commit `feat|fix|test|docs: T-XX ...` por tarefa, mais commits de LOCK.
2. **LOCK por tarefa:** `codex | T-XX | <UTC>` em `ops/LOCK`, commit + push antes de começar;
   liberar (vazio) ao mover para `review`.
3. **Quadro:** `todo → doing → review`, com seção "Evidência de conclusão" (comandos e números).
4. **Gates por tarefa:** `uv run ruff check`, `uv run ruff format --check`,
   `uv run pytest --cov=arb --cov-branch --cov-report=json:data/coverage.json`,
   `uv run python scripts/check_coverage.py data/coverage.json`, `uv run arb doctor`,
   `npm --prefix worker test` se tocar o Worker. **CI do PR (gates + worker) verde antes da
   próxima tarefa.** Módulos novos que decidem dinheiro/efeito externo entram no gate de 95%.
5. **LIVE_MODE:** nunca `true` em shell, CI ou processo. Permitido apenas
   `monkeypatch.setenv("LIVE_MODE", "true")` **dentro de testes** com `httpx.MockTransport`
   ou FakeMeta, como já fazem os testes existentes.
6. **Proibido:** alterar `config/rules.yaml`; APIs reais de produto; contas; credenciais
   reais; ler `.env`; gerar/ler chave privada real (testes usam a chave sintética do conftest
   ou geram uma em `tmp_path`); deploy; mensagens reais; gastos; merge do próprio PR;
   editar migrações já aplicadas (criar 006+); inventar campos/endpoints da Graph API.
7. **Modelos/contratos:** mudança em `arb.models` exige ADR e `arb contracts export`.
8. **Testes úteis:** cada teste compara com uma referência ou planta uma violação; testes que
   só reafirmam a implementação não contam como evidência.
9. **Bloqueio:** se faltar decisão humana, versão, permissão ou informação do provedor,
   registre em "Bloqueios" no `HANDOFF.md` (o que falta, quem decide, impacto) e siga para a
   próxima tarefa independente. Não peça confirmação entre tarefas.
10. **Fim:** `HANDOFF.md` atualizado (feito, evidências, riscos, bloqueios, decisões humanas),
    LOCK liberado, PR **ready for review**, sem merge.

## Definição de pronto
- PR `codex/batch-03` com CI verde; T-42…T-57 em `review` ou bloqueadas com registro.
- `arb ops pending`, `arb ops reconcile`, `arb db release`, `arb db drill`, `arb scout apply`,
  `arb scale propose|apply`, `arb drill run` funcionais e testados.
- Drill com 3 seeds determinísticas e invariantes; 1 seed no CI.
- `config/rules.yaml` intocado; nenhum efeito externo real.
