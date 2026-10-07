# Contrato pendente do executor Meta real — T-55

Entrega documental. A porta `RemoteWriter` usa modelos internos, não payloads Graph.
`FakeMeta` é um provedor sintético sem rede. Não há executor Graph de create, activate ou
scale neste batch. A aprovação Ed25519 autoriza uma intenção; não fornece permissões de API.

| Operação | Informação necessária | Fonte | Estado |
| --- | --- | --- | --- |
| create | Uma campanha por oferta, orçamento ABO por conjunto, 1–3 ângulos e três criativos por ângulo; criação pausada | [Spec §3](../arb-engine-spec-v1.md), `arb.launcher.plan` | Definido no motor; mapeamento Graph bloqueado |
| create | Otimização InitiateCheckout, fallback LandingPageView após 72 h sem volume; público amplo | Spec §3 | Intenção de produto definida; disponibilidade e mapeamento por versão bloqueados |
| create / locate | Localizar criação depois de resposta perdida sem duplicar objetos | ADR-026/027, V-06 | Bloqueado: chave e lookup do FakeMeta são hipóteses, não garantias da Meta |
| activate | Aprovação própria vinculada a entidade, geo e orçamento; criação não ativa | ADR-022, `arb.launcher.actions` | Barreira interna definida; executor Graph bloqueado |
| set_budget | Aprovação scale, máximo +20% e intervalo mínimo de 24 h; snapshot pré-escrita | T-51, `arb.launcher.scale`, `arb.rules.scale_allowed` | Barreira interna definida; executor Graph bloqueado |
| pause | Intenção antes do efeito, PAUSED confirmado ou ledger incerto e reconciliação | T-36/T-42/T-43, `arb.meta.pause`, `arb.reconcile` | Escritor existente exercitado com MockTransport; aceite real bloqueado |
| read | Identidade, status observado e dados de conta/gasto necessários à reconciliação | `arb.meta.read`, V-06 | Leitor existente exercitado com mocks; versão, acesso e aceitação reais bloqueados |
| Todas | Versão Graph suportada e recursos efetivamente disponíveis nela | `config/settings.yaml`: meta_api_version null; V-06 | Bloqueado; nenhuma versão inferida |
| Todas | Conta autorizada, permissões por operação e vínculos dos recursos | V-06; documentação oficial da versão escolhida, a confirmar pelo humano | Bloqueado; nenhum nome de permissão inventado |
| Todas | Limites de taxa, classificação de erros e política segura de retomada | V-06; documentação oficial a confirmar pelo humano | Bloqueado; falhas do FakeMeta não são contrato do provedor |
| Todas | Conta BRL / America/Sao_Paulo, spend_cap positivo e cartão dentro de 240000 centavos | [Checklist F5/F6](f5-f6-checklist.md), `arb.preflight` | Critérios definidos; configuração e confirmação reais pendentes |

As fontes oficiais a consultar pelo humano são a documentação de
[Marketing APIs](https://developers.facebook.com/docs/marketing-apis/) e
[Graph API](https://developers.facebook.com/docs/graph-api/) da versão escolhida. Estes
links não comprovam campos, endpoints ou permissões específicos. Não há novos payloads,
endpoints ou permissões Graph declarados neste documento.

## Perguntas para destravar V-06

1. Qual versão Graph será validada e qual evidência confirma suporte no período de operação?
2. Qual conta e quais vínculos/permissões autorizam cada operação? Confirmar no host humano;
   não enviar IDs sensíveis, tokens ou credenciais a agentes.
3. Como localizar e distinguir uma criação cujo ACK foi perdido, inclusive após queda de
   processo? Qual evidência demonstra ausência de duplicação?
4. Quais limites de taxa e erros devem congelar execução? Como confirmar estado antes do retry?
5. InitiateCheckout, fallback LandingPageView, público amplo e ABO estão disponíveis na
   configuração escolhida? Qual decisão humana resolve eventual incompatibilidade?
6. Quais evidências confirmam moeda/fuso, limites do cartão e spend_cap independentes?

Responsável: humano, com revisão do Claude. Impacto: bloqueia implementação/aceite do
executor Graph e exposição real. Não bloqueia T-54, T-56 ou T-57, que usam apenas dados
sintéticos e arquivos locais. Merges #29/#30 já resolveram calibração e chave pública;
esses itens não são pendências deste contrato. F5/F6 reais e V-01 a V-06 seguem separados.
