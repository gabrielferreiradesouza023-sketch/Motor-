# Decisões arquiteturais

## ADR-001 — Fundação em simulação e configuração inicial (T-01)
- Usar o checkout existente Motor- como raiz do monorepo arb-engine; sem worktree novo.
- Registrar os valores iniciais da spec em rules.yaml, sem calibração; mudanças exigem ADR.
- Nenhuma integração externa na F0. Variáveis de integração faltantes são avisos, não erros.
- Não ler .env, nem automaticamente: usar variáveis exportadas; LIVE_MODE ausente equivale a false.
- Configuração local validada de forma estrita. Graph API permanece não definida até V-06/F5.
- Revisão de T-01 a T-03 aguarda T-04: o doctor completo depende delas. Não apresentar stub como aprovação.

## ADR-002 — Contratos iniciais (T-02)
- Nove modelos da seção 8.2, timestamps com fuso, extras proibidos e centavos inteiros não negativos.
- price_local também usa centavos na moeda local; conversão só na apresentação.
- Gate serializado como string (inclusive T). Status de ângulo/criativo segue o ciclo de oferta.
- Action.live mantém bool conforme a seção 8.2 para registros de auditoria; a F0 não
  executa ações externas e doctor recusa LIVE_MODE diferente de false.
- JSONs de métricas/payload são objetos. Contratos gerados de forma determinística.

## ADR-003 — Snapshots e validação sintética (T-08)
- Snapshots persistidos representam intervalos não sobrepostos; somar contadores é válido.
  F5 deverá converter insights cumulativos em deltas auditáveis, incluindo correções negativas
  em mecanismo próprio, sem gravar cumulativos como se fossem intervalos.
- Simulação tem três ofertas, três ângulos e três criativos por ângulo por padrão.
  Um combo é vencedor plantado; perdas incluem atenção, intenção e ausência de vendas.
- Tráfego usa Bernoulli por evento e CPM com ruído. Não lê regras para definir probabilidades.
- Aceite de 50 seeds mede este cenário sintético, não prevê lucratividade de campanhas reais.

## ADR-004 — P&L e receita tardia (T-10)
- P&L acumulado recalcula as vendas pelo status atual e preserva decisões append-only.
- Sem timestamp do clique no contrato SaleEvent, a atribuição diária retroativa é por
  coorte da primeira atividade conhecida da entidade, não pelo dia em que o CSV foi importado.
  É uma aproximação explícita; atribuição real por clique requer contrato/ADR futuro.
- Reopened é indicador no relatório para entidade morta cujo ROI se tornou positivo;
  não reativa anúncios automaticamente. Receita esperada não retorna ao caixa disponível.

## ADR-005 — Contrato da biblioteca de ângulos (T-12)
- Adicionar AngleLearning como contrato público e migração 002 para registros por ângulo/geo.
- Arquivar só ângulos pausados com kill ou pass do Portão 3/T. Hold não é veredito encerrado.
- Consulta por nicho mantém contexto, formato, métricas e motivo. Repetir archive atualiza a
  mesma chave e não duplica aprendizado. Decisões originais continuam append-only.

## ADR-006 — Contratos de coleta manual (T-13)
- OfferIntake contém Offer e avaliação manual; AdObservation contém anunciante e primeira
  observação. Exportar JSON Schema de ambos. Datas de coleta são explícitas, sem scraping.
- Importação CSV é estrita e atômica: cabeçalho exato, nenhuma coluna surpresa, duplicatas
  rejeitadas, inteiros monetários e booleanos true/false. Não armazenar credenciais nos CSVs.
- Um anunciante contado por oferta; idade é calculada na data observada, não inventada.

## ADR-007 — Normalização da pontuação (T-14)
- Pesos positivos da spec somam 85: normalizar para 100 e aplicar penalidade de até 15.
  Comissão líquida é saturada em R$100; prova de mercado em 5 anunciantes antigos.
  São escalas iniciais explícitas, ainda sem dados reais de marketplace.
- Os filtros usam comissão nominal mínima R$40 conforme texto do Portão 0.
- Aprovação new_offer tem exposição zero e hash de ofertas completas. Ranking não aprova
  ofertas, não cria campanha e não expande exposição. Preservar decisões existentes.

## ADR-008 — Ingestão de rastreio (T-18)
- BridgeEvent é contrato explícito; exportação D1 tem cursores persistidos por origem.
- Recibos deduplicam eventos antes de gerar snapshots de contadores de ponte.
  Colisão de timestamp no mesmo ad ganha microssegundos sem perder o timestamp no recibo.
