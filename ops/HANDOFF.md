# HANDOFF — BATCH-05

## Estado atual
- Branch `codex/batch-05`; PR [#36](https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/36) para main. Claude revisa; merge somente humano.
- Base usada: planejamento `89cf60a` da branch `claude/inspiring-davinci-o0loro`, escolhido quando #35 estava aberto. #35 já mergeado; main conferida `9ba15e8`. #34/BATCH-04 já revisado e mergeado.
- T-72 a T-76 concluídas para review. LOCK será liberado no commit T-76. PR só passa a ready após gates + worker verdes no head final.
- Motor **não pronto para dinheiro real**. `arb readiness`: não pronto, exit 1; 17 pendências, aceites ausentes recusados como “evidência não assinada”.

## Feito
- T-72: assinatura Ed25519 de evidências; kits continuam unsigned até revisão/assinatura humana. Primitivas de approval reutilizadas, hash preservado, campos integralmente assinados, TTY e chave existente.
- T-73: `arb validate record/show`; assinatura liga domínio e item. Edição/cópia/vencimento não confirma nada. Registro versionado continua pending, sem fatos inventados. validation no gate 95%.
- T-74: `arb service status`, diagnóstico WSL/PID1/timezone/unidades por leitura. Avisos no doctor/preflight e metadados no readiness; persistent_host ainda exige registro assinado.
- T-75: `arb service install-plan`; snapshot verificável, pacote/hash recusados se inválidos, caminhos escapados, WSL, instalação/timers/journal/rollback apenas impressos.
- T-76: [Guia do operador](../docs/runbooks/operador.md), 22 comandos validados com help, links/âncoras e ausência de segredos. Valores e aceites reais pertencem ao humano.

## Evidências
- 968 testes passed, 0 skips; total combinado 90.66%; todos os 23 grupos de dinheiro >=95%. Ruff, format, coverage gate, doctor, contratos e detect-secrets verdes.
- Drill 42 idêntico ao versionado; 6 invariantes e 7 cenários verdadeiros. Sem alteração da referência.
- T-72–T-75: CI gates + worker SUCCESS confirmado antes da tarefa seguinte. T-76/resultado final: [Checks do PR](https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/36/checks), observado antes de marcar ready/encerrar.
- T-73 teve preparação de runner presa; mesma job reexecutada e verde, sem mudar workflow/gates.
- Tabela de commits, cobertura por módulo, URLs do CI e readiness completo: [Evidência BATCH-05](../docs/validation/batch-05-evidence.md).
- config/rules.yaml, config/settings.yaml, ops/validation-status.json e arb.models intocados. Nenhuma migração nova.

## Bloqueios
Nenhuma tarefa de software bloqueada. Pendências operacionais continuam bloqueando dinheiro real:
- Humano + provedores: V-01–V-06 (webhook/CSV/rastreio/permissões do produtor/reembolsos/impostos/Graph). Impacto: dados e contrato reais ausentes; confirmações continuam pending.
- Humano: cartão, spend_cap, host sempre ligado, instalação manual do pacote em simulação e disponibilidade real. Diagnóstico/check não confirmam esses fatos.
- Humano no próprio host autorizado: aceites F5, uma pausa F6 e rastreio; precisam de credenciais/versionamento, entidade de teste existente e Worker publicado. Agente não cria/provisiona/deploya esses recursos.
- T-55: contrato e executor Graph de exposição ausentes. Resolver versão/permissões/idempotência com provedor e implementar em novo escopo revisado. Só FakeMeta permanece disponível.
- Claude: revisar #36. Humano: decidir merge; #35 já resolvido. Chave pública existente não precisa ser gerada/trocada.

## Riscos e decisões do humano
- Manter privada só na máquina assinadora; pública/configuração são raiz de confiança e mudanças passam por PR.
- Assinatura não comprova a verdade da resposta humana nem disponibilidade contínua de WSL. Avaliar host persistente e ACLs pessoalmente.
- Evidências/registros duram 7 dias; drill do backup <=48h. Preservar tentativas anteriores e reconciliar uncertain antes de repetir.
- Instalação só humana, sempre em simulação neste pacote. Aceites reais demandam autorização específica no terminal manual; não mudam serviço para live nem implementam executor.
- Próxima ação humana: revisão/merge #36 e execução do guia no host. Não declarar o motor apto a dinheiro real.

### BATCH-05 T-76 — review
3 testes novos: 22 comandos por --help, ausência de segredos/aumento de exposição e links/âncoras válidos. Guia, HANDOFF e relatório de evidências completos. Gates locais: 968 testes, 90.66% total; dinheiro >=95%, doctor OK, drill 42 idêntico. CI será verificado antes da próxima tarefa.
