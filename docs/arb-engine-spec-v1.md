# arb-engine — Spec e Plano de Implementação v1.0

> **Para agentes (Codex / Claude Code):** este documento é a fonte da verdade do projeto. Leia inteiro antes da primeira tarefa. Execute as fases na ordem, uma tarefa por vez, seguindo o protocolo da seção 9. Na dúvida entre duas interpretações, escolha a que **gasta menos dinheiro** e registre em `ops/decisions.md`.

**Objetivo:** motor que descobre, valida e escala combinações lucrativas de oferta × ângulo × criativo × geo em tráfego pago (Meta Ads), com desperdício mínimo de verba e operação humana de ~10 min/dia.

**Arquitetura:** monorepo Python (motor, regras, relatórios) + Cloudflare (páginas-ponte e receptor de eventos), SQLite como fonte única da verdade, módulos que só conversam por contratos (JSON Schema). Simulação é o modo padrão; dinheiro real exige flag explícita e aprovação humana.

**Stack:** Python 3.12, uv, pydantic v2, typer, sqlite3, jinja2, httpx, pytest, ruff · Cloudflare Pages + Workers (TypeScript) + D1 · Meta Marketing API (Graph API, versão configurável).

---

## 0. Princípios inegociáveis

1. **O motor pode sempre gastar menos sozinho; nunca gastar mais sem aprovação humana.** Pausar é automático. Criar campanha, ativar anúncio ou aumentar verba exige um arquivo aprovado em `ops/approvals/`.
2. **Matar no sinal mais barato, confirmar só no dinheiro.** Toda entidade passa por portões com teto de gasto. Sem sinal, ela morre no teto.
3. **Nenhuma decisão com amostra insuficiente.** Toda regra tem amostra mínima. Abaixo dela, o estado é `insufficient_data`, nunca `kill` ou `pass`. O teto de gasto é a única exceção.
4. **Defesa em profundidade:** limite no cartão, limite na conta Meta, orçamento por campanha, regras do motor e aprovação humana. O código nunca é a única barreira.
5. **Simulação por padrão.** `LIVE_MODE=false` em qualquer ambiente novo.
6. **Tudo auditável:** cada ação com efeito externo gera uma linha na tabela `actions`, com a entrada, a saída, o operador e o id da aprovação.
7. **Nunca deletar entidades na Meta.** Só pausar. O histórico é um ativo.

---

## 1. Sanity check: o que mudou em relação à versão conversada

| # | Problema encontrado | Correção aplicada |
|---|---|---|
| 1 | Otimizar a campanha para clique atrai "clicadores" que não compram. Otimizar para compra é inviável, porque o Meta precisa de dezenas de eventos por semana. | Evento intermediário de otimização: `InitiateCheckout`, disparado no clique da página-ponte para o checkout. Tem volume suficiente e é próximo da compra. |
| 2 | Thompson sampling com R$ 2,4 mil de mídia tem amostra pequena demais para guiar a operação e briga com o algoritmo de entrega do Meta. | O MVP usa regras determinísticas com amostra mínima. O alocador bayesiano entra como módulo v2, desligado por flag, alimentado pelo histórico. |
| 3 | Sem amostra mínima, a variância mata vencedores cedo. | Cada métrica tem `min_sample` (impressões, visitas ou cliques) antes de qualquer veredito. |
| 4 | Comissão da Hotmart é liberada só depois do prazo de garantia e há reembolsos. A receita "bruta" engana. | A receita é tratada como **receita líquida esperada** (comissão × (1 − taxa de reembolso)). O caixa de comissões é tratado como **não reciclável** até fevereiro. |
| 5 | A fatura do Meta no Brasil embute impostos. O CPC do painel não é o custo real. | Todo custo é **gasto bruto** = gasto no painel × (1 + `media_tax_rate`). O padrão é 0,13, recalibrado pela primeira fatura. |
| 6 | A API pública da Ad Library não cobre anúncios comerciais fora da UE. | O scout é semiautomático: a coleta é feita via navegador (Claude in Chrome ou manual) para CSV, e a pontuação é automática. |
| 7 | Não é garantido que o afiliado tenha webhook de venda na Hotmart. | O tracker tem dois modos: webhook, se disponível, ou importação do CSV de vendas. O casamento venda → anúncio é feito pelo parâmetro de rastreio. Item de validação V-01. |
| 8 | A premissa "o que vence no laboratório vence na escala" não é garantida. Poder de compra e preço exibido variam por país. | A transferência entre geos é uma hipótese com portão próprio (teto de R$ 80 por vencedor por geo novo), não uma promoção automática. |
| 9 | O fuso e a moeda da conta Meta não podem ser alterados depois. | O checklist obriga BRL e `America/Sao_Paulo`, alinhados ao relatório da Hotmart. |
| 10 | Nichos de emprego e educação formal caem em categoria especial do Meta, que restringe segmentação. Saúde e finanças geram ban e conflito. | Lista fechada de nichos permitidos e proibidos (seção 2.3). |
| 11 | "Desperdício zero" não estava medido. | Meta-métricas: `waste_ratio` e `cost_per_learning` no relatório diário. |
| 12 | Não havia critério de encerramento do projeto. | Checkpoint de stop-loss em R$ 1.200 e critério de encerramento em R$ 2.400 (seção 5.4). |