- Comissão e rastreio não podem mudar silenciosamente numa transação existente.
  Reembolsos/chargebacks atualizam status, sem apagar decisões ou aceitar regressão para approved.
- /sale recebe contrato normalizado de teste; adaptador do webhook real aguarda V-01.

## ADR-009 — Insights cumulativos, correções e sincronização completa (T-20)
- MetricSnapshot ganha period_start opcional para atribuição à data da conta, mantendo ts
  como coleta. Adicionar MetricAdjustment com deltas assinados para correções negativas.
  Gerar contratos e migração 004. Logs de correção são append-only.
- Meta diário é cumulativo: gravar só diferenças em relação ao último estado confirmado.
  Repetir coleta não duplica gasto; correções não são descartadas nem sobrescrevem snapshots.
- Todos os GETs terminam antes da transação; falha de página ou validação causa rollback
  e um registro failed. last_collection só retorna tempo se o último ciclo ficou complete.
- Descoberta de anúncio desconhecido exige mapping explícito ad_id→offer_id; não inventar
  ofertas, comissão, creative ou atribuição. Mudanças manuais são auditadas e não revertidas.

## ADR-010 — Desenvolvimento local de F6–F8 antes do aceite real de F5
O usuário autorizou avançar em tudo que não exige cadastros ou gastos. Implementamos
as próximas fases apenas com dados sintéticos, arquivos e transportes de teste;
o aceite real de F5/F6 permanece pendente. Nenhuma chamada de escrita Meta ou envio
real de Telegram será executado. LaunchPlan passa a ser contrato público exportado:
contém entradas aprovadas, destino e estrutura ABO pausada. O hash cobre todas as
entradas; execução reconstitui o plano para detectar alterações de estrutura.
Orçamento diário total por oferta limitado a 6000 centavos, dividido entre conjuntos.

## ADR-011 — Copy local sem alegações inventadas
Gerador usa templates editoriais em espanhol, sem LLM/API paga. O lint normaliza
acentos, caixa e caracteres invisíveis; rejeita termos banidos, promessas e números
sem URL HTTPS explicitamente declarada. Declarar URL não verifica uma alegação:
a revisão humana precisa confirmar fonte, tradução e compatibilidade com a política.
Região indica contexto do leitor, sem afirmar disponibilidade regional da oferta.
Todos os criativos permanecem candidatos, sem publicação nem aprovação automática.

## ADR-012 — Render sem serviços pagos nem mídia de terceiros
Chromium headless renderiza HTML escapado, sem recursos externos, com DNS bloqueado
para rede e verificação real de overflow/zona segura pelo DOM. São produzidos PNGs
1080×1350 e 1080×1920; ffmpeg combina slides com H.264/AAC por 12 segundos.
A trilha é uma tríade sintetizada originalmente pelo projeto e dedicada a CC0-1.0,
sem fonograma de terceiros. Metadados de direitos acompanham cada vídeo.
Margens conservadoras: 120 px laterais, 200 superiores e 260 inferiores; revisar
visualmente no placement real, pois overlays das plataformas podem mudar.
Chromium usa no-sandbox por limitações do sandbox desta máquina isolada; somente templates
próprios escapados são renderizados. Não aceitar HTML arbitrário como entrada.

Playwright controla o Chromium instalado via protocolo de automação; o CLI headless
da imagem não concluiu. Não baixar browsers novos: executable_path usa binário local,
com caches XDG temporários graváveis e recursos de rede bloqueados por contexto.

## ADR-013 — Scheduler local com checkpoints e trava de processo
Migração 005 registra ciclos por instante UTC dos horários 09/18/23:30 São Paulo.
Lock flock por banco impede ciclos simultâneos; encerramento de processo libera a
trava automaticamente. Checkpoints permitem retomar relatório após falha sem repetir
coleta, decisões ou ações. Decisões têm IDs determinísticos por ciclo/entidade.
Fonte de sync é interface injetável, sem credenciais nem rede por padrão. Fonte ausente
ou falha congela entidades simuladas; pass não aumenta verba nem ativa nada. Entidades
Meta observadas recebem alerta de pausa pendente, sem falsificar estado remoto.
O scheduler agrega folhas da hierarquia e correções de métricas. Pausa ao atingir teto
mesmo com hold/pass, sem depender de kill. Falha de alerta não desfaz pausa. Usar Linux
neste cloud; Windows pode executar via WSL ou implementar trava nativa antes de operar.

