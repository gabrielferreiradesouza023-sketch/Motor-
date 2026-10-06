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
