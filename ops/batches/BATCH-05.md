# BATCH-05 — Evidência humana assinada e preparo do host do operador

**Dono:** Codex  |  **Revisor:** Claude  |  **Aprovação final e merge:** humano
**Tarefas:** T-72 → T-76 (em `ops/board/todo/`)  |  **Base:** ver "Base de trabalho"
**Tamanho:** curto. O gargalo do projeto agora são ações humanas no mundo real.

## Por que este batch existe
1. Achado da revisão do #34: `arb readiness` aceita evidências e confirmações fabricáveis por
   qualquer agente (hash sem origem; `"by": "human"` como texto). Mesma classe de falha do
   HMAC já corrigida nas aprovações (ADR-022). → T-72, T-73.
2. O humano vai instalar o motor em Windows + WSL. O pacote systemd existe, mas não há
   diagnóstico de WSL/systemd nem plano de instalação exato. → T-74, T-75.
3. Falta um roteiro único em português para os passos humanos. → T-76.

## Base de trabalho
- Se o PR de planejamento do BATCH-05 (branch `claude/inspiring-davinci-o0loro`) **já estiver
  mergeado**: `codex/batch-05` a partir da `main`.
- Se **não** estiver: `codex/batch-05` a partir de `origin/claude/inspiring-davinci-o0loro`.
  Ordem de revisão: planejamento primeiro, depois o batch.

## Ordem
T-72 → T-73 → T-74 → T-75 → T-76.

## Regras
Iguais às do BATCH-04 (`ops/batches/BATCH-04.md`, seção "Regras de execução"), incluindo:
uma branch `codex/batch-05` e um PR draft após a T-72; LOCK por tarefa; quadro com evidência;
gates (ruff, format, pytest com cobertura, check_coverage, doctor, drill seed 42 idêntico ao
versionado); CI verde antes de avançar; `rules.yaml` intocado; LIVE_MODE só em monkeypatch
dentro de testes; nenhuma API real, conta, credencial, `.env`, chave privada real, deploy,
`systemctl` que altere estado ou merge. Assinaturas em testes usam apenas a chave sintética do
conftest. Bloqueios vão para "Bloqueios" no HANDOFF e o trabalho segue.

## Definição de pronto
- `arb evidence sign|verify`, `arb validate record|show`, `arb service status`,
  `arb service install-plan` funcionais e testados.
- `arb readiness` continua **não pronto** no estado do repositório, agora também recusando
  evidência/registro sem assinatura.
- `docs/runbooks/operador.md` completo, com todos os comandos validados por teste.
