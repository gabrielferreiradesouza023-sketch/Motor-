# arb-engine

Motor descrito em [docs/arb-engine-spec-v1.md](docs/arb-engine-spec-v1.md), com
T-01–T-29 implementadas para revisão. F1–F4 e F7/F8 têm validação local; F5/F6
continuam com aceite real pendente. Python 3.12, uv, Pydantic, Typer e SQLite.
Simulação é o padrão. Não houve campanha real, gasto, deploy ou merge deste lote.

## Preparar o desenvolvimento

Execute na raiz deste checkout (no cloud: `/workspace/Motor-`):

```bash
export UV_CACHE_DIR=/workspace/.cache/uv
export PRE_COMMIT_HOME=/workspace/.cache/pre-commit
export LIVE_MODE=false
uv sync --frozen
uv run pre-commit install
uv run arb doctor
uv run ruff check
uv run pytest
uv run pre-commit run --all-files
```

Em uma máquina pessoal, as duas variáveis de cache podem ser omitidas. `uv.lock` fixa
as dependências. Não criar outro worktree para tarefas cloud: usar o checkout isolado existente.
O desenvolvimento Python não exige serviço externo. Chromium, ffmpeg e ffprobe
são necessários para os testes de mídia; Playwright usa o Chromium instalado,
sem baixar outro browser. No cloud atual essas ferramentas já estão disponíveis.
Em Linux sem elas, instalar pelos pacotes oficiais do sistema antes dos testes.
Ler AGENTS.md, ops/HANDOFF.md e ops/LOCK antes de trabalhar.

## CLI local

```bash
uv run arb --help
uv run arb contracts export              # regenere somente após ADR de modelo
uv run arb db migrate                    # migrações numeradas e checksum
uv run arb db backup                     # um backup por dia UTC, últimos sete dias
uv run arb doctor                       # config, contratos, banco, modo seguro
```

O `doctor` cria e migra `data/engine.db` se ele ainda não existir e a configuração e os
contratos forem válidos. Em banco existente, verifica em modo somente leitura:
integridade, FKs, migrações/checksums, tabelas, payloads e presença das proteções append-only.
Banco desatualizado exige `arb db migrate`; banco corrompido não é recriado silenciosamente.
`doctor --root <diretório>` permite verificar outra raiz. Erros retornam exit code 1.
Configuração inválida ou LIVE_MODE diferente de false impede a inicialização do banco.

Credenciais ausentes são avisos na F0. O programa não lê `.env`, nem exibe valores de
variáveis: usa apenas o ambiente exportado. `.env.example` documenta nomes para fases
futuras. Não fornecer credenciais para validar F0. `meta_api_version` aguarda V-06/F5.

## Persistência e contratos

Quinze contratos públicos em `arb.models`, com contratos determinísticos em `contracts/`.
Centavos são inteiros não negativos; `price_local` também é centavos na moeda local.
Timestamps exigem fuso horário; portões são strings `0`, `1`, `2`, `3`, `T`.
As interpretações iniciais estão em `ops/decisions.md`.

```python
from pathlib import Path
from arb.db import Repository, connect, migrate
from arb.models import Offer

connection = connect(Path("data/engine.db"))
try:
    migrate(connection)
    offers = Repository(connection, Offer)
    # with connection: offers.add(offer)  # transação controlada pelo chamador
    existing = offers.list()
finally:
    connection.close()
```

Cada modelo tem seu repositório tipado. Chave de snapshot: `(entity_id, ts)`; demais: `id`.
Vendas têm `hotmart_tx_id` único; repetir inserção falha sem duplicar. Atualização de venda
é suportada para reembolsos; importação CSV, casamento e sincronização do Worker estão implementados.
Snapshots, decisões e ações são append-only também no SQL. Não há commit oculto no CRUD.