---

## 2. Tese e escopo

### 2.1 Tese
**Testar onde o clique custa centavos, escalar onde a venda vale mais.** O laboratório roda em geos hispânicos de CPM baixo. O que vence é transferido, com portão próprio, para geos de maior poder de compra. Cada vitória alimenta a **biblioteca de ângulos**, que reduz o custo de descobrir o próximo vencedor. O moat é a velocidade e o custo de aprendizado, não um anúncio específico.

### 2.2 Escopo por fase de capital

| | Laboratório (out/2026 a jan/2027) | Escala (a partir de fev/2027) |
|---|---|---|
| Capital | R$ 3.000 (mídia: R$ 2.400 brutos) | Aporte novo, definido em fevereiro |
| Modelo | Afiliado Hotmart, produtos em espanhol | Mesmo modelo + arbitragem de busca (RSOC) multi-idioma |
| Geos | Laboratório: CO, PE. Transferência: MX | MX, ES, hispânicos nos EUA (segmentação por idioma); Europa no RSOC |
| Meta do período | 1 a 2 combos validados + motor calibrado | Lucro recorrente |

### 2.3 Nichos
- **Permitidos (priorizar):** inglês para hispânicos, ofícios e beleza (manicure, barbearia, sobrancelha), confeitaria e gastronomia, pets (adestramento), artesanato e crochê, Excel e produtividade, fotografia com celular.
- **Proibidos:** saúde, emagrecimento, suplementos, finanças, crédito, investimentos, renda rápida, apostas, emprego, conteúdo adulto, relacionamento/sedução.
- **Proibido em qualquer nicho:** cloaking, perfis falsos, depoimentos inventados, promessa de resultado garantido, uso de marca de terceiros sem autorização, lance em nome de marca.

---

## 3. Mecânica: funil de portões

Todos os valores abaixo ficam em `config/rules.yaml` e são calibráveis. Os valores atuais são pontos de partida.

### Portão 0: triagem de oferta (custo zero de mídia)
- **Entrada:** CSV de ofertas coletado do marketplace da Hotmart + CSV de anúncios observados na Ad Library.
- **Pontuação (0–100):**
  - Comissão líquida esperada em BRL (peso 30)
  - Prova de mercado: nº de anunciantes ativos há 30 dias ou mais (peso 25)
  - Qualidade da página de vendas: nota manual de 1 a 5 (peso 15)
  - Temperatura/popularidade na Hotmart (peso 15)
  - Risco de política: penalidade (peso −15)
