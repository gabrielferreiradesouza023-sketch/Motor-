# Handoff — lote F1–F4 e implementação local da F5

## Estado atual e bastão
- F0 está em main (commit b38638c). Trabalho posterior somente em branches codex/.
- T-01 a T-20 implementadas e entregues para review; F5 (T-19/T-20) SEM aceite real.
- T-21 a T-29 em todo. Nenhuma escrita Meta, campanha, gasto, deploy ou merge realizado.
- Branch final do lote: codex/t-20. Branches encadeadas: revisar e mesclar em ordem.
- Política do usuário: branch codex/<tarefa>, commit/push de ops/LOCK no início;
  PR para main; Claude revisa antes do merge. Nunca push direto em main.
- LOCK vazio ao concluir esta sessão. Verificar também branches/PRs antes de começar.
- Histórico da F0 e diário por tarefa preservados em docs/handoffs/f0-and-night-task-log.md.

## Entregas
- F1: métricas oficiais, portões 1/2/3/T, mínimos de amostra, teto, dados atrasados,
  controles globais e laboratório com verdade plantada. regras.yaml não foi calibrado.
- F2: P&L por dimensão/coorte, receita tardia/reembolso, reopened apenas no relatório,
  relatório HTML móvel escapado com uma pergunta e biblioteca persistida de ângulos.
- F3: importadores CSV estritos, filtros, ranking, top 3 em aprovação pending de exposição
  zero e prompt versionado de coleta manual. Exemplos explicitamente sintéticos.
- F4: ponte educativa em espanhol, Worker TS com D1, origem/auth/rate limit,
  export paginado, vendas CSV, cursores atômicos, replay, casamento e reembolso.
- F5 local: Graph exclusivamente GET, paginação/retry/rate limit, reconciliação humana,
  deltas de insights cumulativos e correções negativas append-only. Coleta parcial grava
  failed e last_collection retorna None; não liberar pass com coleta incompleta.
- 14 contratos JSON Schema, migrações SQLite 001–004 e ADRs 001–009.

## Evidências
- 184 testes pytest passaram, sem skips; Ruff, doctor e pre-commit verdes.
- F1 em 50 seeds: vencedor em 50/50, zero vencedores mortos, waste médio 0,9305%.
  Dados por seed em docs/validation/f1-50-seeds.json; teste faz novamente o ensaio.
- Worker: TypeScript verificado, 2 testes Node passaram e smoke funcional no D1 local:
  origem inválida 403, auth ausente 401, idempotência e rate limit 429.
- F4 E2E executou JS gerado (navegador simulado), chamadas reais ao Worker/D1 local,
  visita→clique→venda falsa casada→replay sem duplicação→reembolso com receita zerada.
  SDK externo do pixel foi substituído, nenhuma chamada Meta no E2E.
- Banco/relatório/biblioteca de exemplo gerados localmente; outputs ficam ignorados.
- CLI scout corrigida para opções documentadas e verificada por smoke automatizado.

## PRs e publicação
- GitHub API bloqueou primeiro com 403; retentativa posterior funcionou, PRs abertos.
- Lista de PRs do lote em docs/validation/pull-requests.json e no resumo da sessão.
- Nenhum PR foi mesclado. Base main por instrução do usuário; dependências explícitas.
- PRs encadeados incluem predecessores até seus merges; revisar na ordem T-05→T-20.

## Pendências que bloqueiam o avanço para F6
- META_ACCESS_TOKEN, META_AD_ACCOUNT_ID e META_API_VERSION ausentes na máquina.
- F5 exige validar V-06 e executar arb sync meta em conta real BRL/São Paulo com
  LIVE_MODE=false. Mapeamento explícito de anúncio desconhecido exige oferta e geo.
- Testes Meta até aqui usam transporte HTTP simulado; não afirmar integração real.
- V-01 webhook nativo Hotmart e V-02 parâmetro/limite de rastreio permanecem pendentes;
  /sale recebe contrato normalizado de testes, sem adaptador nativo confirmado.
- Nenhum deployment Cloudflare realizado. ID D1 zero é exclusivo do ambiente local.