`arb db backup` usa a API de backup do SQLite (inclui WAL), valida integridade e publica
atomicamente. Uma segunda chamada no mesmo dia preserva a primeira cópia. Invocar diariamente
quando houver operação; agendamento contínuo pertence à F8. F0 testa restauração em banco
separado. Não sobrescrever o banco de trabalho nem restaurar com conexões abertas.
Dados, backups, relatórios e artefatos locais são ignorados pelo Git. Launcher,
criativos e scheduler têm implementações locais; integração live não é habilitada.

## Quadro e próximo passo

T-01 a T-29 ficam em `ops/board/review/` para revisão humana. O usuário autorizou
F6–F8 local antes do aceite real de F5 (ADR-010). Main contém apenas F0;
as demais tarefas estão em branches `codex/` e PRs encadeados, sem merge.
F1 foi validada em 50 seeds: 100% de descoberta e waste médio 0,93%, sem calibrar regras.
Resultados completos em `docs/validation/f1-50-seeds.json`. Esse cenário sintético não
prevê lucro real. Nunca alterar rules.yaml sem ADR ou aumentar exposição sem aprovação.

```bash
uv run arb sim run --seed 42 --budget 2400 --database data/simulation-new.db
uv run arb report --database data/simulation-new.db
uv run arb library archive --database data/simulation-new.db
uv run arb library query excel_produtividade --database data/simulation-new.db
```

Use banco novo para simulação; não sobrescrever dados existentes.

## Scout — coleta CSV (F3)

Exemplos sintéticos em `examples/scout/`; não são ofertas ou links reais.
UTF-8, vírgula, cabeçalho exato na ordem apresentada, booleanos `true`/`false`,
valores monetários em centavos inteiros, datas ISO `YYYY-MM-DD`.

`offers.csv`: `id,hotmart_product_id,name,niche,language,commission_brl_cents,price_local,currency,allows_paid_traffic,sales_page_url,affiliate_link,native_spanish,sales_page_quality,popularity,policy_risk`.
Qualidade manual 1–5, popularidade 0–100, risco 0–1. Niche usa os identificadores de policy.yaml.

`adlibrary.csv`: `offer_id,advertiser_id,first_seen,observed_at,active`.
Um anunciante por oferta, datas verificáveis. Não inventar tempo de atividade.

```bash
uv run arb scout import --offers examples/scout/offers.csv --adlibrary examples/scout/adlibrary.csv --database data/scout-example.db
```

Cabeçalho alterado, linha duplicada ou inválida é recusado antes da gravação.
A avaliação manual permanece no CSV fonte; o banco contém os contratos Offer.

Para a triagem completa:

```bash
uv run arb scout rank --offers examples/scout/offers.csv --adlibrary examples/scout/adlibrary.csv --database data/scout-example.db
```

O resultado gera proposta `new_offer` em `ops/approvals/pending/`, sem aprovar automaticamente.
Use o prompt versionado `src/arb/scout/collect_prompt.md` para a coleta assistida no navegador.

## Worker local (F4)

Node 24, npm e dependências fixadas em worker/package-lock.json. Execute na raiz:

```bash
npm --prefix worker --cache /workspace/.cache/npm ci --no-audit --no-fund
npm --prefix worker run typecheck
npm --prefix worker test
export XDG_CONFIG_HOME=/workspace/.cache/config
export WRANGLER_LOG_PATH=/workspace/.cache/wrangler/logs
export WRANGLER_SEND_METRICS=false
CI=1 npm --prefix worker run db:local
npm --prefix worker run dev
```

O ID zero em wrangler.toml é exclusivo de D1 local; não executar deploy com esse ID.
ALLOWED_ORIGIN deve corresponder exatamente à origem da ponte. POST /event tem CORS,
validação de payload e limite persistido no D1 de 60 requisições por minuto/IP (hash).
POST /sale exige X-Hotmart-Hottok correspondente a SALE_TOKEN. GET /export exige
Authorization Bearer SYNC_TOKEN, com cursores/paginação. Tokens ausentes recusam acesso.
A rota /health consulta D1; não basta uma porta aberta.

