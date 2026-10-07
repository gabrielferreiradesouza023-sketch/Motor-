# BATCH-04 — Prontidão operacional e kits de aceite para o humano

**Dono:** Codex  |  **Revisor:** Claude  |  **Aprovação final e merge:** humano
**Tarefas:** T-58 → T-71 (em `ops/board/todo/`)  |  **Base:** ver "Base de trabalho"

## Por que este batch existe
BATCH-03 (#32) fechou idempotência, reconciliação, quarentena e o drill em simulação. A revisão
do Claude e a inspeção da `main` (ceb98a0) deixaram dois tipos de trabalho:
1. **Achados e lacunas internas:** release de quarentena deixa estado local divergente;
   `scheduler once` não retoma ciclos antigos; consultas de auditoria varrem todas as Actions;
   alertas at-most-once sem confirmação humana; permissões de arquivos não verificadas; não
   existe id curto de rastreio (fallback da V-02 previsto na spec) nem mapeamento de colunas
   do CSV de vendas (V-01).
2. **Pendências humanas que o código pode facilitar sem executá-las:** pacote de serviço para
   host persistente, kits de aceite F5 (leitura), F6 (pausa real de uma entidade de teste) e
   rastreio, suíte de conformidade para o futuro executor Graph e um painel de prontidão que
   nunca diz "pronto" sem evidência humana.

Os kits são **executados pelo humano** no próprio host. O Codex só os implementa e testa com
MockTransport. Isto continua **não** tornando o motor apto a dinheiro real.

## Base de trabalho
- Se o PR de planejamento do BATCH-04 (branch `claude/inspiring-davinci-o0loro`) **já estiver
  mergeado**: `codex/batch-04` a partir da `main` atualizada.
- Se **não** estiver: `codex/batch-04` a partir de `origin/claude/inspiring-davinci-o0loro`.
  Ordem de revisão: PR do planejamento primeiro, depois o PR do batch.

## Ordem e dependências
```
T-58 release alinhado ─► T-59 retomada de ciclos ─┐
T-60 desempenho de auditoria (independente)        │
T-61 id curto ─► T-62 mapeamento CSV ─────────┐    │
T-63 fila de decisões ─► T-64 ack de alertas  │    │
T-65 permissões ─► T-66 pacote de serviço ◄───┼────┘
T-65 ─► T-67 aceite F5 ─► T-68 aceite pausa F6│
T-69 conformidade RemoteWriter (independente) │
T-61 + T-62 ─► T-70 aceite rastreio ◄─────────┘
T-64, T-65, T-66, T-67, T-68, T-69, T-70 ─► T-71 painel de prontidão
```
Executar nesta ordem: T-58, T-59, T-60, T-61, T-62, T-63, T-64, T-65, T-66, T-67, T-68,
T-69, T-70, T-71. Se uma tarefa bloquear, seguir para a próxima com dependências satisfeitas
e voltar às bloqueadas no fim.

## Regras de execução (além de AGENTS.md)
1. **Uma branch, um PR:** `codex/batch-04`. PR para `main` como **draft** logo após a T-58.
   Um commit `feat|fix|test|docs: T-XX ...` por tarefa, mais commits de LOCK.
2. **LOCK por tarefa:** `codex | T-XX | <UTC>` em `ops/LOCK`, commit + push antes de começar;
   liberar (vazio) ao mover para `review`.
3. **Quadro:** `todo → doing → review`, com "Evidência de conclusão" (comandos e números).
4. **Gates por tarefa:** `uv run ruff check`, `uv run ruff format --check`,
   `uv run pytest --cov=arb --cov-branch --cov-report=json:data/coverage.json`,
   `uv run python scripts/check_coverage.py data/coverage.json`, `uv run arb doctor`,
   `uv run arb drill run --seed 42 --json` (deve seguir idêntico ao versionado, salvo mudança
   justificada em ADR com o JSON regenerado), `npm --prefix worker test` se tocar o Worker.
   **CI do PR (gates + worker) verde antes da próxima tarefa.** Módulos novos que decidem
   dinheiro ou efeito externo entram no gate de 95%.
5. **LIVE_MODE:** nunca `true` em shell, CI ou processo do agente. Somente
   `monkeypatch.setenv("LIVE_MODE", "true")` dentro de testes com MockTransport/FakeMeta.
   Os kits T-67/T-68/T-70 exigem LIVE/rede **no host humano**; o agente nunca os executa
   contra serviços reais.
6. **Proibido:** alterar `config/rules.yaml`; APIs reais de produto (Meta, Hotmart, Cloudflare,
   Telegram, Worker publicado); contas; credenciais reais; ler `.env`; gerar/ler chave privada
   real; deploy; `systemctl`/instalação de serviço; mensagens reais; gastos; merge de PR;
   editar migrações aplicadas (criar novas); inventar endpoints, campos, formatos de CSV ou
   valores de V-01–V-06.
7. **Configuração:** mudanças em `config/settings.yaml` ou novos YAML só com padrão que
   preserve o comportamento atual byte a byte e ADR.
8. **Testes úteis:** cada teste compara com referência ou planta uma violação.
9. **Bloqueio:** faltando decisão humana, versão, permissão ou dado do provedor → registrar em
   "Bloqueios" no `HANDOFF.md` (o que falta, quem decide, impacto) e seguir. Sem pedir
   confirmação entre tarefas.
10. **Fim:** `HANDOFF.md` atualizado, LOCK liberado, PR **ready for review**, sem merge.

## Definição de pronto
- PR `codex/batch-04` com CI verde; T-58…T-71 em `review` ou bloqueadas com registro.
- Comandos novos funcionais e testados: `arb scheduler status`, `arb ops alerts|ack`,
  `arb service render|check`, `arb accept f5|pause|tracking`, `arb readiness`.
- `arb readiness` no estado do repositório retorna **não pronto** com a lista correta.
- `config/rules.yaml` intocado; nenhum efeito externo real.
