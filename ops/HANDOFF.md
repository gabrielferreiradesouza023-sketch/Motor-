# HANDOFF — BATCH-04

## Estado atual e revisão
Repositório gabrielferreiradesouza023-sketch/Motor-, branch `codex/batch-04`, PR #34:
https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/34
Base usada: `origin/claude/inspiring-davinci-o0loro`,
`ab85b95276223a362fa9f7b722ea9e3b094fe6b0` (planejamento PR #33).
Main verificada na abertura: `ceb98a0088805d724ba1d2c311db59fc8f75bf5f`.
PRs #31 e #32 mergeados; achados #32 tratados em T-58/T-59. #33 segue aberto na
verificação desta tarefa: revisar/mergear #33 primeiro, depois #34. Codex não faz merge.
PR só passa a ready for review após CI final gates+worker verde no próprio head.

O motor **não está pronto para dinheiro real**. Chave pública T-41 e calibração ADR-018
já resolvidas; não solicitar nem gerar outra chave. Privada permanece com o humano.
Histórico BATCH-03 e evidências intermediárias BATCH-04 preservados em
[histórico até T-70](../docs/handoffs/historico-ate-t70.md), sem tratar pendências antigas
como estado atual. Este documento substitui o resumo histórico.

## Feito e evidências por tarefa
Todo → doing → review, LOCK publicado antes de código e liberado na entrega de cada tarefa.
Um commit de implementação por tarefa; CI gates+worker verde antes da seguinte.
T-58–T-70 têm registros dos checks por SHA em docs/validation/batch04-ci.md.
T-71 e a cobertura final constam na seção de evidência abaixo e no CI do PR.

| Tarefa | Estado | Commit | Casos novos | Evidência principal |
| --- | --- | --- | ---: | --- |
| T-58 | review | a17daf0 | 2 | release alinha PAUSED local e revalida remoto |
| T-59 | review | cbd5cf9 | 9 | retomada running/failed; ciclos perdidos auditados |
| T-60 | review | 9dee93f | 2 | 100k Actions: pending 2,68 ms / last_increase 1,66 ms |
| T-61 | review | 2a0f566 | 12 | ids curtos opt-in; golden padrão byte-idêntico |
| T-62 | review | 82bd95c | 18 | mapa CSV canônico; moeda/data declarativas sem inferência |
| T-63 | review | b8201a6 | 12 | fila ordenada e HTML 0/1/3, sem segredos |
| T-64 | review | f741196 | 8 | ack humano append-only; alertas críticos bloqueiam |
| T-65 | review | 364ec16 | 15 | arquivos 0600/dirs 0700; symlinks recusados |
| T-66 | review | 20ef57d | 16 | 6 templates determinísticos; nunca instalar |
| T-67 | review | 1dd881a | 14 | F5 GET-only, falhas e prova redigida |
| T-68 | review | ad4abba | 26 | flag explícita; pausa durável; GET/reconciliação |
| T-69 | review | a4b6a17 | 12 | FakeMeta e três writers defeituosos detectados |
| T-70 | review | ee391cb | 58 | 50 casos do kit + 8 na guarda; Worker 3 testes; P&L isolado |
| T-71 | review | commit que contém este handoff | 47 | prontidão bloqueada mesmo com provas sintéticas verdes |

## Validação final
Gates por tarefa: ruff check/format, pytest com linhas+branches, check_coverage, doctor,
contratos exportados sem drift, detect-secrets e drill seed 42 byte-idêntico ao versionado.
Worker tocado somente em T-70: typecheck e npm test (3 testes, zero skips) verdes.
Módulos novos tracker.ids, permissions, accept, accept_pause, accept_tracking e readiness entram
no gate de 95%. Cobertura combinada por módulo: docs/validation/batch04-coverage.json.
Final local: 898 passed in 229.93s (0:03:49); zero skips; cobertura combinada total 90.26%; 22 grupos de dinheiro >=95%, sem falhas.
A seção T-71 abaixo contém os comandos finais efetivamente medidos.

Drill 42: seis invariantes e sete incidentes verdes; 5 entidades, 10 efeitos remotos FakeMeta,
35 Actions no restore drill, pending=0, quarentena preservada, somente synthetic-only.
Saída idêntica ao golden em docs/validation/drill-seed-42.json; sem regenerar o golden.

`arb readiness --json` neste checkout retorna exit 1, **não pronto**. Verificados:
permissions e approval_public_key. Pendências: preflight, drill_recent, f5, f6_pause,
tracking, V-01–V-06, graph_executor, card_limit, spend_cap, persistent_host,
service_package e service_installed. A saída real está em docs/validation/batch04-readiness.json.
O drill sintético verde do batch não é o drill recente de backup do host de produção.

## Bugs reais encontrados e correções
- Restore release deixava local ativo após remoto PAUSED: reconciliação local auditada,
  revalidação remota e rollback se estado mudar (T-58).
- once não retomava running/failed antigos: retoma cronologicamente e registra ciclos
  perdidos como skipped, sem executar decisões retroativas (T-59, migração 007).
- CLI backup resolvia symlink antes de recusá-lo; preflight ainda abria banco após
  detectar caminho financeiro inválido: testes de violação falharam antes; ambos corrigidos
  em T-66, com prova de nenhuma leitura do alvo.
- IDs curtos/aliases recusam colisão com ids completos, sem remapear história (T-61).
- Flags de teste do Worker não geram MetricSnapshot, inclusive no consumo posterior de
  produção; CSV sintético só em cópia descartável (T-70).

## Bloqueios e decisões pendentes do humano
| Falta | Quem decide/executa | Impacto/tarefas |
| --- | --- | --- |
| Revisão/merge #33, depois #34 | Claude/humano | publicação em main; Codex não mergeia |
| V-01–V-06 e dados/permissões/versão reais do provedor | humano | CSV real, rastreio, kit F5/F6, T-55 |
| Aceites F5, F6 de uma entidade de teste e rastreio | humano no próprio host | kits T-67/T-68/T-70 entregues/testados com mocks; validação real pendente |
| Executor Graph de exposição, contrato aprovado e conformidade | humano + PR futuro | T-55; criação/ativação/escala reais indisponíveis; FakeMeta apenas |
| Limites do cartão e spend_cap dentro do teto | humano/emissor/Meta | defesa externa obrigatória, nunca inferida por agentes |
| Host persistente, backups/restore e relógio | humano | drill recente e disponibilidade operacional |
| Revisão/instalação dos serviços no host correto | humano | T-66 só renderiza/verifica; nenhuma instalação executada |
| Rastreamento uncertain após perda de resposta | humano/revisão técnica | não reenviar; consultar ledger/export; reconciliador existente não fecha tracking_test automaticamente |

Registrar confirmações reais revisáveis em ops/validation-status.json (todos pending nesta
entrega) e provas revisadas em ops/validation/{f5,f6_pause,tracking}.json. Não inventar valores
V-01–V-06. Não colocar segredos, dados de cartão ou chave privada no repositório.

## Riscos e limites
- Testes e conformidade atuais são MockTransport/FakeMeta; não provam comportamento do
  provedor real. Graph continua sempre bloqueado em readiness deste batch.
- SHA256 detecta alteração, não autentica executor/origem. Evidências e registro humano
  exigem revisão; painel usa dados locais recentes, não monitoramento remoto em tempo real.
- Windows requer validação de ACLs/host Linux ou WSL; bits POSIX não certificam ACLs.
- Kits podem persistir intent/uncertain sem prova exportada se o host cair; ledger e GET
  de reconciliação precedem qualquer nova tentativa. Ack de alerta não confirma entrega.
- Serviço verificado não equivale a instalado. Templates forçam simulação; eventual operação
  real exige decisão e implementação futuras, sem alterar esses gates por conveniência.
- Migrações novas 007–010; aplicar com arb db migrate no host após backup/revisão. Não editar
  migrações já aplicadas nem sobrescrever banco no restore.

LIVE_MODE permaneceu false no shell/processo do agente. Modo true apenas dentro de testes
com MockTransport/FakeMeta. Nenhuma API real de produto, conta, gasto, deploy, mensagem,
instalação, chave privada real ou leitura de .env. config/rules.yaml intacto.

### T-71 — Codex, BATCH-04
Painel read-only não pronto com 19 checks, 47 testes novos e readiness 100%; 898 testes sem skips, 22 grupos de dinheiro verdes; drill 42 repetido byte-idêntico; HANDOFF e evidências finais atualizados.
898 passed in 229.93s (0:03:49); cobertura 90.26%; gates locais verdes.

## BATCH-05 (planejado por Claude, a executar pelo Codex)
- #33 e #34 (BATCH-04, T-58–T-71) revisados e mergeados (e42a46f). Revisão do #34: 898
  testes, drill 42 idêntico, readiness "não pronto". Achado: evidências/confirmações do
  readiness sem prova de origem → T-72/T-73.
- T-58–T-71 movidos para `board/done`.
- Próximo: `ops/batches/BATCH-05.md`, T-72–T-76 (curto): evidência assinada, registro
  assinado de V-01–V-06/limites, diagnóstico WSL/systemd, plano de instalação do serviço,
  guia do operador.
- Humano (decidido em 2026-10-08): instalar host/serviço em simulação agora; Hotmart, Meta e
  limites no fim de semana; aceites reais bloqueados até lá.

### BATCH-05 T-72 — review
14 testes novos: origem, adulteração, chave divergente, TTY e chave ausente; evidência sem assinatura recusada. Gates locais: 912 testes, 90.36% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.

### BATCH-05 T-73 — review
28 testes novos; registro liga assinatura ao item, recusa cópia/edição/vencimento e mantém pending atual. validation >=95%. Gates locais: 940 testes, 90.47% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.