Para os testes locais, crie **somente se não existir** `worker/.dev.vars` com valores
sintéticos `SALE_TOKEN=local-sale-fixture-only` e `SYNC_TOKEN=local-sync-fixture-only`.
Não sobrescrever configurações existentes. Nunca usar esses valores em produção.
O arquivo é ignorado pelo Git e os valores são fixtures públicas sem credenciais reais.
Depois de iniciar o Worker, execute `uv run python worker/test/smoke.py` para testar
D1, origem, autenticação, repetição de eventos e rate limit. Repetir imediatamente pode
exigir esperar a próxima janela de minuto do rate limit.

A rota /sale aceita o contrato normalizado documentado no teste; o formato nativo do
webhook Hotmart ainda depende de V-01. Não foi feito deploy, nem afirmado suporte real
à conta Hotmart. Reembolso é um novo evento com novo id e o mesmo hotmart_tx_id.
Wrangler pode avisar sobre Request.cf não disponível no proxy; o teste local usa o
fallback documentado e não depende de metadados reais de borda.

## Vendas e eventos (F4)

```bash
uv run arb sales import sales.csv
uv run arb sync events --worker-url https://worker-do-operador.example
# Com wrangler dev e fixtures locais configuradas:
uv run python worker/test/e2e.py
```

A URL acima é um placeholder, não um serviço publicado. `sync events` lê
TRACKER_SYNC_TOKEN exportado no processo; nunca lê .env. O E2E usa somente tokens
sintéticos conhecidos, roda o JS gerado num contexto de navegador simulado e faz chamadas
reais ao Worker/D1 local. O SDK externo do pixel é substituído no teste, sem chamadas Meta.
Cobre visita, clique, parâmetro no redirect, venda falsa, casamento, replay e reembolso.

CSV de vendas: cabeçalho exato `hotmart_tx_id,ts,commission_cents,status,tracking_param`.
Timestamp ISO com fuso, comissão em centavos; status approved/refunded/chargeback.
Rastreio vazio permanece unmatched no relatório. Repetir a mesma venda não duplica;
reembolso atualiza status sem apagar histórico. Divergência de comissão/rastreio é recusada
com rollback. Páginas de exportação têm commit atômico e cursores para retomada após falha.

V-01 (webhook real) e V-02 (parâmetro Hotmart real) continuam pendentes. O receptor é
normalizado para testes; não foi conectado a Hotmart, Cloudflare remoto ou Meta.

## Meta somente leitura — F5 com aceite real pendente

```bash
# Requisitos exportados de forma segura: META_ACCESS_TOKEN, META_AD_ACCOUNT_ID,
# META_API_VERSION (validar V-06; settings.yaml também aceita meta_api_version).
uv run arb sync meta --since 2026-10-01 --until 2026-10-05 --mapping-file mapping.json
```

Exemplo de mapping explícito para anúncios ainda desconhecidos:

```json
{"123456789": {"offer_id": "excel", "geo": "CO"}}
```

Usar IDs reais e ofertas existentes no banco; nunca inventar geo ou comissão. O cliente
faz somente GET, verifica BRL/São Paulo, pagina por cursor e respeita rate limit/retry.
Não segue URLs next externas, não envia token na query e sanitiza erros. Configuração de
nova oferta ou geo do laboratório não altera a conta Meta.

Insights diários cumulativos geram apenas deltas. Snapshot.ts registra coleta e
period_start a data da conta. Restatements negativos ficam em MetricAdjustment append-only
e são incorporados ao P&L. Todas as páginas devem terminar antes da gravação; erro causa
rollback e ciclo failed. `last_collection` retorna None se o último ciclo falhou, bloqueando
consumidores futuros de tomar pass com coleta parcial. Reconciliação audita mudanças
observadas como actor=human; não desfaz edições e não faz nenhuma escrita externa.

**Ainda não validado com conta real:** token, conta e versão estão ausentes neste ambiente.
Os testes usam transporte HTTP simulado, sem alegar integração Meta real. O campo de
views de vídeo usa actions/video_view e também deve ser confirmado na validação V-06.
F6–F8 possuem código local: launcher dry-run, render de mídia e ciclos acelerados.
Escrita Meta e operação real continuam pendentes; testes locais não substituem esse aceite.

