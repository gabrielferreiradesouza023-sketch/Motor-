# Handoff — T-01–T-29, validação local concluída

## Estado e bastão
- F0 permanece em main, commit b38638c. Nenhum push/merge posterior em main.
- T-01–T-29 implementadas e em review; aceitações reais F5/F6 continuam pendentes.
- Branch final codex/t-29; PRs encadeados para main. Revisão do Claude antes de merge.
- Branch codex/<tarefa> e commit/push de ops/LOCK cumpridos em cada tarefa deste lote.
- LOCK vazio ao concluir. Ler PRs/board e conferir LOCK antes de retomar.
- Autorização mais recente: avançar tudo que não exige cadastros/gastos. ADR-010
  permite F6–F8 locais antes do aceite real F5; não libera escrita/exposição real.
- Nenhuma conta criada, credencial real alterada, mídia paga, deploy ou mensagem real.
- Históricos: docs/handoffs/f0-and-night-task-log.md e pre-f8-local-batch.md.

## Entregas novas T-21–T-29
- Launcher: planos ABO pausados, 1 oferta/campanha, 1–3 ângulos, 3 criativos/ângulo,
  elegibilidade, destino HTTPS, hash estável e teto diário por oferta. Execute revalida
  aprovação por arquivo/hash/exposição/data e entradas atuais, com idempotência e Actions.
- Launcher é exclusivamente simulado: cria entidades locais sem meta_id, sem HTTP de
  escrita. Ativação local exige aprovação separada e uso único. Somente pausa é autônoma.
- Criativos: três hipóteses usando biblioteca do nicho, evita famílias mortas; copies
  espanhol neutral/CO/PE/MX, lint contra banidos/garantias/números sem fonte. Candidate
  continua candidate. Fonte declarada não é prova: precisa de revisão humana.
- Mídia: HTML escapado → PNG 1080×1350/1920 via Playwright + Chromium instalado.
  DOM recusa overflow; contexto bloqueia rede. ffmpeg cria vídeos H.264/AAC 12s com
  trilha original sintetizada CC0 e metadados de direitos. Não usa serviço pago.
- Scheduler: nove ciclos São Paulo em três dias acelerados, sync→rules→pausa→report→alerts,
  lock flock por banco, checkpoints, replay sem duplicar e backup diário UTC.
  Coleta ausente/falha congela simulação; teto pausa mesmo com hold/pass.
- Alertas locais de freios/stale/pending/unmatched no HTML. Telegram é opt-in com cliente
  explícito; CLI desabilita envio. Testes somente MockTransport; entrega uncertain não
  é repetida automaticamente. Auditoria omite token e respostas externas.
- Runbook: iniciar simulação, gerar candidatos/mídia, panic, backup/restore e trocar token.
  Panic não falsifica estado Meta: remote_pause_pending retorna saída 1. Restore valida
  SQLite/FKs/payloads/checksums e publica em caminho novo, recusando sobrescrita.
- 15 contratos JSON Schema; migrações 001–005; ADRs 001–015 em ops/decisions.md.

## Evidências
- 234 testes pytest passaram, sem skips; Ruff, arb doctor e scanner de segredos verdes.
- Script completo de instalação reexecutado com uv --frozen e npm ci; dependências
  Playwright fixadas em uv.lock. Chromium/ffmpeg/ffprobe já presentes nesta imagem.
- Teste de render produz 3 ângulos × 3 criativos, verifica 18 PNGs e 3 vídeos com ffprobe;
  inspecionada visualmente uma imagem. Overflow e copy sem lint são recusados.
- CLI externo: 11 comandos verdes, incluindo scout/ângulos/copies/render, backup/panic/
  restore/report, três dias acelerados e ciclo offline. docs/validation/f8-runbook.json.
- Nove ciclos e replay: docs/validation/f8-three-days.json. Sem gasto real ou contas.
- F1: 50/50 seeds encontram vencedor, zero vencedores mortos, waste médio 0,9305%.
  Evidência preservada em docs/validation/f1-50-seeds.json, novamente testada na suíte.
- Worker: TypeScript e 2 testes Node verdes. E2E/smoke com D1 local são descritos no README;
  pixel externo é stub; webhook é normalizado de teste. Sem aceite de provedores reais.
- Rotação de token ensaiada com substituição de clientes read-only em MockTransport.
  Nenhum token real emitido, lido de arquivo, exposto, alterado ou revogado.

## PRs e revisão
- PRs #1–#15: T-05–T-20. PRs #16–#24: T-21–T-29. Todos para main, sem merge.
- Lista completa em docs/validation/pull-requests.json. Revisar/mesclar em ordem crescente;
  branches incluem predecessores até seus merges. A branch final contém o lote completo.
- Tarefas continuam review; revisão/aceite não foram feitos em nome do Claude/humano.

## O que continua dependendo do operador
1. Claude revisar os PRs e autorizar/realizar merges. Não merge automático.
2. F5 real: META_ACCESS_TOKEN/AD_ACCOUNT_ID/API_VERSION e V-06, somente leitura,
   conta BRL/São Paulo, mapping real e confirmação de vídeo/actions/video_view.