- **Filtros eliminatórios:** nicho proibido; produtor proíbe tráfego pago de afiliado; comissão menor que R$ 40; página de vendas fora do espanhol nativo.
- **Saída:** top 3 ofertas → arquivo de aprovação humana.

### Estrutura de campanha no laboratório
- 1 campanha por oferta, orçamento por conjunto (ABO).
- 1 conjunto por ângulo (máximo 3 ângulos por oferta).
- 3 criativos por conjunto.
- Público amplo: país + idioma espanhol + 18–65. Sem interesses no laboratório, para que o resultado reflita o criativo e não a segmentação.
- Destino: página-ponte própria → link de afiliado com parâmetro de rastreio.
- Otimização: `InitiateCheckout` (clique ponte → checkout). Se o evento não acumular volume em 72 h, o fallback é `LandingPageView`.

### Portão 1: atenção (por criativo)
- **Teto:** R$ 15 brutos por criativo.
- **Amostra mínima:** 1.000 impressões.
- **Mata se**, após a amostra: hook rate < 25% (vídeo) **ou** CTR de link < 0,8%.
- **Passa se:** CTR de link ≥ 1,2% (e hook ≥ 30% para vídeo).
- **Entre os limites:** continua até o teto. No teto, sem passar, morre.

### Portão 2: intenção (por ângulo/conjunto)
- **Teto:** R$ 60 brutos por conjunto.
- **Amostra mínima:** 40 visitas à ponte.
- **Mata se:** taxa ponte → checkout < 8%.
- **Passa se:** taxa ≥ 15%.

### Portão 3: dinheiro (por oferta × ângulo)
- **Teto:** 2 × comissão líquida esperada.
- **Mata se:** atingiu o teto com 0 vendas.
- **Mata também se:** atingiu 1,5 × o teto sem validar, mesmo com vendas (ADR-016).
- **Valida (vira "combo validado") se:** ≥ 3 vendas **e** ROI esperado ≥ 30% no acumulado **e** CPC bruto ≤ EPC × 0,7.

### Portão T: transferência de geo
- Combo validado ganha um teste no geo de escala, com teto de R$ 80 e os mesmos critérios do Portão 3, recalculados por geo.

---

## 4. Métricas: definições oficiais

Todas são calculadas em `modules/metrics/` e são a única fonte para regras e relatórios.

| Métrica | Fórmula |
|---|---|
| `spend_gross` | `spend_platform × (1 + media_tax_rate)` |
| `hook_rate` | `video_3s_views / impressions` (somente vídeo) |
| `ctr_link` | `link_clicks / impressions` |
| `cpc_gross` | `spend_gross / link_clicks` |
| `bridge_rate` | `checkout_clicks / bridge_views` |
| `rev_expected` | `Σ commission × (1 − refund_rate)`; `refund_rate` padrão 0,15 até haver 20 vendas próprias |
| `epc` | `rev_expected / bridge_views` |
| `max_cpc` | `epc × 0,7` |
| `roi_expected` | `(rev_expected − spend_gross) / spend_gross` |
| `waste_ratio` | gasto em entidades mortas **acima** do que a regra exigiria (por atraso de execução ou falha de amostra) ÷ `spend_gross` total. **Meta: < 10%** |
| `cost_per_learning` | `spend_gross / nº de vereditos (pass + kill) com amostra mínima` |
| `cash_at_risk` | teto restante do orçamento − gasto do dia corrente |

Regra de arredondamento: valores monetários em centavos (inteiro) no banco. A conversão para exibição ocorre só no relatório.

---

## 5. Controles

### 5.1 Camadas de proteção (todas obrigatórias)
1. **Cartão virtual dedicado**, com limite igual ao orçamento total de mídia bruto.
2. **Limite de gastos da conta Meta**, configurado no painel, igual ao orçamento de mídia.
3. **Orçamento diário por conjunto**, criado pelo launcher e nunca acima do valor aprovado.
4. **Regras do motor**, executadas a cada ciclo (seção 5.2).
5. **Aprovação humana** para qualquer aumento de exposição.