## Branches e revisão

Trabalhar sempre em `codex/<tarefa>`, commit e push de ops/LOCK no início. Entregar PR para
main e aguardar revisão do Claude antes do merge. Nunca fazer push direto em main.
As branches deste lote são encadeadas por dependência; revisar/mesclar em ordem crescente.
A F0 foi enviada a main antes desta instrução; nenhuma tarefa posterior foi enviada a main.
A criação dos PRs foi bloqueada inicialmente pelo proxy a api.github.com; uma retentativa
posterior funcionou. Links do lote em docs/validation/pull-requests.json. Nada foi mesclado.


## Runbook: iniciar sem contas ou gastos

Na raiz, `LIVE_MODE=false`. Para dados sintéticos, sempre escolher bancos novos:

```bash
uv run arb scheduler simulate --database data/night-sim.db --output reports/night-sim
uv run arb report --database data/night-sim.db --output reports/night-sim
uv run arb panic --database data/night-sim.db
```

O primeiro comando roda três dias acelerados, nove ciclos 09:00/18:00/23:30 São Paulo,
com replay idempotente. Usa tráfego sintético; nenhuma API é acessada. Recusa banco
existente. Evidência desta entrega: `docs/validation/f8-three-days.json`.

`arb scheduler once --database data/night-sim.db --output reports/night-sim` executa
o último slot vencido com fonte **offline ausente**: congela entidades simuladas e
reporta stale. Não atribui frescor a dados antigos nem inicia integração externa.
A interface Python `run_cycle(sync_source=...)` permite conectar fontes somente leitura
já verificadas; a integração operacional Meta+Worker completa ainda exige aceite real.

Em host Linux persistente, depois da revisão, o operador pode configurar cron local:

```cron
CRON_TZ=America/Sao_Paulo
0 9,18 * * * cd /caminho/Motor- && LIVE_MODE=false uv run arb scheduler once --database data/night-sim.db >> data/scheduler.log 2>&1
30 23 * * * cd /caminho/Motor- && LIVE_MODE=false uv run arb scheduler once --database data/night-sim.db >> data/scheduler.log 2>&1
```

Cron não foi instalado nesta sessão. O cloud pode ser encerrado; execução contínua
requer host persistente. Locks/checkpoints são por banco; repetir um ciclo completo
retorna o resultado anterior. Falha de relatório pode ser retomada sem repetir proteção.
Não reativar entidades ao virar o dia automaticamente. Windows: usar WSL neste estágio,
pois a trava do scheduler usa flock. Não afirmar compatibilidade nativa sem validar.

## Runbook: pausa de emergência

```bash
uv run arb panic --database data/engine.db
```

Pausa todas as entidades **simuladas** ativas, com Action auditável. Repetição é segura.
Se houver entidade observada da Meta, `remote_pause_pending` lista IDs e o comando sai
com código 1: não houve pausa remota. Nesse caso pausar diretamente no Gerenciador
Meta e verificar status/orçamento, além de parar o scheduler. Não interpretar alteração
local como efeito na conta. Este projeto ainda não possui adaptador de escrita live.

## Runbook: backup e restauração

```bash
uv run arb db backup --database data/engine.db --output data/backups
uv run arb db restore data/backups/engine-YYYY-MM-DD.db --database data/recovered.db
uv run arb panic --database data/recovered.db
uv run arb report --database data/recovered.db --output reports/recovered
```

Trocar YYYY-MM-DD pelo arquivo produzido. Backup diário é UTC e mantém sete cópias;
a primeira cópia do dia não é substituída. `restore` verifica integridade, FKs, payloads
e migrações/checksums, migra versões antigas válidas e publica somente em caminho novo.
Recusa sobrescrever arquivos existentes. Não substituir engine.db com conexões abertas.
Parar processos, restaurar em banco separado, executar panic e conferir relatório antes
de apontar o scheduler à cópia recuperada. Uma cópia anterior ao panic pode conter
entidades ativas; a restauração não inventa histórico de pausas.