3. V-01 formato nativo Hotmart e V-02 parâmetro/limite de rastreio. /sale atual normalizado;
   nenhum adaptador nativo confirmado, nenhum Cloudflare deployment. D1 zero só local.
4. Executor Meta de escrita real não implementado. Antes de qualquer exposição, revisar
   barreiras de cartão/conta/orçamentos e aprovações humanas completas da seção 5.
5. Telegram real permanece desabilitado/sem credenciais; ativação futura exige autorização
   de envio e verificação do chat. Não é necessário para proteção local.
6. Cron não instalado: cloud não garante permanência do processo. Host persistente é
   necessário para operação contínua; scheduler local usa flock/Linux, Windows via WSL.

## Ambiente reutilizável e limites
- Rascunho cloud contém install_script/start_skill com Python, Worker e ferramentas de mídia.
  Salvar configuração não executa nem publica. Publicação/restauração em nova tarefa
  continuam não verificadas. Configuração do repo aponta main: código do lote está nas
  branches de PR até revisão/merge; não presumir F8 ao abrir main em uma tarefa nova.
- Requisitos Meta existentes preservados sem valores. Nenhum novo cadastro/secret é
  necessário para testes locais. Nunca pedir valores no chat, ler .env ou LIVE_MODE=true.
- Caches/logs em /workspace/.cache; HOME preservado. worker/.dev.vars ignorado, preservar
  arquivo existente; fixtures públicas de teste não são credenciais de produção.
- Aprovações reais com plan_hash podem gerar falso positivo no scanner: revisar o caso
  específico sem desligar proteção. Não versionar outputs sintéticos em approvals/approved.
- Aproximação diária por coorte permanece ADR-004. Laboratório pode ter P&L global negativo;
  descoberta sintética não prevê lucro. Receita esperada não é saldo reciclável.
- Margens de mídia conservadoras exigem revisão no placement real; lint é heurístico.
- Fonte de sync é injetável; CLI once offline congela simulação, não afirma coleta nova.
  Integração contínua Meta+Worker real e escrita remota permanecem passos futuros.
- Restore pode recuperar entidades ativas anteriores ao panic: parar processos, usar caminho
  novo, executar panic/revisar antes de apontar o scheduler à cópia.

## Próximo passo independente de cadastros/gastos
Revisar os diffs encadeados e corrigir feedback nas respectivas branches com LOCK. O escopo
local das tarefas T-01–T-29 está entregue; não iniciar operação real a partir dos testes.

### Entrega final T-29
PR #24 confirmado: https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/24
Lista de 24 PRs sincronizada com GitHub; evidência final em docs/validation/f8-summary.json.
install_script/start_skill salvos no rascunho cloud, sem publicação automática.

### T-30 (Claude) — teto rígido G3/T
Entregue em `claude/inspiring-davinci-o0loro`, PR sobre `codex/t-29`. ADR-016: G3/T sem
validação morre em 1,5 × teto mesmo com vendas. Próximo: simulador com parâmetros
realistas e vencedores no limite para calibrar G3 (3 vendas dentro de ~R$ 102 é improvável).

## BATCH-02 (planejado por Claude, executado por Codex)
F0–F8 + T-30 mergeados na `main` (#24, #26); CI com render e Worker (#27). T-01–T-30 movidas
para `board/done`. Próximo trabalho: `ops/batches/BATCH-02.md` (T-31–T-39) — simulador
realista e calibração (sem alterar rules.yaml), aprovação assinada, guarda central de escrita,
escritor de pausa (mock), testes de propriedade, cobertura e preflight.

### BATCH-02 T-31
Planted reproduz histórico nas 50 seeds; realistic/pessimistic 200 seeds cada sem erro. Distribuições/posições/summary determinísticos; docs/validation/sim-profiles.json. ADR-017 documenta hipóteses.

### BATCH-02 T-32
Grid 81 variantes × 2 perfis × 100 seeds; duas execuções JSON idênticas, regras validadas em memória e rules.yaml intacto. HTML local ordenável/Pareto. Hard cap não autoriza ultrapassar pausa nominal do simulador.


## Bloqueios
- T-33: proposta documental concluída, aplicação do ADR-018 bloqueada por decisão humana.
  Escolher/rejeitar calibração e tolerância de risco. config/rules.yaml permanece intacto.
  T-34–T-39 são independentes dessa escolha e podem prosseguir em testes locais.

### BATCH-02 T-33
Proposta com 3 opções e números rastreáveis (células 032/040/075), conta financeira G3, ADR-018 Proposto com diff exato. Aplicação bloqueada por decisão humana registrada em Bloqueios; regras intactas.

### BATCH-02 T-34
HMAC-SHA256 canônico em todos os campos, comparação constante e consumo fail-closed. CLI sign exige tty/confirmar e não sobrescreve; verify e aviso doctor. ADR-019/15 contratos atualizados. 50 testes focados verdes com chave sintética, incluindo adulteração de cada campo e launch/activate.