## Configuração cloud e segurança
- install_script/start_skill atualizados no rascunho com setup Python e Worker local.
- Domínios api.github.com e graph.facebook.com declarados; secret requirement
  META_ACCESS_TOKEN e variáveis META_AD_ACCOUNT_ID/META_API_VERSION salvas sem valores.
- Inserir valores em configurações do ambiente de forma segura, nunca no chat ou Git.
  Revisar/salvar e publicar pelo produto; nova tarefa restaurada ainda não foi verificada.
- Script install_script completo foi reexecutado com uv --frozen e npm ci; sucesso.
- Worker local iniciado nesta sessão foi encerrado após validar E2E; start_skill descreve reinício.
- Caches e logs usam /workspace/.cache; HOME não foi modificado. TLS/assinaturas mantidos.
- worker/.dev.vars contém apenas fixtures locais criadas nesta sessão; é ignorado, não
  imprimir ou sobrescrever arquivo existente. Nunca usar fixtures em produção.
- Não ler .env, rodar LIVE_MODE=true, aumentar exposição ou refatorar fora da tarefa.
- Aprovação real new_offer pode sinalizar hash como alta entropia no scanner de segredos;
  auditar falso positivo específico antes de versionar, sem desativar proteção global.

## Próximo passo
1. Claude revisa os PRs na ordem; resolver feedback nas respectivas branches.
2. Preencher requisitos F5 via ambiente, validar versão/permissões V-06 e testar leitura real.
3. Só após aceite F5, pegar T-21 em nova branch codex/t-21 e publicar LOCK imediatamente.
4. T-21–T-23: launcher com hash/aprovação/idempotência e apenas pausa automática;
   nenhum teste de exposição real sem arquivo humano aprovado e barreiras da seção 5.
5. T-24–T-29: criativos, scheduler/alertas e runbook, ainda não implementados.

## Limites conhecidos
- Atribuição diária tardia usa coorte da primeira atividade, aproximação documentada em ADR-004.
- O sucesso sintético não prevê lucro real; laboratório completo pode ter P&L negativo mesmo
  encontrando um combo vencedor. Receita esperada não é reciclada no caixa.
- Hook de vídeo via actions/video_view aguarda confirmação V-06 na versão Meta escolhida.
- Snapshot.ts registra coleta; period_start permite atribuição diária do insight.
- Reopened é indicador de revisão e não reativa anúncios.

### T-21 — 2026-10-06T02:26:08.529331+00:00
Plano ABO determinístico e pausado, limites e elegibilidade revalidados. Desenvolvimento local autorizado; aceitações reais F5/F6 continuam pendentes.

### T-22 — 2026-10-06T02:27:17.853065+00:00
Execução dry-run auditada, aprovação por arquivo e hash, revalidação no banco e idempotência transacional. Sem cliente de escrita externa. ADR-010 consolidado no caminho ops/decisions.md.

### T-23 — 2026-10-06T02:28:27.073165+00:00
Somente pausa automática; ativação simulada com aprovação separada e consumo único. Estado remoto observado não é falsificado; escrita Meta real segue bloqueada.

### T-24 — 2026-10-06T02:29:21.168483+00:00
Gerador determinístico de três hipóteses em espanhol, biblioteca elimina famílias mortas e prioriza evidências positivas; CLI persiste somente candidatos.

### T-25 — 2026-10-06T02:30:46.984393+00:00
Copies neutras e CO/PE/MX com lint contra termos banidos, promessas e números sem fonte declarada; candidatos sem aprovação automática. Fontes exigem conferência humana.

### T-26 — 2026-10-06T02:36:42.752553+00:00
Render real 3×3: PNG 1080×1350/1920 e três vídeos H.264/AAC de 12s. Overflow recusado no DOM, rede bloqueada e trilha original CC0. Playwright usa Chromium local, sem serviço pago.

### T-27 — 2026-10-06T02:39:55.063202+00:00
Nove ciclos São Paulo em três dias acelerados, lock de processo, checkpoints e replay sem duplicação. Sync ausente/falho congela simulação; freios antes de relatório/alertas. Evidência docs/validation/f8-three-days.json.

### T-28 — 2026-10-06T02:42:25.572491+00:00
Alertas de freio/stale/pending/unmatched no relatório e auditoria local; Telegram opt-in somente via adaptador explícito, testado com MockTransport. Entrega incerta não é repetida; nenhum envio real.