### 5.2 Regras de execução
- **Ciclos:** 2×/dia (09:00 e 18:00, horário de São Paulo), mais o ciclo de fechamento às 23:30.
- **Teto diário global:** R$ 60 brutos no laboratório. Ao atingir 90%, o motor pausa tudo até o dia seguinte.
- **Freio de emergência:** ROI do dia < −50% com gasto do dia > R$ 30 → pausa tudo e cria um alerta.
- **Escala:** no máximo +20% de orçamento por conjunto a cada 24 h. Sempre exige aprovação.
- **Dados atrasados:** se a última coleta de métricas tiver mais de 6 h, o motor não toma decisão de `pass`, só de `kill` por teto, e gera um alerta.

### 5.3 Segurança dos agentes
- Credenciais só em `.env` (fora do git), com `.env.example` versionado. Hook de pre-commit para varredura de segredos.
- Toda escrita na API do Meta passa por `launcher.execute(plan, approval_id)`. O plano é serializado e recebe um hash. A aprovação referencia esse hash. Se o hash divergir, a escrita é recusada.
- Toda escrita usa chave de idempotência. Repetir o mesmo plano não duplica entidades.
- Com `LIVE_MODE=false`, o launcher só escreve o plano em `ops/dry_runs/` e registra na tabela `actions` com status `simulated`.

### 5.4 Critérios de encerramento do laboratório
- **Checkpoint (R$ 1.200 gastos):** se nenhuma entidade passou do Portão 2 → o motor pausa tudo e gera um relatório de revisão para decisão humana (trocar ofertas, ângulos ou nicho).
- **Fim (R$ 2.400 gastos):** se nenhum combo foi validado no Portão 3 → a frente de afiliado é encerrada. O motor, a biblioteca e o histórico seguem para a frente RSOC em fevereiro.

---

## 6. Rotina do operador humano

- **Diária (~10 min):** abrir `reports/latest.html`, ler o P&L e responder à única pergunta de decisão do dia, se houver, aprovando ou rejeitando o arquivo em `ops/approvals/pending/`.
- **Semanal (~30 min):** aprovar novas ofertas do scout e novos ângulos, e revisar `waste_ratio` e `cost_per_learning`.
- **O humano nunca opera o painel do Meta**, exceto para o setup inicial e emergências. Toda mudança manual deve ser registrada com `arb log-manual`.

---

## 7. Setup de contas (checklist humano, antes da Fase 5)

Siga a ordem abaixo. Itens marcados com ⚠️ são irreversíveis.

- [ ] E-mail dedicado à operação + gerenciador de senhas + 2FA por aplicativo em todas as contas.
- [ ] Domínio próprio, neutro, sem nome de nicho (ex.: um nome de "estúdio de conteúdo").
- [ ] Cloudflare (plano gratuito): DNS do domínio, Pages, Workers e D1.
- [ ] Hotmart: conta no CPF, cadastro como afiliado, pedido de afiliação às ofertas aprovadas no Portão 0.
- [ ] Meta Business Manager criado a partir do perfil pessoal real. Nenhum perfil adicional.
- [ ] Verificação do domínio no Business Manager.
- [ ] Pixel/Dataset criado e vinculado ao domínio. Eventos `PageView`, `ViewContent` e `InitiateCheckout` configurados por código na ponte.
- [ ] Conta de anúncios: ⚠️ moeda **BRL**, ⚠️ fuso **America/Sao_Paulo**.
- [ ] Limite de gastos da conta = orçamento de mídia.
- [ ] Cartão virtual dedicado, com limite = orçamento de mídia.
- [ ] Meta for Developers: app em modo de desenvolvimento, usuário do sistema no Business Manager com acesso à conta de anúncios, token com permissões `ads_read` e `ads_management`.
- [ ] (Opcional) Bot de Telegram para alertas.
- [ ] Preencher `.env` a partir do `.env.example`.

