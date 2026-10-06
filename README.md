# arb-engine

Fundação F0 do motor descrito em [docs/arb-engine-spec-v1.md](docs/arb-engine-spec-v1.md).
Python 3.12, uv, Pydantic v2, Typer, SQLite, pytest e Ruff. Simulação é o padrão.
Nenhuma integração externa, decisão de portão ou gasto de mídia está implementado.

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
Nenhum serviço precisa iniciar na F0. Ler AGENTS.md, ops/HANDOFF.md e ops/LOCK antes de trabalhar.

## CLI da F0

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

Nove modelos públicos em `arb.models`, com contratos determinísticos em `contracts/`.
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
é suportada para reembolsos futuros; casamento/importação não está implementado.
Snapshots, decisões e ações são append-only também no SQL. Não há commit oculto no CRUD.

`arb db backup` usa a API de backup do SQLite (inclui WAL), valida integridade e publica
atomicamente. Uma segunda chamada no mesmo dia preserva a primeira cópia. Invocar diariamente
quando houver operação; agendamento contínuo pertence à F8. F0 testa restauração em banco
separado. Não sobrescrever o banco de trabalho nem restaurar com conexões abertas.
Dados, backups, relatórios e artefatos locais são ignorados pelo Git. Os diretórios de fases
futuras estão vazios de implementação.

## Quadro e próximo passo

T-01 a T-04 ficam em `ops/board/review/` para revisão humana; T-05 a T-29 em `todo/`.
F1 começa por T-05: fórmulas puras com divisão por zero retornando None. Depois:
portões, controles, simulador e laboratório de 50 seeds. Aceite F1: encontrar o vencedor
plantado em pelo menos 80% das seeds e waste_ratio médio abaixo de 10%.
Nunca alterar rules.yaml sem ADR; nunca aumentar exposição sem aprovação.
O runbook operacional completo (panic, tokens, operação contínua) pertence à T-29.

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