## Runbook: ângulos, copies e mídia

```bash
uv run arb scout import --offers examples/scout/offers.csv --adlibrary examples/scout/adlibrary.csv --database data/creative-demo.db
uv run arb creative angles excel --database data/creative-demo.db
uv run arb creative copies ANGLE_ID --region CO --database data/creative-demo.db
uv run arb creative render CREATIVE_ID --database data/creative-demo.db --output data/creatives
```

Substituir IDs pelos JSONs retornados. Também há `neutral`, `PE` e `MX`. Exemplos são
sintéticos, sem afiliado real. O gerador consulta aprendizados do nicho para evitar
famílias mortas; ângulos e criativos permanecem candidate. Lint é uma checagem editorial
conservadora, não uma garantia de conformidade: conferir fontes, tradução e política.
Números em copy exigem fonte declarada; o render CLI conservador recusa copy quantitativa
sem esse contexto. PNGs têm 1080×1350/1920; vídeos usam slides e trilha original CC0,
12s H.264/AAC. Overlays reais exigem revisão de placement. HTML arbitrário não é aceito.

## Runbook: lançamento somente simulado

A interface `arb.launcher.plan` exige oferta/ângulos/criativos approved e lint passed,
1 campanha/oferta, até 3 conjuntos, exatamente 3 criativos/conjunto, destino ponte HTTPS
e geos CO/PE. Plano ABO distribui orçamento diário total de até 6000 centavos por oferta;
a aprovação não elimina a necessidade de controlar o teto global de todas as ofertas.

`arb.launcher.serialize` e `plan_hash` produzem documento e hash. O humano revisa o
plano completo e um Approval de kind launch, decide status approved/decided_at e salva
`ops/approvals/approved/ID.json`. Não gerar aprovação humana automaticamente. O scanner
pode sinalizar hashes de plano: revisar falso positivo específico sem desativar proteção.

`arb.launcher.execute.execute(connection, plano, ID)` valida arquivo, hash, exposição
e dados atuais, cria entidades **simuladas e pausadas**, gera ops/dry_runs e Action
simulated. Replay não duplica. Ativação simulada usa `arb.launcher.actions.activate`
com outro Approval kind activate e hash de `activation_intent`. Aprovação consumida
não reativa depois de pausa. Escala/criação/ativação nunca são ações autônomas.

Para operação real: aguardar revisão dos PRs, aceite F5/V-06, validações Hotmart V-01/V-02,
barreiras de cartão/conta Meta e novo executor de escrita validado. Não usar LIVE_MODE=true.
F6 nesta sessão não teve campanha real criada/ativada, nem teste de gasto.

## Runbook: trocar token com segurança

1. Parar o scheduler/serviços que usam o token. Não imprimir token nem conteúdo de .env.
2. Obter/rotacionar a credencial pelo provedor e salvar pelo mecanismo seguro de secrets
   do ambiente. Isso depende da conta do operador; não foi realizado aqui.
3. Reiniciar o processo para usar o novo ambiente; não alterar o banco ou versionar secrets.
4. Com Meta: confirmar conta BRL/São Paulo e versão via operação somente leitura;
   `arb sync meta` exige mapeamento explícito para anúncios desconhecidos. Erro de auth
   mantém coleta failed; não liberar pass a partir de coleta parcial.
5. Worker: atualizar SALE_TOKEN/SYNC_TOKEN no serviço e TRACKER_SYNC_TOKEN no cliente
   pelo mecanismo seguro. Validar /health e export autenticado; não registrar Bearer.
   Não sobrescrever worker/.dev.vars existente; fixtures locais são somente testes.
6. Revogar a credencial anterior no provedor após verificar a nova. Telegram é opcional:
   CLI não envia; adaptador precisa de autorização/configuração explícitas. Timeout é
   entrega uncertain, sem reenvio automático para evitar mensagens duplicadas.

A troca foi ensaiada com dois tokens sintéticos em MockTransport, sem expor valores
nem contactar provedores. Nenhuma credencial real foi emitida, alterada ou revogada.