## ADR-014 — Alertas opcionais, entrega incerta e ausência de credenciais
Alertas locais incluem freios, dados atrasados, propostas pendentes e vendas sem
casamento. A CLI não habilita Telegram. Adaptador só é usado com cliente, credenciais
e flag de envio explicitamente fornecidos; nesta sessão somente MockTransport.
Actions guardam conteúdo resumido e resultado, sem token/chat de destino ou respostas.
Tentativa é registrada antes do envio: timeout/falha vira uncertain e não é reenviada
automaticamente, pois Telegram não oferece chave idempotente para sendMessage.
Sem autorização/configuração real, dispatch é disabled, sem requisições externas.
Falta/falha de alerta não compromete a execução anterior dos freios.

## ADR-015 — Runbook exercitável sem exposição externa
Panic só confirma pausas locais; entidades Meta observadas ficam remote_pause_pending,
com código de saída 1. Restore usa backup SQLite consistente, valida contratos/checksums
e publica atomicamente em caminho novo; recusa sobrescrita mesmo em concorrência.
Restauração pode recuperar entidades ativas anteriores ao freio: exigir panic/revisão
antes de voltar a usar a cópia. Rotação de token foi testada apenas por substituição de
clientes read-only com tokens sintéticos; conta/provedor não foram alterados.

## ADR-016 — Teto rígido nos Portões 3 e T (T-30)
- Problema: a spec só mata G3/T "no teto com 0 vendas". Com 1–2 vendas a amostra nunca
  é suficiente e a entidade fica em `insufficient_data` gastando sem limite; com 3+ vendas
  e ROI ruim fica em `hold` indefinidamente. Só freios globais seguravam o gasto.
- Decisão (aprovada pelo humano): `gate_3.hard_cap_multiplier: 1.5`. Em G3/T, gasto bruto
  ≥ teto × 1,5 sem `pass` → `kill` com `rule_id` `g3.hard_cap`/`gT.hard_cap`, inclusive com
  dados atrasados (é kill por teto). `pass` nunca é sobrescrito.
- Faixa entre teto e teto rígido: mantém o comportamento anterior (até 50% extra para
  combos com venda acumularem as 3 vendas exigidas).
- Validação: 50 seeds inalteradas (50/50, 0 vencedores mortos, waste médio 0,93%).
- Limite conhecido: o simulador planta um vencedor com margens irreais (checkout→compra
  30%); calibrar com parâmetros realistas antes de operar. Multiplicador é calibrável via ADR.

## ADR-017 — Perfis diagnósticos uniformes (T-31)
Faixas são hipóteses fornecidas no card T-31, não dados coletados nem estimativas
estatísticas de mercado. Distribuições uniformes independentes por criativo, papéis
compartilhados por ângulo. Realistic usa CPM R$8–20 e taxas sugeridas; pessimistic
multiplica CPM por 1,25 e compra por 0,6. Vencedor/borderline são papéis relativos,
sem garantia de lucro ou de passar portões. Seed sorteia posições, nenhuma calibração
foi aplicada a rules.yaml. Planted conserva RNG/valores/algoritmo histórico, inclusive
posição fixa para regressão; somente perfis diagnósticos sorteiam posições.


## ADR-018 — Calibração G3 equilibrada
Status: **Aceito** pelo humano em 2026-10-06 (opção equilibrada); aplicado em rules.yaml (T-40/Claude).

Fonte: docs/validation/calibration-proposal.md e células 040 dos dois perfis no grid.
Recomendação: aumentar teto nominal a 3× comissão líquida e exigir 2 vendas mínimas,
sem alterar ROI, EPC, CTR, teto rígido, tetos diários/cartão/conta/projeto.
Tradeoff: maior acerto sintético e gasto total cerca de 13% maior; amostra menor e resultados
pessimistas fracos não autorizam operação real. Alternativas e limitações no documento.

Diff exato proposto para config/rules.yaml (apenas estes dois valores):
```diff
 gate_3:
-  commission_cap_multiplier: 2
-  min_sales: 3
+  commission_cap_multiplier: 3
+  min_sales: 2
   min_roi: 0.30
   epc_factor: 0.7
   hard_cap_multiplier: 1.5
```

Até decisão humana permanecem as regras atuais. Não implementar este diff neste batch.

Aplicação (Claude): verificação pós-aplicação reproduz o grid — realistic 43/100 achados,
waste 2,53%; pessimistic 16/100, waste 3,87%; planted 50/50, waste 0,77%. Testes de lógica
de G3 e o histórico `planted` passam a fixar as regras anteriores (`pinned_rules` em
tests/conftest.py) para manter limites exatos; teste novo verifica os valores vigentes.


