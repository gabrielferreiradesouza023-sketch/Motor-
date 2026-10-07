# Painel de prontidão

`arb readiness [--json] [--root <projeto>]` lê evidências locais e retorna exit 1 enquanto
houver pendência. Não lê .env/chave privada, não consulta API, não envia evento, não instala
serviço nem altera modo live. Neste batch, **graph_executor é sempre bloqueado**.

As evidências revisadas pelo humano ficam em:
- ops/validation/f5.json — saída do kit de leitura F5;
- ops/validation/f6_pause.json — saída do kit de pausa de uma entidade de teste;
- ops/validation/tracking.json — saída do kit de rastreio sintético.

Valida schema, tipo, todos os checks, SHA256 canônico, data com fuso e idade <=7 dias,
sem aceitar datas futuras; F5 também valida versão declarada e spend_cap dentro do teto.
Não fabrique provas. Hash não autentica quem executou: humano/Claude revisam origem e
resultados antes de registrar. Nenhuma prova real acompanha esta entrega cloud.

O registro versionado **próprio** ops/validation-status.json inicia todos os itens pending.
Após resolver cada V-01–V-06 e limites/host/instalação, o humano altera SOMENTE seu item:
`{"status":"confirmed","by":"human","checked_at":"<ISO com fuso>","evidence":"<referência revisável>"}`.
Preserve schema 1 e todos os nomes. Nunca colocar tokens, dados de cartão, chaves privadas
ou conteúdo de .env nesse arquivo público. Sem confirmação recente/referência, fica pendente.

Preflight é read-only e sem rede. Só meta_spend_cap pode usar prova F5 válida + confirmação
humana; credenciais por nome, limites e demais checks continuam exigidos no host. Presença
por nome não prova credencial válida. Backup/drill precisam estar íntegros e recentes (48h).
A chave pública já existe; não é necessário gerar outra chave por este batch.

Permissões, pacote verificado, host persistente e instalação são checks separados. Agentes
só renderizam/verificam templates; instalação e aceites reais pertencem ao humano no host.
Este painel não autoriza dinheiro: assinatura da intenção exata e demais gates continuam.
Não é um monitor da API em tempo real. Resolver T-55/V-06 requer contrato e PR separados,
respostas aprovadas e conformidade; nenhum arquivo/checkbox pode liberar Graph neste batch.
