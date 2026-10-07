# Aceite de rastreio no Worker do humano

O cloud só executa MockTransport e testes locais. Publicação do Worker e qualquer execução
real pertencem ao humano. A versão publicada precisa conter a extensão **própria** test:true
que preserva eventos de teste no export. Não altere schemas de vendas do provedor por suposição.

No host humano, com entidade e rastreio reais já registrados, resolva V-01/V-02/V-06, origem
permitida e credencial de sincronização. Nunca envie credenciais/chave privada ao agente.

1. Em modo false: `arb accept tracking-propose --url <base-https-worker> --origin <origem-da-ponte>
   --entity-id <id-local> [--tracking-id <alias-curto-existente>]`. A proposta contém um único
   evento de teste exato, sem token, com exposição monetária zero.
2. Revise URL, origem, entidade e test:true. Assine a proposta com `arb approve sign <proposta>`
   em TTY na própria máquina, usando sua chave existente. Não gere outra chave por este kit.
3. No host humano, com modo live deliberadamente configurado, defina TRACKER_SYNC_TOKEN e rode
   `arb accept tracking --url <mesma-base> --approval-id <id> --out <novo-tracking.json>`.
4. Revise: ACK do POST /event, GET /export autenticado, recibo marcado, CSV canônico interno
   casado em cópia descartável e fingerprint financeiro de produção inalterado.

O evento sintético não conta em métricas, inclusive na sincronização de produção posterior.
A venda com comissão sintética de 1 centavo só existe na cópia descartável, nunca no P&L real.
Ids completos ficam no ledger privado; prova exportável contém apenas sufixo e data/hash.
SHA256 é integridade, não assinatura de origem. Falha gera exit 1 e resultado uncertain:
verifique ledger e export autenticado no host; não reenviar automaticamente nem forçar gates.
O kit não cria venda real, não chama Hotmart, não instala serviço nem implementa exposição Meta.