## ADR-019 — Aprovação HMAC verificável
Status: **Substituído pelo ADR-022** (HMAC simétrico: quem verifica também assina).

Approval.signature opcional no contrato para propostas pending e registros legados, mas
obrigatória no consumo de approved. HMAC-SHA256 do JSON UTF-8 canônico (sort_keys,
separadores compactos, todos os campos incluindo id/status/data exceto signature).
Verificação em tempo constante; launch e activate recusam alteração de qualquer campo,
assinatura/chave ausente ou chave errada. Atualização pending→approved inclui assinatura.
`arb approve sign` requer tty e confirmação de kind/exposição/hash/resumo; não sobrescreve.
Não aceita pipelines/automação. `arb approve verify` não gera assinatura.

APPROVAL_SIGNING_KEY existe exclusivamente no ambiente do humano/runtime sob seu controle;
nunca deve ser disponibilizada a agentes ou neste cloud. Doctor só verifica presença por
nome, com aviso em simulação. O humano deve executar assinatura/verificação em seu host:
sem chave no cloud, launch/activate falham fechados até no dry-run. Testes sobrescrevem
ambiente com fixture sintética. HMAC depende da proteção dessa chave: não substitui
isolamento de host, limites do cartão/conta, ou revisão independente. Aprovações antigas
sem assinatura precisam de nova decisão humana. Nenhuma chave real criada ou lida aqui.


## ADR-020 — Guarda central e notificações autenticadas
Status: Aceito para implementação; nenhum efeito real neste batch.

arb.safety é a única leitura de LIVE_MODE para controles de execução. Simulação local
recusa live; escrita externa recusa false/valor inválido e tipos fora da allowlist. Pause
é a única exceção autônoma. Demais tipos exigem approved_file assinado, intenção exata,
exposição e data. Guarda registra intenção sanitizada no logger; adaptadores persistem
Actions antes do HTTP. Executor/ativador permanecem exclusivamente locais.

Approval.kind ganha notification para não reaproveitar aprovação financeira em mensagens.
A assinatura liga mensagem normalizada ao bot_id/chat_id (não ao token secreto); mudança
de destinatário/conteúdo invalida autorização. Dispatch e Telegram direto passam pela
guarda. Envio desabilitado continua idêntico; send=True agora exige modo/autorização
explícitos. Testes antigos de opt-in usam apenas modo mockado e chaves/HTTP sintéticos.
Idempotência e resultado uncertain sem retry continuam preservados. Sem mensagem real.

Teste AST conserva allowlist por módulo/método: Telegram.__call__ e futuro PauseWriter.pause;
recusa verbos de escrita, request dinâmico/desconhecido e aliases importados fora dela.
É uma barreira estática conservadora, complementar à guarda e à revisão humana.


## ADR-021 — Escritor Meta exclusivamente de pausa
Status: Aceito para implementação/testes MockTransport; não validado em conta real.

PauseWriter aceita somente id Graph numérico e payload exato status=PAUSED. Não oferece
create/activate/budget/delete. Guarda central antes do POST, Bearer no header, redirects
bloqueados, timeout e erros sanitizados (190/HTTP/transporte). Em false não constrói cliente
real nem lê credenciais via factory. Cliente é lazy e fechado quando pertencente ao writer.
Idempotência por estado já pausado/cache de ACK; falha nunca entra no cache.

Panic conserva remote_pause_pending em simulação. No runtime humano autorizado, pausa
locais e remotos: grava Action intent antes do HTTP e resultado append-only após ACK.
Estado remoto local só muda após success=true; falha produz uncertain e requer leitura de
reconciliação. Não há retry automático, ativação ou aumento real. Backup antigo pode
ressuscitar estado ativo: ler/reconciliar antes de operação. Aprovação para gastar continua
independente e não implementa executor de exposição real. Todos os testes deste batch
injetam MockTransport e mockam a função de modo; nenhum LIVE_MODE=true operacional,
credencial real ou chamada Meta real usada.


## ADR-022 — Aprovação humana com Ed25519 (T-40)
Status: **Aceito** pelo humano em 2026-10-06; substitui o mecanismo do ADR-019.

