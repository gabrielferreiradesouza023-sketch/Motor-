# Coleta assistida — v1.0 (T-15)

Objetivo: coletar evidências de ofertas em espanhol e anúncios comerciais observados
manualmente no navegador. Não lançar campanhas, comprar tráfego, publicar, solicitar
credenciais ou contornar acesso. A API pública da Ad Library não é premissa desta coleta.

Leia config/policy.yaml para a lista fechada de nichos. Priorize Excel/produtividade,
inglês para hispânicos, ofícios/beleza, gastronomia, pets, crochê e fotografia com celular.
Não coletar saúde, finanças, renda rápida, emprego, apostas ou outros nichos proibidos.

No marketplace da Hotmart, consulte informações disponíveis ao afiliado e confirme:
- Comissão nominal convertida para BRL com data/fonte da cotação, em centavos inteiros.
- Produtor permite tráfego pago e página-ponte: não presumir autorização.
- Página em espanhol nativo verificada por leitura humana, sem depoimentos inventados.
- Nota manual de qualidade 1–5 e popularidade 0–100; risco de política 0–1.
- Nome e identificadores originais, URL da página, link de afiliação fornecido oficialmente.
  Não inventar links. Sem link ou autorização confirmada, registrar pendência fora do CSV.

Na Meta Ad Library, registre por oferta e anunciante: identificador verificável,
primeira data de atividade observada, data da coleta e se permanece ativo.
Não inferir gasto, receita ou lucratividade de anúncios. Só marcar 30 dias se há evidência.
Não duplicar o mesmo anunciante na mesma oferta. Preserve URLs/fontes em notas de coleta,
sem adicionar colunas aos CSVs de importação.

Saída UTF-8, separador vírgula, aspas CSV em campos com vírgula e sem linhas de comentário.
Cabeçalhos obrigatórios, nessa ordem:

```csv
id,hotmart_product_id,name,niche,language,commission_brl_cents,price_local,currency,allows_paid_traffic,sales_page_url,affiliate_link,native_spanish,sales_page_quality,popularity,policy_risk
```

```csv
offer_id,advertiser_id,first_seen,observed_at,active
```

Booleanos somente true/false. Datas YYYY-MM-DD, first_seen <= observed_at. Moedas ISO
maiúsculas; price_local em centavos. language=es só após confirmação. IDs únicos e
estáveis, compatíveis entre arquivos. Compare exemplos em examples/scout/.
Se não souber um campo obrigatório, não fabricar valor: liste a pendência ao operador.

Entregue offers.csv, adlibrary.csv e notas de evidência separadas. Execute a validação local
e o ranking; o resultado é somente uma proposta pending para aprovação humana:

```bash
uv run arb scout rank --offers offers.csv --adlibrary adlibrary.csv
```

Top 3 não significa aprovação, compra de mídia ou garantia de resultado.
