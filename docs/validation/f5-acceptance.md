# Kit F5 — execução exclusivamente no host humano

O cloud dos agentes valida apenas MockTransport. Este kit não aprova gasto nem disponibiliza
executor Graph. Versão/permissões reais V-06 seguem pendentes; não escolher versão por exemplo.

Preparar host isolado e permissões 0600/0700, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID e
META_API_VERSION escolhida pelo humano. LIVE_MODE=true é exclusivamente para esta execução
humana autorizada; nunca no cloud. No host humano, executar:

```
uv run arb accept f5 --out data/acceptance/f5.json
```

Faz somente GET usando Reader existente: conta BRL/São Paulo, insights de dois dias de
calendário São Paulo, ads e spend_cap positivo <= total_cap_cents. Todos os checks precisam
passar; exit 1 se falhar. Nenhuma escrita Meta, ativação ou mensagem. Saída redigida com
versão, sufixo de conta, data e SHA-256; não sobrescreve evidência existente. Para novo ensaio,
usar outro caminho e preservar a evidência anterior para revisão.

Não enviar tokens/ids completos ou a chave privada ao chat. Compartilhar somente a evidência
redigida com o revisor, que confirma fonte/conta/permissões e validade. Hash não é assinatura
nem prova de origem por si só. Mocks não fecham F5 real. Conferir spend_cap no painel e cartão
no emissor; nenhuma variável/GET comprova o limite físico restante. Dinheiro real bloqueado.
