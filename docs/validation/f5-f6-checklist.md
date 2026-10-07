# Checklist humano antes do aceite real F5/F6

Esta entrega valida software com dados/chaves sintéticos e MockTransport. **Não declara
F5/F6 reais aceitos.** `LIVE_MODE=false` continua padrão; preflight não habilita live,
não aprova gasto, não assina propostas, não envia mensagens e não faz deploy.

## Preparar o host e as barreiras

1. #28/#29/#30 e #32 já foram revisados e mergeados. ADR-018 e a chave pública T-41
   estão resolvidos; revisar o PR BATCH-04 antes de usar estes kits. Simulação não valida conta real.
2. Usar um host persistente Linux/WSL com isolamento de operadores/agentes. Configurar
   segredos diretamente nesse host, nunca no chat/repositório/cloud dos agentes. Preflight
   inspeciona somente **nomes presentes**, sem provar valores não vazios, validade ou acesso:
   META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID,
   CLOUDFLARE_D1_DATABASE_ID e HOTMART_WEBHOOK_SECRET.
3. A chave pública T-41 já está versionada. Na máquina assinadora humana, configurar
   APPROVAL_PRIVATE_KEY_FILE para a chave existente; não gerar outra chave para este batch.
   Nunca levar a privada ao motor/cloud. O motor só conhece a pública (ADR-022).
4. Confirmar V-06 e definir META_API_VERSION (`vN.N`) no host humano. A conta precisa de
   BRL e America/Sao_Paulo. O leitor verifica moeda/fuso antes de ler `spend_cap`.
5. **Defesa independente:** configurar `spend_cap` positivo na conta Meta, em centavos BRL,
   ≤ `controls.total_cap_cents` (atualmente 240000 = R$ 2400). Zero significa sem limite e
   é recusado. Confirmar o limite restante/cumulativo no painel; o código não configura nada.
6. Declarar CARD_LIMIT_CENTS positivo ≤ total_cap_cents. Confirmar limite/bloqueios no emissor:
   uma variável de ambiente não configura nem comprova o limite físico do cartão.
7. Preparar banco e ciclo local em simulação, garantindo o arquivo `.scheduler.lock`.
   Executar `arb db backup`, confirmar backup do **dia UTC** em `data/backups/`, e ensaiar
   restore em caminho novo. Preflight restaura apenas uma cópia descartável temporária,
   sem sobrescrever/alterar o banco ou o backup. A trava existente é testada sem edição.

## Executar a inspeção

```sh
uv run arb doctor
uv run arb preflight
uv run arb preflight --json
```

Por padrão não há rede. O check `meta_spend_cap` fica em erro por falta de leitura da conta.
No **host humano**, após autorização para o aceite somente leitura, executar:

```sh
uv run arb preflight --read-meta
uv run arb preflight --read-meta --json
```

`--read-meta` faz somente GET (conta BRL/fuso e spend_cap). Neste batch essa opção foi
exercitada exclusivamente com MockTransport. Exit 1 se qualquer check for `erro`;
`aviso` é reservado ao alerta opcional. Nenhum token, chave, chat ou resposta externa é
impresso. Corrigir as instruções por check; não burlar erros alterando limites no código.
`ok` significa checks de preparação satisfeitos, não aprovação de exposição nem aceite real.

## Aprovação, pausa e reconciliação

1. No terminal interativo do humano, revisar kind/exposição/hash/resumo antes de usar
   `arb approve sign ops/approvals/pending/<id>.json`. Sem tty o comando recusa. Testar
   `arb approve verify ops/approvals/approved/<id>.json` no mesmo ambiente protegido.
   Arquivos antigos sem assinatura são recusados. Mudança de qualquer campo invalida a assinatura Ed25519.
2. Launch e activate têm aprovações distintas. Uma aprovação consumida não pode reativar
   depois de pausa. O executor de exposição real continua fora deste batch: só o escritor
   de pausa existe. Não interpretar assinatura/preflight como disponibilidade de launch real.
3. Confirmar revisão dos testes de panic: POST exato `status=PAUSED`, intent antes do HTTP,
   resultado append-only, erro sanitizado. Em simulação o comando mantém
   `remote_pause_pending`; nenhum token real foi usado para o teste deste escritor.
4. Qualquer `uncertain` exige leitura/reconciliação do estado Meta antes de repetir ou
   retomar. Um ACK de pausa não substitui observação contínua; backup anterior pode conter
   entidades ativas. Parar processos e revisar/pausar antes de usar uma restauração.
5. Telegram é opcional e permanece desabilitado. Nome presente não comprova credencial;
   configuração real, destinatário e envio exigem aprovação assinada separada. Falha de
   alerta não pode ser a única barreira de proteção da verba.

## Decisões/aceites que continuam humanos

- Claude revisar o PR BATCH-04 e humano realizar o merge; Codex não faz merge.
- ADR-018 já aceita; experimentos/alterações futuros exigem nova decisão humana.
- Validar V-01/V-02 Hotmart/rastreio e V-06 Graph com provedores reais, sem gastos automáticos.
- Validar host, cartão, conta, observabilidade e reconciliação; provisionar segredos fora dos agentes.
- Autorizar separadamente qualquer cadastro, deploy, live, envio ou exposição real em sessão futura.

Kit F5 read-only: [f5-acceptance.md](f5-acceptance.md). A evidência real é produzida pelo humano no próprio host.
