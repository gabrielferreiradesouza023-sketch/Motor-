# CSV de vendas — V-01 pendente

O padrão de config/sales_csv.yaml é o esquema interno, sem presumir a exportação Hotmart.
No próprio host, inspecione uma exportação e declare os cinco nomes exatos em columns,
os valores exatos de status em statuses e, se necessário, date_format (strptime), timezone
(IANA), money_format: decimal e decimal_separator. Não colocar credenciais no YAML.

Null em date_format mantém o parser atual; timestamp sem fuso exige timezone declarado.
Datas ambíguas/inexistentes são recusadas. Valores decimais precisam de no máximo duas casas,
sem símbolo monetário, agrupamento ou expoente. Nada é arredondado. strict_headers: false
permite reordenação/colunas extras; campos requeridos e unicidade continuam obrigatórios.

`uv run arb sales import arquivo.csv --mapping config/sales_csv.yaml` analisa todas as linhas
antes de gravar; conflito reverte a importação. Valide uma cópia sintética primeiro, confira
status/comissão/rastreio e submeta o mapeamento real à revisão humana. Isto não fecha V-01.
Os exemplos de teste com txn/quando/valor/situacao/rastro são exclusivamente sintéticos.