Problema: HMAC é simétrico. No live a chave precisaria estar no host do motor, e quem pode
verificar pode assinar — um agente com acesso a esse ambiente forjaria aprovações de gasto.
Decisão: assinatura Ed25519 sobre o mesmo JSON canônico (todos os campos exceto
`signature`, agora 128 hex). Chave **privada** só na máquina humana, em arquivo fora do
repositório com permissão 0600, apontado por `APPROVAL_PRIVATE_KEY_FILE`. Chave **pública**
versionada em `config/settings.yaml` (`approval_public_key`); motor, preflight e agentes só a
leem — verificar nunca permite assinar.
- `arb approve keygen --output <arquivo>`: exige tty, recusa caminho dentro do repo, nunca
  sobrescreve, grava 0600 e imprime a chave pública para o humano colar via PR.
- `sign` recusa chave privada ausente, com permissão aberta, inválida ou que não
  corresponda à pública versionada. `verify` falha fechado sem chave pública válida.
- Alterar `approval_public_key` equivale a trocar quem aprova gasto: só por PR revisado e
  mergeado pelo humano. Agentes nunca geram, leem ou recebem a chave privada.
- Doctor avisa e preflight dá erro enquanto `approval_public_key` for null.
- Sem aprovações reais existentes: nenhuma migração de assinaturas HMAC necessária.

## ADR-023 — Retomada e hook de notificação incerto (T-45)
A matriz plantou queda após entrega do hook notify e antes/depois do checkpoint final:
a retomada entregava duas vezes (3 casos falhavam). Registrar tentativa durável antes do
hook, sem retry se já existir, preserva ADR-014; queda antes da entrega pode perder alerta,
portanto o relatório local continua obrigatório. Hook é extensão local injetável, não
configura Telegram nem dispensa sua aprovação. BaseException também marca ciclo failed,
rollback e liberação do flock; tentativa/resultado permanecem append-only.

## ADR-024 — Restore em quarentena (T-46)
Migração 006 adiciona marcador com origem, SHA-256 e data do restore. Scheduler e
exposição recusam enquanto aberto; pause/panic permanecem disponíveis. Release exige
tty + confirmação, ledger vazio, locais pausados e leitura PAUSED de todos os remotos.
A exigência de pausa é conservadora: ACTIVE ou desconhecido não autoriza liberar restore.
Verificações são revalidadas sob BEGIN IMMEDIATE antes da Action de liberação; não há --yes.

## ADR-025 — Approval creative_set (T-50)
Novo kind creative_set, com envelope de ângulos e criativos ligado por hash à assinatura
Ed25519. Proposta exclui lint reprovado e reexecuta o lint; consumo confere conteúdo atual,
assinado e kind, e aplica status approved atomicamente com Action. Exposição máxima zero:
esta aprovação não substitui launch, activate ou scale. Contrato approval.json regenerado.

## ADR-026 — Porta remota e FakeMeta (T-52)
RemoteWriter opera sobre Entity e chaves de intenção do motor, nunca payloads Graph.
FakeMeta cria pausado e oferece activate/budget/pause/read/locate, sem delete ou rede.
Chaves e lookup determinísticos são uma hipótese do fake: a forma de localizar/deduplicar
criação na Meta real é DESCONHECIDA, bloqueada até V-06/T-55. Não transferir essa garantia
para o provedor. Timeout antes/depois, server_error, rate_limit e resposta inválida são
falhas sintéticas; nenhuma versão, endpoint, campo ou permissão Graph é implementada aqui.

## ADR-027 — Journal de exposição exclusivamente sintético (T-53)
Launch, activate, scale e pause sobre FakeMeta registram intenção durável antes da chamada,
validam aprovação Ed25519 quando aumentam exposição e só alteram estado local após prova
compatível. Resposta perdida mantém ledger aberto; leitura resolve aplicado ou não aplicado
antes de retry. Criação usa chave por plano/item; aggregate launch só fecha após todos os
itens. Scheduler admite FakeMeta em LIVE_MODE=false, sem habilitar executor Graph. Sem
writer, o caminho simulado existente permanece. Nenhuma garantia de dedupe é atribuída à
Meta real: segue o bloqueio documental da ADR-026.

## ADR-028 — Ensaio isolado e determinístico (T-54)
Drill usa exclusivamente diretório temporário, configuração pública copiada, chave sintética
conhecida do conftest e FakeMeta. O ponteiro da chave é substituído apenas no escopo isolado
por arquivo temporário 0600 e restaurado sem ler a chave original. Um pseudo-terminal local
exercita as guardas tty com callbacks sintéticos; não remove guardas de aprovação/release.
Banco/configuração reais não são alterados. JSON normaliza UUIDs, caminhos e timestamps de
restore; preserva contagens, dinheiro, cenários e invariantes verificados. Dedupe do fake
não comprova dedupe Graph. O ensaio não aceita LIVE_MODE=true nem writer externo.
