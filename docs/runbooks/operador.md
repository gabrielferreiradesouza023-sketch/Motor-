# Guia do operador — Windows/WSL e Linux

Execute pessoalmente, depois da revisão do Claude e do merge humano do PR BATCH-05 #36.
O planejamento #35 já foi mergeado. Este roteiro prepara simulação e aceites controlados;
o executor de exposição Graph continua ausente. Dinheiro real permanece bloqueado.

Substitua todos os valores entre `<...>` por informações verificadas por você. Não cole
placeholders literalmente, não invente valores e não repita comandos que terminaram incertos.
Compartilhe com Claude somente saídas/evidências redigidas: nunca tokens, arquivo de
credenciais, chave privada, IDs completos, dados pessoais de compradores ou fatura completa.
A assinatura comprova origem; conferir conteúdo, frescor e limites continua obrigatório.

## 1. Preparar WSL/Linux e o checkout

No PowerShell do Windows, consultar a instalação existente:

```powershell
wsl --status
wsl --list --verbose
```

Esperado: distribuição WSL 2 identificada. Se faltar WSL, seguir a
[documentação Microsoft](https://learn.microsoft.com/windows/wsl/install) no seu computador;
contas e instalação são decisões suas. No Linux nativo, seguir direto para o checkout.
**Enviar ao Claude:** versão WSL e sistema, sem nomes de usuário ou caminhos privados.

No terminal Linux/WSL, usar disco Linux para modos 0600/0700. O host precisa de Python 3.12,
uv e Git; verificar as versões. No primeiro checkout:

```sh
python3 --version
uv --version
git --version
git clone https://github.com/gabrielferreiradesouza023-sketch/Motor-.git "$HOME/Motor-"
cd "$HOME/Motor-"
git checkout main
git pull --ff-only
uv sync --frozen
export LIVE_MODE=false
uv run arb doctor
uv run arb service status --json
```

Se o checkout já existir, pular o clone e fazer o pull somente com árvore limpa. Reutilizar
sua autenticação GitHub existente; não incluir credenciais na URL. Esperado: doctor OK,
diagnóstico com timezone, WSL/PID 1 e unidades. Aviso “WSL sem systemd” aponta preparo
pendente; WSL pode suspender mesmo com systemd. **Enviar ao Claude:** SHA de `git rev-parse
HEAD`, doctor redigido e campos do diagnóstico; nenhuma variável de credencial.

## 2. Serviço em simulação

Usar o banco de simulação deste checkout. Não substituir banco operacional existente.
Se houver produção ou quarentena/intenções pendentes, consultar o
[runbook de incidentes](incidentes.md) antes de continuar.

```sh
export LIVE_MODE=false
uv run arb db migrate --database data/engine.db
uv run arb scheduler once --database data/engine.db --root . --output reports
uv run arb db backup --database data/engine.db --output data/backups
uv run arb db drill --backups data/backups --json
uv run arb service render --root "$PWD" --user "$(id -un)" --output data/service
uv run arb service check --output data/service --json
uv run arb service install-plan --output data/service
```

Esperado: ciclo simulado, backup privado, drill passed e check `ok: true`. O último comando
só imprime um plano. Revisar caminhos, usuário, seis unidades, timers, journal e rollback;
executar os comandos impressos pessoalmente somente após revisão. No WSL, seguir o passo
`[boot] systemd=true` do plano e executar `wsl --shutdown` no PowerShell; isso interrompe
as distribuições. Reabrir WSL e consultar:

```sh
uv run arb service status --json
```

Esperado depois da instalação humana: systemd PID 1, timers instalados/ativos; serviços
oneshot podem estar inativos depois de terminar. Conferir reinício, journal e backups.
ExecStart força simulação. Não alterar as unidades para live por este roteiro.
Disponibilidade contínua é uma avaliação humana, especialmente em WSL.

Na **máquina assinadora**, em checkout com a mesma chave pública, apontar
APPROVAL_PRIVATE_KEY_FILE para o arquivo privado existente fora do repo e confirmar
TTY/permissões (0600 em POSIX; ACLs no Windows). Não gerar outra chave, não mostrar seu
conteúdo e não levá-la ao host do motor/cloud. HOME do WSL e HOME do Windows podem ser
diferentes. Artefatos públicos assinados podem ser transferidos ao host; a privada fica
na máquina assinadora. Configurar o caminho real da chave existente nessa máquina,
substituindo o placeholder. Em terminal Linux/WSL da máquina assinadora:

```sh
export PYTHONUTF8=1
export APPROVAL_PRIVATE_KEY_FILE="<caminho-absoluto-da-chave-existente-fora-do-repo>"
```

Se a máquina assinadora usa PowerShell, configurar o mesmo nome em sua janela:

```powershell
$env:PYTHONUTF8 = "1"
$env:APPROVAL_PRIVATE_KEY_FILE = "<caminho-absoluto-da-chave-existente-fora-do-repo>"
```

Manter PYTHONUTF8=1 no terminal assinador antes de iniciar uv/Python: o JSON canônico é
UTF-8, inclusive seus caracteres Unicode. Não reutilizar uma .venv Linux no Windows; usar
o ambiente local da máquina assinadora.
Após verificar cada fato real, registrar separadamente:

```sh
uv run arb validate record persistent_host --evidence "<referencia-redigida-da-disponibilidade>"
uv run arb validate record service_installed --evidence "<referencia-redigida-dos-timers-journal-e-reinicio>"
```

Esperado: confirmação interativa e registro assinado só do item escolhido. Não confirmar
host persistente apenas por estar funcionando agora. **Enviar ao Claude:** check e status
redigidos, resultado do drill, avaliação da disponibilidade e registro assinado; nunca
runtime.env, chave ou dump completo do journal. Mais detalhes: [Host](host.md).

## 3. Hotmart — V-01, V-02, V-03 e V-05

Responder com evidência do provedor, sem presumir esquema do CSV ou parâmetros:

| Item | Pergunta a resolver pelo humano |
| --- | --- |
| V-01 | Afiliado tem webhook/postback? Se não, qual CSV real está disponível e quais cabeçalhos/formato/fuso? |
| V-02 | Qual parâmetro de rastreio é aceito e aparece no relatório, com qual limite/alfabeto? |
| V-03 | Cada produtor permite tráfego pago e página-ponte para a oferta escolhida? |
| V-05 | Qual prazo real de liberação e taxa de reembolso por produto? |

Na máquina assinadora, somente depois de obter respostas:

```sh
uv run arb validate record V-01 --evidence "<referencia-redigida-webhook-ou-csv>"
uv run arb validate record V-02 --evidence "<referencia-redigida-parametro-limite-relatorio>"
uv run arb validate record V-03 --evidence "<referencia-redigida-permissao-do-produtor>"
uv run arb validate record V-05 --evidence "<referencia-redigida-prazo-e-reembolsos>"
uv run arb validate show --json
```

Esperado: só fatos confirmados e assinados ficam `confirmed`; pending não é erro de parsing.
`record` não configura adaptadores nem taxas. Mudanças de mapping/rastreio/regras ficam em
PR separado com revisão; não editar rules.yaml para destravar. **Enviar ao Claude:** respostas
redigidas, fonte/data e registros assinados; amostras de cabeçalhos sem compradores/IDs.
Perguntas originais: [Validações da spec](../arb-engine-spec-v1.md#12-itens-a-validar-antes-ou-durante-o-desenvolvimento).

## 4. Meta — conta, app/token, V-04 e V-06

No próprio painel/host, confirmar conta BRL e America/Sao_Paulo, vínculos do app, permissões
e versão Graph efetivamente suportada. Provisionar tokens somente no host autorizado,
fora do Git/chat. Presença do nome de variável não comprova validade da credencial.
V-04 é a alíquota real dos impostos da fatura Meta; V-06 é versão/permissões/contrato Graph.
Consultar o [contrato pendente](../validation/meta-executor-contract.md) e o
[checklist F5/F6](../validation/f5-f6-checklist.md); não inferir endpoints ou permissões.

```sh
uv run arb validate record V-04 --evidence "<referencia-redigida-aliquota-da-fatura>"
uv run arb validate record V-06 --evidence "<referencia-redigida-versao-permissoes-e-contrato>"
uv run arb preflight --json
```

Esperado: registros assinados na máquina humana; preflight padrão sem rede pode recusar
credenciais/tetos/aceites ausentes. Confirmar V-06 não implementa executor Graph nem muda
settings/regras automaticamente. **Enviar ao Claude:** versão validada, referências oficiais,
moeda/fuso, alíquota e saída redigida; nunca token, app secret, fatura ou IDs completos.

## 5. Cartão e spend_cap

Confirmar teto físico no emissor e limite positivo da conta Meta, ambos dentro de
`controls.total_cap_cents` aprovado. Zero não é limite seguro. Declarar CARD_LIMIT_CENTS no
host humano com o valor real em centavos; isso não configura o emissor. Não aumentar limites
nem alterar rules.yaml por este roteiro. Verificar limite restante/cumulativo no painel.

```sh
uv run arb validate record card_limit --evidence "<referencia-redigida-limite-confirmado-no-emissor>"
uv run arb validate record spend_cap --evidence "<referencia-redigida-limite-confirmado-na-conta>"
uv run arb validate show --json
```

Esperado: assinatura de cada item; readiness ainda exige prova F5 e preflight coerentes.
**Enviar ao Claude:** tetos em centavos e referências redigidas, sem número de cartão,
código de segurança, IDs completos ou imagens financeiras privadas.

## 6. Aceites F5, F6 e rastreio — só no host humano autorizado

Esta etapa depende de autorização humana específica, credenciais/versão verificadas e
pré-requisitos dos kits. O modo live dos kits é configurado deliberadamente pelo próprio
humano **em terminal manual isolado**, conforme os documentos ligados abaixo. Nunca no
Codex/cloud, scheduler ou serviço: unidades continuam em simulação. Se faltar dado,
permissão ou entidade de teste existente, registrar bloqueio e parar o kit afetado.

F5 faz somente leitura. No host humano autorizado:

```sh
uv run arb accept f5 --out ops/validation/f5.json
```

Na máquina assinadora, revisar conteúdo, data/checks/teto, apontar a chave existente e usar:

```sh
uv run arb evidence sign ops/validation/f5.json
uv run arb evidence verify ops/validation/f5.json
```

Esperado: `Aceite F5: passed`, depois assinatura válida. Os kits salvam **sem assinatura**;
sem o passo humano readiness recusa. Arquivos não são sobrescritos: preservar tentativas
anteriores em caminhos novos; colocar só a versão revisada/assinada no caminho de readiness.
**Enviar ao Claude:** JSON assinado e redigido. [Detalhes F5](../validation/f5-acceptance.md).

F6 exige anúncio único exclusivamente de teste **já existente**, entidade local corretamente
mapeada e nenhuma pendência/quarentena. Confirmar os IDs somente no terminal privado:

```sh
uv run arb accept register-test --meta-id <id-remoto-de-teste> --database data/engine.db
uv run arb accept pause --meta-id <id-remoto-de-teste> --database data/engine.db --out ops/validation/f6_pause.json
uv run arb evidence sign ops/validation/f6_pause.json
uv run arb evidence verify ops/validation/f6_pause.json
```

Esperado: cadastro interativo, somente pausa e PAUSED observado; depois assinatura válida.
Não criar/ativar anúncios por este roteiro. Resultado incerto exige consultar ledger e
reconciliação por leitura antes de nova tentativa; usar o runbook de incidentes.
**Enviar ao Claude:** prova assinada redigida ou bloqueio, nunca IDs completos.
[Detalhes F6](../validation/f6-pause-acceptance.md).

Rastreio exige Worker já publicado com suporte ao evento de teste, origem autorizada,
entidade/alias existentes e V-01/V-02 resolvidas. Nenhum deploy faz parte deste roteiro.
Propor em modo false, revisar kind `tracking_test`, exposição zero, URL/origem/evento exatos
e assinar a proposta na máquina humana:

```sh
export LIVE_MODE=false
uv run arb accept tracking-propose --url <base-https-worker> --origin <origem-da-ponte> --entity-id <id-local>
uv run arb approve sign ops/approvals/pending/<id-proposta-rastreio>.json
uv run arb approve verify ops/approvals/approved/<id-proposta-rastreio>.json
```

Depois, no terminal manual de aceite do humano com o modo exigido pelo kit e sua
credencial de sincronização configurada privadamente:

```sh
uv run arb accept tracking --url <mesma-base-https-worker> --approval-id <id-proposta-rastreio> --out ops/validation/tracking.json
uv run arb evidence sign ops/validation/tracking.json
uv run arb evidence verify ops/validation/tracking.json
export LIVE_MODE=false
```

Esperado: evento sintético reconhecido, produção inalterada, aceite passed e assinatura
válida. Venda sintética fica em cópia descartável; resultado uncertain não deve ser reenviado
automaticamente. Ao terminar os kits, retornar o terminal manual para simulação.
**Enviar ao Claude:** prova assinada redigida e resultado dos checks; nunca credencial de
sync ou export bruto. [Detalhes rastreio](../validation/tracking-acceptance.md).

## 7. Conferir prontidão e entregar a revisão

Transferir os artefatos assinados para o checkout do host do motor, que usa somente a
pública versionada. Conferir relógio e permissões; não transferir a privada. Na raiz:

```sh
export LIVE_MODE=false
uv run arb validate show --json
uv run arb readiness
uv run arb readiness --json
```

Esperado neste estágio: **não pronto**, exit 1 e pendências reais. Evidência sem assinatura
recebe “evidência não assinada”; registro sem assinatura válida/vencido continua pending.
Aceites/validações duram até sete dias, sem timestamp futuro; drill de backup até 48 horas.
Mesmo com todos esses itens resolvidos, Graph permanece bloqueado por T-55: sua implementação
exige contrato validado, novo trabalho e revisão separada. Nenhum desses comandos autoriza gasto.

**Enviar ao Claude:** readiness redigido, provas assinadas, registros e lista de bloqueios
com responsável/impacto. Solicitar revisão; merge é humano. Não tratar mocks, assinatura,
serviço em simulação ou presença de variáveis como aceite de dinheiro real.

Para começar a fumaça humana em observação, siga [o roteiro do dia 1](dia-1.md).
