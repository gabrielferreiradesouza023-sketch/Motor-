# Handoff — BATCH-02, T-31–T-39 para revisão

## Estado e bastão
- Base: main sincronizada, commit a0b01be (F0–F8/T-30 e CI anteriores já mergeados).
- Entrega: uma branch codex/batch-02, PR #28 para main:
  https://github.com/gabrielferreiradesouza023-sketch/Motor-/pull/28
- PR criado draft após T-31. Tornar ready somente após CI final verde; Claude revisa
  antes de qualquer merge pelo humano. Codex não faz merge/push direto em main.
- T-31–T-39: implementação/documentação em review; revisão humana/Claude não presumida.
  LOCK publicado antes de cada tarefa e liberado ao mover doing→review.
- CI de cada predecessor verde antes da tarefa seguinte. Evidências:
  docs/validation/batch02-ci.json e checks públicos do HEAD do PR.
- Regras operacionais config/rules.yaml preservadas byte a byte em relação à main.
- Nenhuma API Meta/Telegram/Cloudflare real, conta, credencial real, deploy, mensagem,
  gasto ou execução operacional LIVE_MODE=true neste batch. Não ler .env.
- Histórico anterior preservado em docs/handoffs/pre-batch02.md; aquele documento
  descreve a sessão antiga e não o estado atual das branches/merges.

## Feito
- T-31: perfis planted (regressão histórica), realistic e pessimistic; distribuição por
  papel, vencedor/borderline em posições por seed, mortes/custos e diagnóstico 200 seeds
  por perfil. ADR-017 e docs/validation/sim-profiles.json. Planted preserva 50/50 e 0,9305%.
- T-32: grid 81 variantes × 2 perfis × 100 seeds, validação em memória, sem editar regras;
  duas execuções byte a byte idênticas, cada uma observada abaixo de 10 minutos nesta
  sessão (aproximadamente 4 minutos, quatro workers; não é promessa para qualquer host).
  JSON rastreável e HTML regenerável/ordenável/Pareto: arb sim calibrate --workers 4.
- T-33: até três opções com acerto/waste/custo/risco, matemática de G3 e ADR-018 Proposto
  com diff exato. Equilibrada recomendada para novo experimento após decisão, não aplicada.
- T-34: Approval.signature, HMAC canônico de todos os campos, consumo fail-closed,
  comparação constante, CLI approve sign/verify, tty/confirmar, doctor só presença.
  ADR-019 e contratos regenerados. Aprovações antigas sem assinatura recusadas.
- T-35: guarda central de escrita, pausa como única exceção autônoma, demais efeitos
  assinados; notificações ligadas a conteúdo/destinatário. AST recusa verbos de escrita,
  aliases e request dinâmico fora da allowlist. ADR-020; default sem envio preservado.
- T-36: escritor Meta exclusivamente status=PAUSED, transporte lazy/nenhum real em false,
  erros sanitizados, idempotência, panic misto auditado (intent antes do HTTP, resultado
  append-only). Em simulação mantém remote_pause_pending. Somente MockTransport; ADR-021.
- T-37: propriedades determinísticas (~1400 exemplos) em 2,42s; amostra, stale, tetos,
  monotonicidade, dinheiro, controles e escala. Encontrou e corrigiu TypeError de EPC None
  em G3/T com vendas/cliques mas zero bridge_views; ausência não permite pass, hard cap vale.
- T-38: CI exige linhas+branches combinados >=95% nos cinco grupos de dinheiro e >=80%
  no pacote. Medição final de T-38: 100% dinheiro / 87,57% pacote; 400 testes, sem skips,
  render incluído. Sem exclusões/pragma no cover. docs/validation/coverage.json atualizado
  pelos gates finais. Teste negativo confirma falha abaixo do limite e por módulo ausente.
- T-39: arb preflight [--json], checklist português, nomes sem ler chave HMAC, cap Meta via
  GET opt-in --read-meta, cartão, restore descartável do dia UTC, flock disponível, alerta
  opcional e panic disponível. Matriz sintética/MockTransport com 37 testes focados verdes.
  Offline real desta sessão retorna erro esperado por falta de preparação, sem rede:
  docs/validation/preflight-offline.json. docs/validation/f5-f6-checklist.md.

## Evidências e limites dos gates
- Gates locais por tarefa: Ruff check/format, pytest e arb doctor. T-38/T-39 adicionam
  cobertura de branch ao pytest e o verificador scripts/check_coverage.py, igual à CI.
- CI gates inclui render sem skips, doctor, drift de contratos e scanner de segredos.
  Worker (typecheck + dois testes Node) verde em todos os predecessores; nenhum arquivo
  do Worker alterado. Entrega final para revisão depende de ambos os jobs verdes no HEAD.
- Doctor é verde com avisos de nomes ausentes; não transforma ausência de integração real
  em aceite. Preflight offline falha fechado e não significa falha da implementação.

## Bloqueios e decisões pendentes do humano
1. ADR-018: escolher/rejeitar a calibração e tolerância de risco. Proposta documental T-33
   concluída, aplicação bloqueada; manter regras atuais até decisão. Nenhum diff aplicado.
2. Claude revisar PR #28, humano realizar merge. Só então mudanças chegam à main.
3. Aceites reais F5/F6 e V-01/V-02 Hotmart/rastreio/V-06 Graph permanecem pendentes.
   Provedores, formatos reais, mapping, BRL/fuso, cap da conta/cartão e host persistente
   precisam de confirmação humana. Não criar contas nem provisionar segredos por agentes.