**Nota fiscal para o operador:** comissões recebidas no CPF são renda tributável e devem ser declaradas. Converse com um contador antes do primeiro saque relevante.

---

## 8. Arquitetura

### 8.1 Estrutura do repositório

```
arb-engine/
├── AGENTS.md                  # constituição dos agentes (Codex lê nativamente)
├── CLAUDE.md                  # 1 linha: "Leia e siga AGENTS.md"
├── README.md
├── pyproject.toml             # uv, ruff, pytest
├── .env.example
├── config/
│   ├── rules.yaml             # portões, tetos, amostras mínimas
│   ├── settings.yaml          # geos, ciclos, tax_rate, refund_rate
│   └── policy.yaml            # nichos proibidos, termos banidos em copy
├── contracts/                 # JSON Schema (gerados dos modelos pydantic)
├── ops/
│   ├── LOCK                   # dono atual do bastão
│   ├── HANDOFF.md             # estado atual / último passo / próximo passo
│   ├── decisions.md           # ADRs curtos, numerados
│   ├── board/{todo,doing,review,done}/   # 1 tarefa = 1 .md
│   ├── approvals/{pending,approved,rejected}/
│   └── dry_runs/
├── src/arb/
│   ├── cli.py                 # typer: `arb <comando>`
│   ├── models/                # pydantic: Offer, Angle, Creative, Entity, Snapshot, Sale, Decision, Approval, Action
│   ├── db/                    # conexão, migrações SQL numeradas, repositórios
│   ├── metrics/               # fórmulas da seção 4 (funções puras)
│   ├── rules/                 # portões, vereditos, freio de emergência
│   ├── sim/                   # simulador de tráfego com "verdade plantada"
│   ├── scout/                 # importação de CSVs + pontuação do Portão 0
│   ├── creative/              # ângulos → copies → imagens/vídeos; lint de política
│   ├── bridge/                # gerador de páginas-ponte (jinja2 → HTML estático)
│   ├── tracker/               # ingestão de vendas (webhook D1 ou CSV) + casamento
│   ├── meta/                  # cliente Graph API: read (insights) e write (plano)
│   ├── launcher/              # plano → aprovação → execução idempotente
│   ├── analyst/               # P&L diário, biblioteca de ângulos, relatório HTML
│   └── scheduler/             # orquestra os ciclos
├── worker/                    # Cloudflare Worker (TS): /event, /sale, /health
├── bridges_out/               # HTML gerado para deploy no Pages
├── reports/                   # latest.html + histórico datado
├── data/engine.db             # SQLite (fora do git) + backups diários
└── tests/
```

### 8.2 Modelos e contratos (campos mínimos)

- **Offer:** `id, hotmart_product_id, name, niche, language, commission_brl_cents, price_local, currency, allows_paid_traffic, sales_page_url, affiliate_link, score, status(candidate|approved|testing|validated|killed)`
- **Angle:** `id, offer_id, hypothesis, promise, audience_pain, hook_line, status`
- **Creative:** `id, angle_id, format(image|video), copy_primary, headline, asset_path, policy_lint(passed|failed), status`
- **Entity:** `id, kind(campaign|adset|ad), meta_id, parent_id, offer_id, angle_id, creative_id, geo, gate(0|1|2|3|T), daily_budget_cents, status(active|paused)`
- **MetricSnapshot:** `entity_id, ts, impressions, video_3s_views, link_clicks, spend_platform_cents, bridge_views, checkout_clicks` (append-only)
- **SaleEvent:** `id, source(webhook|csv), hotmart_tx_id (único), ts, commission_cents, status(approved|refunded|chargeback), tracking_param, matched_entity_id`
- **Decision:** `id, ts, entity_id, gate, verdict(pass|kill|insufficient_data|hold), metrics_json, rule_id, reason`
- **Approval:** `id, plan_hash, kind(launch|activate|scale|new_offer), summary, max_exposure_cents, status, decided_at`
- **Action:** `id, ts, actor(engine|human|agent:codex|agent:claude), kind, payload_json, approval_id, live(bool), result`

