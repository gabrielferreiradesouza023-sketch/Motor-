# Proposta de calibração — BATCH-02 T-33

Status: **Proposto; requer decisão humana. Nenhuma regra aplicada.**

Fonte: [calibration-grid.json](calibration-grid.json), seeds 0–99 por perfil e célula;
81 variantes × 2 perfis × 100 seeds. Distribuições de `config/sim_profiles.yaml` são
hipóteses independentes, não dados observados de mercado. `planted` serve só à regressão.
Reprodução: `uv run arb sim calibrate --workers 4` (duas execuções byte a byte idênticas).
HTML ordenável com Pareto: `reports/calibration.html`, regenerável pelo comando.

## Três opções

Acerto = vencedor real de cada seed chegou a G3 pass, não qualquer entidade.
Waste = média da fração de gasto excedente aos tetos, **não** todo gasto perdido.
Até validar = gasto total do laboratório até o primeiro G3 pass, **condicionado ao sucesso**;
seeds que nunca validam ficam fora dessa média. Total inclui as seeds sem validação.
Valores monetários abaixo em BRL; JSON original em centavos.

| Opção | Perfil/célula | Acerto | Waste | Até validar | Validações/100 | Gasto total médio |
|---|---|---:|---:|---:|---:|---:|
| Conservadora (atual) | cell-032-realistic | 26% | 2.837% | R$ 465.74 | 26 | R$ 516.54 |
| Conservadora (atual) | cell-032-pessimistic | 5% | 4.358% | R$ 452.40 | 5 | R$ 515.18 |
| Equilibrada | cell-040-realistic | 43% | 2.534% | R$ 434.42 | 46 | R$ 585.45 |
| Equilibrada | cell-040-pessimistic | 16% | 3.871% | R$ 426.85 | 17 | R$ 580.96 |
| Agressiva | cell-075-realistic | 51% | 2.182% | R$ 420.08 | 51 | R$ 649.58 |
| Agressiva | cell-075-pessimistic | 17% | 3.497% | R$ 425.73 | 18 | R$ 647.25 |

- Conservadora: mantém G3 3 vendas, teto 2× comissão líquida e kill CTR 0,008.
  Risco principal: falsos negativos (25%/51% das seeds matam o vencedor realista/pessimista).
- Equilibrada: G3 2 vendas e teto 3× comissão líquida; CTR e hard cap inalterados.
  Risco principal: maior gasto por combo; menos vendas mínimas exigem cautela estatística.
- Agressiva: G3 1 venda, teto 4× comissão líquida e kill CTR 0,010.
  Risco principal: uma venda pode ser acaso; aumento forte de exposição por combo e CTR
  mais rígido podem descartar oportunidades. Células 075 na fronteira Pareto realista.

**Recomendação: equilibrada para um próximo experimento controlado, somente após aprovação.**
Ela eleva o acerto de 26%→43% e 5%→16%, com gasto total médio cerca de 13% maior.
O pessimista ainda falha em 84% das seeds: nenhum cenário libera exposição real por si só.
A agressiva sobe o acerto realista a 51%, mas não melhora proporcionalmente o pessimista
nem justifica reduzir a confirmação a uma única venda. A conservadora continua vigente.

## Conta do Portão 3

Comissão típica do laboratório: R$ 60,00; reserva de reembolso 15% → R$ 51,00 esperados
por venda aprovada. Teto nominal atual 2× = R$ 102,00; teto rígido 1,5× = R$ 153,00.
No teto nominal, ROI mínimo 30% exige receita ≥ R$ 132,60, ou **3 vendas** de R$ 51,00.
Portanto 3 vendas no teto requerem CAC bruto médio ≤ R$ 34,00; não são três vendas
financiadas pela reciclagem da receita esperada. Comissão não limita a contagem de vendas:
a conta depende de CAC, além dos limites de ROI e CPC ≤ 0,7× EPC.

Na equilibrada, teto nominal R$ 153,00 e rígido R$ 229,50; no teto nominal o ROI exige
**4 vendas** (ceil(1,3×3)), mesmo com amostra mínima de 2. Duas vendas podem validar
antes do teto com gasto ≤ R$ 78,46 e CPC suficiente. Na agressiva, teto nominal R$ 204,00
exige **6 vendas** no limite (ceil(1,3×4)); uma venda só passa cedo, com gasto ≤ R$ 39,23.
Amostra mínima menor não remove nenhuma destas restrições financeiras.

## Limites da evidência e decisão

100 seeds por célula não estabelecem desempenho de mercado nem precisão estatística alta.
Winner found, qualquer validação e waste medem coisas diferentes. Há custo de seeds sem
sucesso; a média condicionada não é promessa de custo por vencedor.
O laboratório pausa G3 para revisão no **teto nominal**. Por isso as três variantes de
hard cap produzem resultados idênticos: não há evidência para recalibrar esse parâmetro;
mantemos 1,5. Receita esperada permanece não reciclável; ganhos sintéticos não são lucro.

Decisão pendente: humano escolher conservadora/equilibrada/agressiva ou rejeitar todas,
confirmar tolerância de risco e novo desenho de validação. Revisão do Claude e aprovação
humana precedem qualquer aplicação do diff no ADR-018. F5/F6 reais permanecem pendentes.
