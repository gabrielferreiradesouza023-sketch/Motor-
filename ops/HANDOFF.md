# HANDOFF — BATCH-03

## Estado atual e ordem de revisão
Repositório gabrielferreiradesouza023-sketch/Motor-. Uma branch codex/batch-03, PR #32:
https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/32
Base usada: origin/claude/inspiring-davinci-o0loro, 6cb06b2 (planejamento PR #31).
main verificada na abertura: a913317; #28, #29 e #30 mergeados. Calibração ADR-018,
Ed25519 T-40 e chave pública T-41 resolvidos; não solicitar outra chave privada/pública.
PR #31 ainda aberto na última verificação desta sessão: revisar/mergear #31 primeiro,
depois #32. Codex não faz merge. Ready for review somente após CI final gates+worker verde.
Histórico anterior preservado em docs/handoffs/historico-ate-t56.md, sem usá-lo como backlog atual.

## Feito
- Ledger órfão/incerto, bloqueio de retry e reconciliação por leitura; pausa remota no scheduler.
- Matrizes de queda/retomada e ingestão com correções apenas das falhas demonstradas.
- Migração nova 006 de quarentena, release interativo, snapshots pré-exposição e restore drill.
- Consumo assinado new_offer, creative_set e scale; envelopes vinculados por hash Ed25519.
- Porta RemoteWriter/FakeMeta e journal de create/activate/scale/pause exclusivamente sintético.
- Contrato documental Graph com lacunas explícitas; nenhum executor real de exposição.
- Drill completo isolado, três seeds e sete incidentes; painel operacional e preflight ampliado.
- Runbook de incidentes: comandos existentes e vínculo a cenários exercitados. Referências
  de campanha no contrato Graph corrigidas para spec §3; sem mudança de mapeamento.

| Tarefa | Quadro | Commit de implementação |
| --- | --- | --- |
| T-42 | review | 5146407 |
| T-43 | review | bbbde95 |
| T-44 | review | 0d8f459 |
| T-45 | review | 8425166 |
| T-46 | review | 1d59e26 |
| T-47 | review | 5702199 |
| T-48 | review | ce454e2 |
| T-49 | review | fc6746f |
| T-50 | review | 43b1a0b |
| T-51 | review | d0918f1 |
| T-52 | review | aab98bf |
| T-53 | review | 537cebd |
| T-55 | review | 01828e7 |
| T-54 | review | f6cf867 |
| T-56 | review | 5abc6c5 |
| T-57 | review nesta entrega | commit final do PR |

Cada card em ops/board/review contém comandos e contagens reais; houve commit/push de LOCK
antes de cada tarefa e liberação ao mover para review. Migrações aplicadas não foram editadas.

## Evidências
647 passed in 180.38s (0:03:00); 0 skips. Cobertura total combinada linhas+branches: 89.36%; todos os 16 grupos de dinheiro/efeito >=95%.
Números completos por módulo em docs/validation/batch03-coverage.json. Ruff check,
ruff format --check, check_coverage.py e arb doctor verdes.
CI de cada implementação T-42–T-56: gates+worker success, SHA e links em
 docs/validation/batch03-ci.json. CI do commit final: aba Checks do PR #32; entrega ready
somente após ambos verdes. Worker não foi alterado; seus testes rodam em cada CI.
Contratos exportados sem drift, detect-secrets verde e rules.yaml intacto em todos os gates.

Drill: seeds 7/42/101 com JSON byte a byte idêntico em duas execuções. Planos de 9/5/13
entidades e 14/10/18 efeitos remotos, sem duplicação. Seis invariantes: autorização,
auditoria, unicidade, pausa após kill, quarentena e totais; todas verdes. Sete incidentes:
pausa incerta, intenção órfã, ciclo interrompido, backup corrompido, restore ativo,
token 190 e quarentena. Referências em docs/validation/drill-seed-*.json. CI executa seed 42
com timeout 120 s. Nada disto valida Meta/Hotmart/Cloudflare reais.

## Bugs reais demonstrados pelas matrizes
- T-45: hook de notificação podia entregar novamente após queda entre entrega e checkpoint.
  Três violações antes da correção; intenção durável notify_hook antes do callback e replay
  sem novo envio. Queda antes da entrega pode perder alerta: relatório local é obrigatório.
- T-48: página atrasada do Worker podia regredir cursor já avançado por outro coletor.
  Uma violação antes da correção; upsert usa MAX nos dois cursores. Replay continua idempotente.
- T-49 resolveu incompatibilidade do envelope {approval, plan} com assinatura de arquivo,
  preservando hash/conteúdo/tipo e assinatura. Não é evidência de API real.

## Bloqueios e decisões pendentes do humano
| Falta | Quem decide | Impacto |
| --- | --- | --- |
| Versão Graph, conta/permissões, lookup/dedupe de criação e limites/erros de taxa documentados | Humano + revisão Claude (V-06) | Executor Graph create/activate/scale bloqueado; T-55 é entrega documental |
| Aceites F5/F6 e V-01 a V-06 com provedores reais | Humano | Não há aceite para dinheiro real |
| Cartão e spend_cap positivos dentro de 240000 centavos, confirmados externamente | Humano | Variáveis e mocks não comprovam limites físicos |
| Host persistente Linux/WSL, supervisor, segredos e observabilidade | Humano | Nenhum deploy/provisionamento foi realizado |
| Revisão e merge #31, depois #32 | Claude/humano | main não recebeu push direto deste batch |
| Retomar ciclo cujo slot já deixou de ser o último vencido | Humano define tarefa futura revisada | CLI once não seleciona slot antigo; não marcar complete manualmente |

Detalhes de Graph em docs/validation/meta-executor-contract.md; checklist real em
 docs/validation/f5-f6-checklist.md. T-54/T-56/T-57 não dependem do executor real bloqueado.

## Riscos remanescentes e próximo bastão
FakeMeta assume dedupe/lookup e estados independentes; não comprova comportamento Graph,
hierarquia, eventos ou desempenho real. Notificação at-most-once pode ser perdida; nunca
usar alerta como única proteção. Restore permanece em quarentena até verificação/confirmar;
backup antigo pode preservar active. Preflight verde é preparação, não aprovação de gasto.

LOCK vazio ao publicar a implementação final. Próximo bastão: Claude revisar PR #32 após
#31, conferir evidências/CI, depois humano decide merges e os aceites acima. LIVE_MODE=false;
sem APIs reais de produto, contas, gastos, deploy, mensagens reais ou chave privada real.
O motor não está pronto para dinheiro real.

### T-57 — Codex, BATCH-03
Runbook comprovado por 11 comandos e 7 cenarios, HANDOFF consolidado e evidencias finais; 2 testes novos.
647 passed in 180.38s (0:03:00); cobertura 89.36%; gates locais verdes.

## BATCH-04 (planejado por Claude, a executar pelo Codex)
- #31 (planejamento BATCH-03) e #32 (BATCH-03, T-42–T-57) revisados e mergeados (ceb98a0).
  Revisão do #32: 647 testes, cobertura de dinheiro sem falhas, drill 7/42 determinístico e
  igual ao versionado. Achados não bloqueantes viraram T-58 e T-59.
- T-42–T-57 movidos para `board/done`.
- Próximo: `ops/batches/BATCH-04.md`, T-58–T-71 — release alinhado, retomada de ciclos,
  desempenho de auditoria, id curto de rastreio (V-02), mapeamento do CSV de vendas (V-01),
  fila de decisões, ack de alertas, permissões, pacote de serviço, kits de aceite F5/F6/rastreio
  (executados pelo humano), conformidade RemoteWriter e painel de prontidão.
- Pendências humanas inalteradas: F5/F6 reais, V-01–V-06, executor Graph (T-55), cartão e
  spend_cap, host persistente. O motor não está pronto para dinheiro real.

### T-58 — Codex, BATCH-04
Release alinha remotos pausados com Action e revalida leitura na transacao; 2 testes novos reproduziram falhas anteriores
649 passed in 193.84s (0:03:13); cobertura 89.39%; gates locais verdes.

### T-59 — Codex, BATCH-04
Catch-up cronologico, skipped auditavel e status; 9 testes novos, migracao 007 e ADR-029; drill 42 identico
658 passed in 240.40s (0:04:00); cobertura 89.35%; gates locais verdes.

### T-60 — Codex, BATCH-04
Consultas indexadas com equivalencia em 100000 Actions: pending 2.68 ms e last_increase 1.66 ms; 2 testes novos; drill 42 identico
660 passed in 206.38s (0:03:26); cobertura 89.31%; gates locais verdes.

### T-61 — Codex, BATCH-04
Fallback de id curto opt-in com aliases historicos e colisoes recusadas; 12 testes novos e golden HTML da base; tracker.ids no gate de 95%; drill 42 identico
672 passed in 204.99s (0:03:24); cobertura 89.45%; gates locais verdes.

### T-62 — Codex, BATCH-04
CSV declarativo, decimal exato e fuso explicito sem perfil de provedor; 18 testes novos; default preservado e drill 42 identico
690 passed in 188.14s (0:03:08); cobertura 89.57%; gates locais verdes.

### T-63 — Codex, BATCH-04
Fila por exposicao e idade, comando de assinatura, contagens de banco e arquivos preservadas; 12 testes novos; redacao e drill 42 identico
702 passed in 203.85s (0:03:23); cobertura 89.67%; gates locais verdes.

### T-64 — Codex, BATCH-04
Ack humano append-only idempotente sem reenvio, preflight de alertas criticos e painel; 8 testes novos; drill 42 identico
710 passed in 217.05s (0:03:37); cobertura 89.83%; gates locais verdes.

### T-65 — Codex, BATCH-04
Artefatos financeiros 0600 e diretorios 0700, symlinks recusados e ACL aviso fora de POSIX; 15 testes novos; permissions 100%; drill 42 identico
725 passed in 210.51s (0:03:30); cobertura 90.0%; gates locais verdes.

### T-66 — Codex, BATCH-04
Pacote systemd deterministico em false, check de hashes horarios modos e flock; 16 testes novos; 2 bypasses de symlink corrigidos; drill 42 identico
741 passed in 214.90s (0:03:34); cobertura 90.02%; gates locais verdes.

### T-67 — Codex, BATCH-04
Kit F5 GET-only no host humano, matriz de 14 testes, evidência redigida com SHA256 e permissões fechadas; drill seed 42 idêntico ao versionado.
755 passed in 206.80s (0:03:26); cobertura 90.18%; gates locais verdes.

### T-68 — Codex, BATCH-04
Aceite de uma pausa com flag explícita, TTY e ledger durável; 26 testes novos e accept_pause 100%; migração 010 aplicada localmente; drill seed 42 idêntico.
781 passed in 221.61s (0:03:41); cobertura 90.11%; gates locais verdes.

### T-69 — Codex, BATCH-04
Suíte de conformidade com 12 casos: FakeMeta apenas, 3 writers defeituosos detectados, timeout recuperável por leitura e orçamento limitado ao pedido autorizado; drill 42 idêntico.
793 passed in 377.95s (0:06:17); cobertura 90.11%; gates locais verdes.

### T-70 — Codex, BATCH-04
Kit de rastreio assinado, CSV descartável e recibos test:true excluídos das métricas; 50 testes novos, accept_tracking 100%, Worker typecheck e 3 testes verdes; ADR-035 e contratos exportados; drill 42 idêntico.
851 passed in 235.48s (0:03:55); cobertura 90.05%; gates locais verdes.