### 8.3 Rastreamento ponta a ponta
1. O anúncio aponta para `https://<dominio>/<slug>?ad={{ad.id}}&geo=CO`, usando os parâmetros dinâmicos do Meta.
2. A ponte dispara `PageView` (pixel) e `POST /event` no Worker (view).
3. O clique no CTA dispara `InitiateCheckout` (pixel) e `POST /event` (checkout_click), e então redireciona para o link de afiliado com o parâmetro de rastreio = `ad_id` (V-02).
4. As vendas entram via webhook → D1, ou via CSV → `arb sales import`.
5. `tracker.match()` casa a venda com a entidade pelo parâmetro. O que não casar fica em `unmatched` e aparece no relatório.

### 8.4 Biblioteca de ângulos
Cada ângulo encerrado gera um registro: nicho, promessa, dor, gancho, formato, geo, portão alcançado, métricas finais e o motivo da morte. O gerador de criativos consulta a biblioteca antes de propor novos ângulos: ele prioriza variações dos que passaram e evita padrões que morreram 2 ou mais vezes.

---

## 9. Protocolo multiagente

Codex e Claude Code trabalham **um de cada vez** no mesmo repositório. A estrutura já está pronta para paralelismo futuro, com um agente por módulo.

1. **Início de sessão:** ler `AGENTS.md`, `ops/HANDOFF.md` e `ops/LOCK`.
2. **Bastão:** se o LOCK estiver vazio ou tiver mais de 12 h, escreva `agente | tarefa | timestamp`. Se estiver ocupado e recente, pare e informe o humano.
3. **Tarefa:** mova o arquivo da tarefa de `board/todo` para `board/doing`. Execute **apenas** o escopo dela.
4. **Contratos:** módulos só importam `arb.models` e as interfaces públicas de outros módulos. Mudar um modelo exige um ADR em `decisions.md` e a regeneração de `contracts/`.
5. **Qualidade:** `ruff check`, `pytest` e `arb doctor` precisam passar antes de mover para `review`.
6. **Fim de sessão:** atualize o `HANDOFF.md` (o que foi feito, o que falta, riscos), faça commit com mensagem convencional e libere o LOCK.
7. **Proibido:** refatorar fora do escopo, alterar `config/rules.yaml` sem ADR, rodar em `LIVE_MODE=true`, ler ou imprimir o conteúdo de `.env`.

Formato do arquivo de tarefa:
```markdown
# T-XX: título
Fase: F_  |  Depende de: T-__
## Objetivo
## Arquivos
## Critérios de aceite
## Testes obrigatórios
```

---

## 10. Plano de implementação

As fases são sequenciais. Cada fase termina com software testável. **Nenhuma integração com dinheiro real antes da F6.**

### F0: Fundação
- **T-01** Estrutura do repo, `pyproject` (uv, ruff, pytest), `AGENTS.md` com as seções 0 e 9 deste documento, `CLAUDE.md`, `.env.example`, pre-commit com varredura de segredos.
- **T-02** Modelos pydantic (8.2) + geração de `contracts/*.json` via `arb contracts export`.
- **T-03** SQLite: migrações numeradas, repositórios e backup diário rotativo (7 cópias).
- **T-04** CLI `arb doctor`: valida config, banco, contratos e `LIVE_MODE`, e lista o que falta no `.env`.
- **Aceite:** `arb doctor` verde em ambiente limpo; testes de round-trip de todos os modelos.

