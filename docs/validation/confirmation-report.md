# Confirmação estatística — hipóteses, não mercado

Seeds: 100. Valores monetários em centavos. C desligado nas regras atuais.

| Perfil | Variante | FP / perdedores | Taxa FP | Acertos / vencedores | Acerto | Gasto médio | Gasto por vencedor |
|---|---|---:|---:|---:|---:|---:|---:|
| planted | current | 0 / 800 | 0.00% | 100 / 100 | 100.00% | 65801.40 | 65801.40 |
| planted | C-10000 | 0 / 800 | 0.00% | 100 / 100 | 100.00% | 66391.74 | 66391.74 |
| planted | C-15000 | 0 / 800 | 0.00% | 100 / 100 | 100.00% | 66391.74 | 66391.74 |
| planted | C-20000 | 0 / 800 | 0.00% | 100 / 100 | 100.00% | 66391.74 | 66391.74 |
| realistic | current | 31 / 871 | 3.56% | 17 / 29 | 58.62% | 58544.87 | 344381.59 |
| realistic | C-10000 | 18 / 871 | 2.07% | 15 / 29 | 51.72% | 61535.02 | 410233.47 |
| realistic | C-15000 | 18 / 871 | 2.07% | 16 / 29 | 55.17% | 62389.63 | 389935.19 |
| realistic | C-20000 | 19 / 871 | 2.18% | 16 / 29 | 55.17% | 63229.34 | 395183.38 |
| pessimistic | current | 17 / 900 | 1.89% | 0 / 0 | — | 58096.26 | — |
| pessimistic | C-10000 | 3 / 900 | 0.33% | 0 / 0 | — | 59864.31 | — |
| pessimistic | C-15000 | 4 / 900 | 0.44% | 0 / 0 | — | 60556.07 | — |
| pessimistic | C-20000 | 5 / 900 | 0.56% | 0 / 0 | — | 61159.54 | — |

- Perfis são hipóteses, não dados de mercado. Não escolher configuração automaticamente.
- Taxa FP = perdedores validados / perdedores verdadeiros; acerto = vencedores validados / vencedores verdadeiros.
- Custo por vencedor inclui todo gasto e divide somente pelos vencedores verdadeiros validados; sem acerto é null.
- Taxas do perfil são amostradas uma vez; C usa novos lotes no mesmo geo e métricas acumuladas.
- Avaliações repetidas, seleção nos portões anteriores e 100 seeds não garantem taxa fora da amostra.
- Sem C, saídas históricas de summary/calibrate permanecem inalteradas.
