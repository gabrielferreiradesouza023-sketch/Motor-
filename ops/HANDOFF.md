# Handoff — F0 concluída, aguardando revisão

## Estado
- Escopo entregue: somente T-01 a T-04 da especificação v1.0.
- Checkout: /workspace/Motor-; pacote arb-engine, Python 3.12.14.
- T-01 a T-04 em board/review; T-05 a T-29 em board/todo, um arquivo por tarefa.
- LOCK liberado ao fim da sessão. Próximo agente deve seguir AGENTS.md.

## O que foi feito
- Estrutura da seção 8.1, seções 0 e 9 copiadas para AGENTS.md, CLAUDE.md,
  especificação integral em docs/, .env.example, uv.lock e pre-commit detect-secrets.
- Configurações iniciais dos portões, controles, política e settings; sem execução de regras.
- Nove modelos Pydantic e JSON Schemas exportáveis por arb contracts export.
- SQLite: migração 001 com checksum, FKs, venda única por hotmart_tx_id,
  repositórios tipados e snapshots/decisões/ações append-only no SQL.
- Backup consistente por API SQLite, um por dia UTC, retenção de sete dias,
  validação de integridade e teste de restauração separado.
- arb doctor: configurações, contratos, banco e modo seguro; banco ausente inicializado,
  banco existente verificado somente leitura; lista nomes de credenciais faltantes.
- CLI local: contracts export, db migrate, db backup, doctor.

## Evidências
- uv sync --frozen: sucesso (Python 3.12.14).
- uv run ruff check: verde.
- uv run pytest -q: 105 testes passaram, nenhum ignorado.
- uv run arb doctor: verde; avisos apenas de variáveis de integrações futuras ausentes.
- uv run arb db migrate e db backup: sucesso; repetição validada.
- uv run pre-commit run --all-files: varredura de segredos verde.
- Doctor em raiz temporária limpa: verde e repetível (teste automatizado).
- Testes negativos cobrem contratos/config/banco inválidos, migração atômica,
  FKs, rollback, venda duplicada, timestamps sem fuso e LIVE_MODE inseguro.
- Nenhuma credencial real exigida, nenhum arquivo .env lido, nenhuma API chamada,
  nenhuma escrita no Meta ou gasto de mídia.

## Configuração cloud
- install_script e start_skill salvos e confirmados no rascunho do ambiente.
- Revisar/salvar em configurações e publicar pelo produto para ativar o snapshot.
- Publicação e restauração em nova tarefa ainda não verificadas.
- Caches uv/pre-commit usam /workspace/.cache porque HOME é somente leitura.

## Próximo passo — F1 (não implementada)
1. T-05: métricas puras da seção 4; zero no denominador retorna None.
2. T-06: avaliador de portões, amostras mínimas, tetos e dados atrasados.
3. T-07: freio de emergência, teto diário e checkpoints de stop-loss.
4. T-08: simulador com verdade plantada e seeds reproduzíveis.
5. T-09: arb sim run e ensaio de 50 seeds: vencedor encontrado >=80%,
   waste_ratio médio <10%; eventual calibração de rules.yaml exige ADR.

## Riscos e limites
- F0 não oferece métricas, simulador, imports, relatórios, Worker ou integrações.
- Credenciais de integração são opcionais na F0; validar requisitos nas fases próprias.
- Graph API version permanece null até V-06/F5; não inventar versão.
- V-01 a V-06 aguardam validação humana/nas fases pertinentes.
- Modelo Action contém live bool conforme spec; nenhum executor real existe nesta fase.
- Backup é invocado por comando; agendamento contínuo fica para T-27/F8.
- Hook invoca uv run --frozen para funcionar também fora da venv; requer caches conforme README.
- Todas as interpretações iniciais estão em ops/decisions.md (ADR-001/002).
