# BATCH-06 — Preparação do piloto: confirmação estatística, dados observados e sinal

**Dono:** Codex  |  **Revisor:** Claude  |  **Aprovação final e merge:** humano
**Tarefas:** T-77 → T-83 (em `ops/board/todo/`)  |  **Base:** `main` com o BATCH-05 mergeado
**Tamanho:** médio. Tudo em simulação; nenhum gasto, conta ou API real.

## Por que este batch existe
Plano pré-piloto de 2026-10-08 (revisão Claude): o motor está maduro, mas sem dado de mercado.
Este batch prepara o motor para **aprender com o teste-fumaça humano** e para **não confundir
sorte com vencedor** antes do aporte de fevereiro.
1. Com `gate_3.min_sales: 2`, um combo com CAC real de R$ 60 (ROI −15%) faz 2 vendas antes de
   R$ 78 de gasto em ~37% das vezes (Poisson, média 1,31). → T-77 (Portão C), T-78 (medir).
2. O teste-fumaça é criado à mão pelo humano; o motor precisa registrá-lo, ler e transformar
   os números em perfil de simulação observado. → T-81, T-79.
3. `InitiateCheckout` depende só do pixel no navegador (bloqueadores, iOS). → T-80 (CAPI, desligada).
4. O Portão 0 ignora o que o produtor informa (permissão escrita, reembolso real). → T-82.
5. O operador precisa de um roteiro do piloto com os comandos novos. → T-83.

## Ordem
T-77 → T-78 → T-79 → T-80 → T-81 → T-82 → T-83.
T-78 depende de T-77. T-79 e T-81 são independentes entre si, mas mantenha a ordem.

## Regras de execução (iguais ao BATCH-04/05, mais as abaixo)
Valem integralmente `AGENTS.md` e a seção "Regras de execução" de `ops/batches/BATCH-04.md`:
uma branch `codex/batch-06`, PR draft para `main` logo após a T-77; LOCK por tarefa com commit +
push antes de começar; quadro `todo → doing → review` com "Evidência de conclusão"; gates por
tarefa (ruff check/format, pytest com cobertura de linhas+branches, check_coverage, doctor,
drill seed 42 idêntico ao versionado, `npm --prefix worker test` se tocar o Worker); CI do PR
verde antes da próxima tarefa; módulos novos que decidem dinheiro ou efeito externo no gate de 95%.

Adicionais deste batch:
1. **`config/rules.yaml` continua intocado.** Comportamento novo de regra entra como seção
   **opcional** do modelo `Rules` com padrão desligado (`None`); com o `rules.yaml` atual, toda
   saída (drill 42, golden, calibração atual) permanece byte-idêntica. Ligar é decisão humana
   via ADR aceito.
2. **ADRs deste batch nascem com status "Proposto — aguarda aceite humano".** Nunca marcar
   como aceito.
3. **Modelos:** mudar `arb.models` exige ADR e `contracts/` regenerado, como manda o AGENTS.md §9.4.
4. **Nada de valores de mercado inventados.** Perfis observados só saem de dados lidos do banco
   local; nos testes, de fixtures sintéticas marcadas como tal.
5. **CAPI:** desligada por padrão; sem token, sem deploy, sem chamada real. Versão da Graph API
   vem de configuração (V-06), nunca fixada no código.
6. **Bloqueio:** registrar em "Bloqueios" no `HANDOFF.md` e seguir, sem pedir confirmação.

## Definição de pronto
- `Rules.gate_C` opcional, avaliador com veredito de confirmação e métrica `p_roi_positive`,
  desligado com o `rules.yaml` atual; ADR proposto.
- `arb sim calibrate --confirm` (ou flag equivalente) mostra falsos positivos com e sem Portão C.
- `arb observed profile` gera um perfil em `reports/` a partir do banco local.
- Worker com CAPI opcional e `eventID` compartilhado entre pixel e CAPI.
- `arb smoke register|report` funcionais sobre FakeMeta.
- Portão 0 usa dados do produtor quando presentes; CSV antigo dá ranking idêntico.
- `docs/runbooks/piloto.md` com todos os comandos validados por teste.
- `arb readiness` continua **não pronto** no estado do repositório.
- `HANDOFF.md` atualizado, LOCK vazio, PR ready for review, sem merge.
