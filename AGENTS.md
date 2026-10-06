# Constituição dos agentes

## 0. Princípios inegociáveis

1. **O motor pode sempre gastar menos sozinho; nunca gastar mais sem aprovação humana.** Pausar é automático. Criar campanha, ativar anúncio ou aumentar verba exige um arquivo aprovado em `ops/approvals/`.
2. **Matar no sinal mais barato, confirmar só no dinheiro.** Toda entidade passa por portões com teto de gasto. Sem sinal, ela morre no teto.
3. **Nenhuma decisão com amostra insuficiente.** Toda regra tem amostra mínima. Abaixo dela, o estado é `insufficient_data`, nunca `kill` ou `pass`. O teto de gasto é a única exceção.
4. **Defesa em profundidade:** limite no cartão, limite na conta Meta, orçamento por campanha, regras do motor e aprovação humana. O código nunca é a única barreira.
5. **Simulação por padrão.** `LIVE_MODE=false` em qualquer ambiente novo.
6. **Tudo auditável:** cada ação com efeito externo gera uma linha na tabela `actions`, com a entrada, a saída, o operador e o id da aprovação.
7. **Nunca deletar entidades na Meta.** Só pausar. O histórico é um ativo.

---

## 9. Protocolo multiagente

Codex e Claude Code trabalham **um de cada vez** no mesmo repositório. A estrutura já está pronta para paralelismo futuro, com um agente por módulo.

1. **Início de sessão:** ler `AGENTS.md`, `ops/HANDOFF.md` e `ops/LOCK`.
2. **Bastão:** se o LOCK estiver vazio ou tiver mais de 12 h, escreva `agente | tarefa | timestamp`. Se estiver ocupado e recente, pare e informe o humano.
3. **Tarefa:** mova o arquivo da tarefa de `board/todo` para `board/doing`. Execute **apenas** o escopo dela.
4. **Contratos:** módulos só importam `arb.models` e as interfaces públicas de outros módulos. Mudar um modelo exige um ADR em `decisions.md` e a regeneração de `contracts/`.
5. **Qualidade:** `ruff check`, `pytest` e `arb doctor` precisam passar antes de mover para `review`.
6. **Fim de sessão:** atualize o `HANDOFF.md` (o que foi feito, o que falta, riscos), faça commit com mensagem convencional e libere o LOCK.
7. **Proibido:** refatorar fora do escopo, alterar `config/rules.yaml` sem ADR, rodar em `LIVE_MODE=true`, ler ou imprimir o conteúdo de `.env`.

Formato do arquivo de tarefa:
```markdown
# T-XX: título
Fase: F_  |  Depende de: T-__
## Objetivo
## Arquivos
## Critérios de aceite
## Testes obrigatórios
```

## Política de entrega definida pelo usuário

- Sempre trabalhar em branch `codex/<tarefa>`. Não fazer push direto em `main`.
- Ao pegar uma tarefa, fazer commit e push de `ops/LOCK` imediatamente.
- Abrir PR para `main`; Claude revisa antes do merge. Não fazer merge automático.
- Branches com dependências devem explicitar a ordem de revisão nos PRs e no handoff.
- O escopo foi ampliado após F0: seguir as fases em ordem. Não declarar F5 validada
  com conta real usando apenas testes simulados, nem avançar exposição real sem aprovação.

- Autorização mais recente: avançar T-21–T-29 em desenvolvimento e simulação locais,
  sem cadastros, gastos, deploys ou mensagens reais. ADR-010 documenta o escopo;
  aceite real F5/F6 continua pendente e não bloqueia validação sintética F7/F8.
