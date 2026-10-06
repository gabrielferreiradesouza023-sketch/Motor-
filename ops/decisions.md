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