### F1: Métricas, regras e simulador (o coração)
- **T-05** `metrics/`: funções puras da seção 4, com testes de valores conhecidos (incluindo divisão por zero → `None`, nunca exceção).
- **T-06** `rules/`: avaliador de portões lendo `rules.yaml`. Emite `Decision` com `rule_id` e `reason` legíveis. Respeita amostra mínima, teto e dados atrasados.
- **T-07** Freio de emergência, teto diário global e checkpoints da seção 5.4.
- **T-08** `sim/`: simulador que gera snapshots e vendas para N ofertas × ângulos × criativos, com taxas "verdadeiras" plantadas (alguns vencedores, maioria perdedora, ruído realista).
- **T-09** `arb sim run --seed X --budget 2400`: roda o laboratório inteiro em simulação e mede `waste_ratio`, `cost_per_learning`, vencedores achados e vencedores mortos por engano.
- **Aceite:** em 50 seeds, o motor encontra o vencedor plantado em ≥ 80% dos casos, com `waste_ratio` médio < 10%. Se falhar, ajuste `rules.yaml` com ADR e registre a calibração.

### F2: Analista
- **T-10** P&L diário por oferta, ângulo, criativo e geo; meta-métricas; caixa restante.
- **T-11** Relatório HTML de uma tela (`reports/latest.html` + cópia datada): topo com P&L e caixa, meio com mortos/promovidos/alertas, rodapé com **uma** pergunta de decisão.
- **T-12** Biblioteca de ângulos (8.4) com consulta por nicho.
- **Aceite:** relatório gerado a partir de uma simulação F1, legível no celular.

### F3: Scout (Portão 0)
- **T-13** Importadores de CSV: `offers.csv` e `adlibrary.csv` (formatos documentados no README).
- **T-14** Pontuação e filtros eliminatórios + `policy.yaml`. Gera aprovação `new_offer` com as top 3.
- **T-15** Prompt versionado em `src/arb/scout/collect_prompt.md` para coleta assistida via navegador.
- **Aceite:** CSV de exemplo → ranking + arquivo de aprovação pendente.

### F4: Ponte e rastreamento
- **T-16** Gerador de ponte (jinja2): página leve em espanhol, mobile-first, < 100 KB, conteúdo de valor real, CTA único, pixel + chamadas ao Worker, repasse do parâmetro de rastreio.
- **T-17** Worker TS: `POST /event`, `POST /sale` (webhook), `GET /health`, gravação em D1, validação de origem, rate limit simples.
- **T-18** `arb sales import <csv>` + `arb sync events` (puxa do D1) + `tracker.match()` com idempotência por `hotmart_tx_id`.
- **Aceite:** teste de ponta a ponta local (wrangler dev): visita → clique → venda falsa → casada com a entidade correta.

### F5: Meta somente leitura
- **T-19** Cliente Graph API (`meta/read.py`): insights por anúncio no nível dia, com paginação, retry exponencial e respeito a rate limit. Versão da API em `settings.yaml`.
- **T-20** `arb sync meta`: grava `MetricSnapshot` e reconcilia entidades criadas manualmente.
- **Aceite:** com token real e `LIVE_MODE=false`, lê a conta e popula snapshots sem nenhuma escrita.

### F6: Meta escrita com aprovação
- **T-21** `launcher.plan()`: gera a estrutura da seção 3 (campanha, conjuntos, anúncios), **criada pausada**, a partir de ofertas, ângulos e criativos aprovados. Serializa e gera o hash.
- **T-22** `launcher.execute(plan, approval_id)`: valida o hash, aplica idempotência, registra em `actions`. Ativação é um passo separado, com aprovação própria.
- **T-23** Ações automáticas permitidas sem aprovação: **somente pausar**.
- **Aceite:** em `LIVE_MODE=false`, gera dry-runs corretos. Em `LIVE_MODE=true`, cria 1 campanha de teste pausada e a pausa de novo, com o registro completo.

### F7: Fábrica de criativos
- **T-24** Gerador de ângulos: oferta + biblioteca → 3 hipóteses, cada uma com promessa, dor e gancho.
- **T-25** Gerador de copies em espanhol neutro e regional (CO/PE/MX), com lint de política (`policy.yaml`: termos banidos, promessas de resultado, números sem fonte).
- **T-26** Render de imagens (template HTML → PNG, 1080×1350 e 1080×1920) e vídeos curtos (ffmpeg: slides + texto + trilha livre de direitos), seguindo as zonas seguras.
- **Aceite:** 1 oferta → 3 ângulos × 3 criativos aprovados no lint, prontos para o launcher.

