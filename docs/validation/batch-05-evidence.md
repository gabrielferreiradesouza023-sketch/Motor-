# Evidências BATCH-05

Base usada: `origin/claude/inspiring-davinci-o0loro`, `89cf60a59ae2eb6be5fa672b1c24ac9f5d67253f`.
PR [#36](https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/36). Planejamento #35 mergeado; main conferida: `9ba15e88b079d07ab9a69cb0fc238c310ad62c68`.

## Tarefas

| Tarefa | Status | Commit | Novos testes | Evidência |
| --- | --- | --- | ---: | --- |
| T-72 | review | `69c1f5acdc885f7187df92b5af2cb53313ac5204` | 14 | Origem Ed25519; sem assinatura/tamper/chave divergente/TTY/privada ausente recusados |
| T-73 | review | `8783ab7ff9cbf1eb8c88af4249d5530bbf51a601` | 28 | Registro vinculado ao item; cópia entre itens, edição manual e vencimento recusados |
| T-74 | review | `cf0c38e56a0b57341065a0545a0b1d32c920dc83` | 16 | Linux/WSL/PID1/timezone/unidades; somente systemctl show; persistência não inferida |
| T-75 | review | `06400cda2398be13f1b1c56ad1c73fd5441f1658` | 9 | Snapshot independente, integridade do pacote, concorrência e nenhum subprocesso no plano |
| T-76 | review | commit T-76 que contém este relatório | 3 | 22 comandos por --help; nenhum aumento de exposição, nenhum segredo e links/âncoras válidos |

## Gates finais locais

- 968 passed; 0 skips. Cobertura total combinada: 90.66%.
- Ruff check/format, pytest com branches, check_coverage, doctor, contratos e detect-secrets verdes.
- Drill 42: byte a byte igual ao JSON versionado; 6 invariantes e 7 cenários verdadeiros. Somente síntese/FakeMeta.
- Worker intocado; gates e worker no CI de cada commit antes da próxima tarefa. CI da T-76: consultar [Checks do PR](https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/36/checks); PR só será ready após sucesso do head final.

| Módulo | Linhas + branches | Mínimo |
| --- | ---: | ---: |
| arb.rules | 100.00% | 95% |
| arb.metrics | 100.00% | 95% |
| arb.launcher | 97.94% | 95% |
| arb.safety | 100.00% | 95% |
| arb.meta.pause | 100.00% | 95% |
| arb.ledger | 100.00% | 95% |
| arb.reconcile | 100.00% | 95% |
| arb.quarantine | 100.00% | 95% |
| arb.db.checkpoint | 97.70% | 95% |
| arb.scout.approve | 100.00% | 95% |
| arb.creative.approve | 100.00% | 95% |
| arb.launcher.scale | 96.95% | 95% |
| arb.remote | 99.43% | 95% |
| arb.remote.journal | 100.00% | 95% |
| arb.remote.launch | 95.83% | 95% |
| arb.drill | 100.00% | 95% |
| arb.tracker.ids | 100.00% | 95% |
| arb.permissions | 100.00% | 95% |
| arb.accept | 96.99% | 95% |
| arb.accept_pause | 100.00% | 95% |
| arb.accept_tracking | 100.00% | 95% |
| arb.readiness | 100.00% | 95% |
| arb.validation | 97.47% | 95% |

## CI observado antes de iniciar a próxima tarefa

| Tarefa | Head verificado | Gates | Worker |
| --- | --- | --- | --- |
| T-72 | `69c1f5acdc885f7187df92b5af2cb53313ac5204` | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37711967199/job/113099694190) | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37711967199/job/113099694178) |
| T-73 | `8783ab7ff9cbf1eb8c88af4249d5530bbf51a601` | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37712720424/job/113105234421) | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37712720424/job/113105236524) |
| T-74 | `cf0c38e56a0b57341065a0545a0b1d32c920dc83` | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37714639455/job/113108218262) | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37714639455/job/113108218054) |
| T-75 | `06400cda2398be13f1b1c56ad1c73fd5441f1658` | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37715688702/job/113111886085) | [SUCCESS](https://github.com/gabrielferreiradesouza023-sketch/Motor-/actions/runs/37715688702/job/113111885815) |

T-73: uma tentativa permaneceu na instalação de ferramentas de render, sem chegar aos testes. Cancelada após cerca de dez minutos; reexecução do mesmo job passou. Workflow e gates inalterados.

## Readiness observado neste checkout

Status: **não pronto**, exit 1. Chave pública e permissões verificadas; 17 pendências.

```text
não pronto
✘ preflight: Preflight pendente: credentials, graph_version, meta_spend_cap, card_limit, backup_drill, scheduler_lock
✘ drill_recent: Drill de backup ausente/falho ou mais antigo que 48h
✔ permissions: verificado
✔ approval_public_key: verificado
✘ f5: evidência não assinada
✘ f6_pause: evidência não assinada
✘ tracking: evidência não assinada
✘ V-01: Validação do provedor ainda não registrada pelo humano
✘ V-02: Validação do provedor ainda não registrada pelo humano
✘ V-03: Validação do provedor ainda não registrada pelo humano
✘ V-04: Validação do provedor ainda não registrada pelo humano
✘ V-05: Validação do provedor ainda não registrada pelo humano
✘ V-06: Validação do provedor ainda não registrada pelo humano
✘ graph_executor: T-55: executor de exposição Graph ausente; somente FakeMeta
✘ card_limit: Limite do cartão não confirmado ou preflight/teto pendente
✘ spend_cap: spend_cap real não confirmado dentro do teto
✘ persistent_host: Host persistente ainda não confirmado
✘ service_package: Pacote de serviço ausente/inválido; nenhuma instalação executada
✘ service_installed: Instalação/disponibilidade do serviço ainda não confirmada pelo humano
```

Configuração/regras/registro pending permanecem iguais à base. Não houve API real de produto, conta, credencial/chave privada real, deploy, instalação, mensagem, gasto ou merge pelo agente. Apenas systemctl show de leitura, testes sintéticos e publicação do PR.

## Riscos e pendências humanas

- Claude revisar #36; humano decidir merge. #35 já mergeado, sem pendência histórica.
- Executar [guia do operador](../runbooks/operador.md) no próprio host; assinaturas com a chave existente só na máquina humana.
- Resolver V-01–V-06 com provedores, cartão/spend_cap, host persistente e instalação manual em simulação.
- Executar/revisar kits F5/F6/rastreio reais autorizados; Worker publicado e entidade de teste existente são pré-requisitos, não fornecidos neste batch.
- T-55: contrato/implementação/revisão do executor Graph continuam separados; só FakeMeta nesta entrega.
- Provas e registros vencem em 7 dias; drill de backup em 48h. Assinatura comprova origem, não a veracidade de uma confirmação humana.
- WSL pode suspender; diagnóstico ou systemd habilitado não comprovam disponibilidade contínua.
- Dinheiro real permanece bloqueado.