4. APPROVAL_SIGNING_KEY exclusivamente na máquina/runtime do humano; ausente neste cloud.
   Humano provisiona e assina/verify via tty. Presença por nome não prova valor/validade.
5. Autorizar separadamente qualquer deploy, envio, live ou exposição real em sessão futura.
   Executor Meta de launch/activate/scale reais continua fora do escopo; apenas pausa existe.

## Riscos
- Distribuições são hipóteses, não dados de mercado. Acerto realista/pessimista com regras
  atuais (100 seeds) é 26%/5%; não há garantia de lucro ou custo por vencedor. Média até
  validar é condicionada ao sucesso; waste é excedente de teto, não perda econômica total.
- Lab pausa G3 no teto nominal: variantes do hard cap indistinguíveis. Não recalibrar esse
  parâmetro com esta evidência. Receita esperada não é saldo reciclável.
- HMAC depende do isolamento/proteção da chave; assinatura não substitui limites externos.
  Alteração de conteúdo/destinatário exige nova aprovação. Arquivos antigos não autorizam.
- ACK/uncertain exigem reconciliação. Falha remota preserva estado ativo; backup antigo
  pode conter ativos. Restore só em banco novo com processos parados/revisão antes de uso.
- Escritor e preflight testados com mocks; não houve validação de integração de conta real.
  preflight não configura limites nem valida validade de credenciais declaradas por nome.
- Scheduler depende de flock/host Linux ou WSL persistente; este cloud não garante cron.
  Telegram segue opcional/desabilitado; não é barreira exclusiva de proteção financeira.

## Falta / próximo passo
Revisão de Claude do PR único e decisão humana do ADR-018. Seguir o checklist português
no host humano antes dos aceites reais; nenhum passo real/cadastro/gasto autorizado por
esta entrega. Cards T-31–T-39 com evidência em review; LOCK vazio ao encerrar.

### BATCH-02 T-39
Preflight humano/JSON com exit 1 em erro, GET Meta só por opt-in e MockTransport nos testes. 37 casos de presença/cap/cartão/backup/trava/alerta/panic, valores sensíveis omitidos, HMAC nunca lido mesmo presente. Checklist português e HANDOFF reescrito; offline retorna erros esperados sem rede. Gate final com coverage e render; rules.yaml intacto.

## T-40 (Claude) — Ed25519 e ADR-018 aplicado
- BATCH-02 (#28) mergeado. ADR-018 aceito pelo humano: G3 com 2 vendas e teto 3× aplicado.
- Aprovação agora Ed25519 (ADR-022): privada só na máquina humana, pública em settings.yaml.
- **Pendente do humano:** `arb approve keygen --output ~/.arb/approval_ed25519` na própria
  máquina e PR com `approval_public_key`. Até lá launch/activate são recusados (fail-closed).
- Pendentes reais F5/F6 seguem em docs/validation/f5-f6-checklist.md.

## T-41 (Codex) — chave pública fornecida pelo humano
- Base main fa0ec62 (PRs #28/#29 mergeados). Branch codex/t-41-public-key; PR para
  main sujeito à revisão do Claude, sem merge pelo Codex.
- Configurada approval_public_key exatamente como enviada pelo humano. Esta é pública;
  comentário inline limita a exceção detect-secrets a essa linha. Nenhuma chave privada
  real gerada, lida ou recebida; nenhuma API de produto, live, deploy, mensagem ou gasto.
- Fixture de preflight corrigida para definir chave sintética no YAML temporário,
  independente do valor versionado; teste de chave ausente continua obrigatório.
- Evidência local: 443 testes passaram, zero skips/render incluído; cobertura 87,97%;
  gate de dinheiro >=95% verde; Ruff check/format, doctor e detect-secrets verdes;
  contratos e config/rules.yaml intactos. T-41 em review; LOCK liberado.
- Próximo passo: Claude revisar PR e humano/Claude realizar merge; depois atualizar
  main na máquina Windows/WSL do humano. Para assinar, o humano aponta
  APPROVAL_PRIVATE_KEY_FILE para sua chave local, sem compartilhar o arquivo.
- Pendentes: aceites reais F5/F6, limites externos, Graph API, rastreio/Hotmart e host
  persistente conforme docs/validation/f5-f6-checklist.md. Executor Meta para criar,
  ativar ou escalar exposição real continua ausente; chave pública não o implementa
  nem autoriza execução real. Histórico acima de BATCH-02/T-40 descreve aqueles momentos;
  a pendência de enviar a chave pública foi resolvida por esta tarefa, sujeito ao merge.

## BATCH-03 (planejado por Claude, a executar pelo Codex)
- #30 (T-41) revisado e mergeado: chave pública Ed25519 do humano em settings.yaml.
  Aprovações reais agora verificáveis; isto não habilita operação real.
- T-31–T-41 movidos para `board/done` (mergeados em #28, #29, #30).
- Próximo: `ops/batches/BATCH-03.md`, T-42–T-57 — ledger de intenções, reconciliação,
  pausa remota no scheduler, matriz de queda, restore em quarentena, backup antes de escrita,
  matriz de ingestão, aprovação new_offer/creative_set, escala assinada, porta remota +
  FakeMeta, idempotência ponta a ponta, drill completo, contrato Graph (bloqueio
  documental), painel/preflight e runbook de incidentes.
- Continuam pendentes do humano: F5/F6 reais, V-01–V-06, limites externos, host persistente.