### F8: Operação contínua
- **T-27** `scheduler`: ciclos 09:00, 18:00 e 23:30 (cron ou Agendador de Tarefas), com sequência sync → rules → ações automáticas → relatório → alertas.
- **T-28** Alertas por Telegram (opcional): freio acionado, dados atrasados, aprovação pendente, vendas sem casamento.
- **T-29** Runbook em `README.md`: como iniciar, pausar tudo (`arb panic`), restaurar backup e trocar token.
- **Aceite:** 3 dias simulados em tempo acelerado, sem intervenção, com relatórios coerentes.

---

## 11. Modos de falha que os testes precisam cobrir

1. **Venda chega dias depois do gasto:** a entidade já está pausada. O P&L precisa reatribuir a receita retroativamente, e o veredito `kill` deve ser reavaliável (estado `reopened` se o ROI virar positivo).
2. **Reembolso de venda já contabilizada:** o status muda para `refunded`, a receita esperada é recalculada e o histórico de decisão é preservado.
3. **Meta retorna erro, rate limit ou token expirado no meio do ciclo:** nenhuma decisão de `pass` é tomada com dados parciais, o ciclo termina com alerta e a próxima execução retoma sem duplicar.
4. **Entidade editada manualmente no painel:** o `sync` detecta a divergência, atualiza o banco, registra `actor=human` e não reverte a mudança.
5. **CSV com formato alterado ou linha duplicada:** a importação valida o cabeçalho, recusa com erro claro e deduplica por `hotmart_tx_id`.

---

## 12. Itens a validar antes ou durante o desenvolvimento

| ID | Validação | Impacto se falhar |
|---|---|---|
| V-01 | O afiliado da Hotmart tem acesso a webhook/postback de vendas? | Usar só a importação de CSV (já prevista). |
| V-02 | Qual parâmetro de rastreio a Hotmart aceita no link de afiliado e exibe no relatório (ex.: `sck`/`src`)? Qual o tamanho máximo? | Se não aceitar o `ad_id` inteiro, usar um id curto mapeado no banco. |
| V-03 | Os produtores das ofertas escolhidas permitem tráfego pago e páginas-ponte? | Oferta eliminada no Portão 0. |
| V-04 | Alíquota real de impostos na fatura do Meta. | Ajustar `media_tax_rate`. |
| V-05 | Prazo de liberação da comissão e taxa de reembolso real por produto. | Ajustar `refund_rate` e as projeções de caixa. |
| V-06 | Versão atual da Graph API e permissões do app em modo de desenvolvimento. | Ajustar `settings.yaml`. |

---

## 13. Roadmap de fevereiro (não implementar agora)
- Alocador bayesiano (Thompson sampling) como módulo `rules/allocator.py`, desligado por flag até haver 60 dias de histórico.
- Frente RSOC: módulo `feeds/` para receita de feed providers, gerador de artigos multi-idioma e geos DACH, Nórdicos e Japão.
- Escala para MX, ES e hispânicos nos EUA via Portão T.
- Múltiplas contas de anúncio e orquestração paralela de agentes (um por módulo, com filas no lugar do LOCK).

---

## 14. Primeiro prompt para o Codex

```
Leia arb-engine-spec-v1.md inteiro. Crie o repositório conforme a
seção 8.1 e execute a Fase F0 (T-01 a T-04), seguindo o protocolo
da seção 9. Copie as seções 0 e 9 para o AGENTS.md. Popule
ops/board/todo com as tarefas T-05 a T-29, uma por arquivo, no
formato da seção 9. Ao final: todos os testes verdes, `arb doctor`
verde, HANDOFF.md atualizado e um resumo do que ficou para a F1.
Não implemente nada fora da F0.
```
