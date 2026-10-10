# Dia 1 — fumaça humana com o motor observando

Use Linux/WSL no computador do operador, na raiz do checkout atualizado. Se precisar preparar
Python 3.12/uv/Git/WSL, siga [operador.md](operador.md). Substitua todo `<...>` por dado
verificado por você. Os testes usam dados **sintéticos**, que não são valores do provedor.
O motor permanece em simulação; os comandos abaixo não criam nem operam campanha na Meta.

## 1. Tetos externos — faça pessoalmente

No emissor, limite do cartão **R$300**. Na Meta, spend_cap da conta **R$300**, limite de gasto
na campanha **R$220**, moeda **BRL** e fuso **America/Sao_Paulo**. Confira o efeito real de cada
limite no próprio serviço. O teto local bruto de 25000 centavos é um alerta, não substitui
os limites externos. Nenhuma configuração externa é aplicada por este roteiro.

## 2. Preparar o motor em simulação

Se houver banco operacional, quarentena ou intenção pendente, consulte
[incidentes.md](incidentes.md) antes de usar comandos de manutenção. Doctor não recria um
banco existente inválido. Migrar só depois de conferir o diagnóstico e preservar um backup
se o banco já existir; os comandos de backup/drill abaixo usam destino separado da produção.

```sh
export LIVE_MODE=false
uv run arb doctor --root .
uv run arb db migrate --database data/engine.db
uv run arb scheduler once --database data/engine.db --root . --output reports/scheduler
uv run arb db backup --database data/engine.db --output data/backups
uv run arb db drill --backups data/backups --json
```

Esperado: doctor OK, migrações OK, ciclo local, backup e drill `passed` em quarentena, sem
sobrescrever o banco de trabalho. Para banco antigo não migrado, resolver o erro de doctor
com backup/migração antes de repetir. Não instalar serviço para observar manualmente.

A oferta precisa existir no banco, com `producer_paid_traffic_ok=true` e `evidence_ref` que
aponte para permissão escrita real. Se ainda não foi importada, use os CSVs internos do Scout
preenchidos/revisados por você (contratos/exemplos do repositório, não um formato presumido
de exportação Hotmart). Exemplo sintético não é autorização do produtor.

```sh
uv run arb scout import --offers "<CSV_OFERTAS_COM_PERMISSAO>" --adlibrary "<CSV_OBSERVACOES_ADLIBRARY>" --database data/engine.db
```

Se a oferta já existe, não repetir a importação. Conferir seu ID e a permissão antes do passo 6.

## 3. Assinar os registros humanos dos limites

Na **máquina assinadora**, configure o caminho da chave privada existente fora do repo e
confirme os dois limites depois de verificá-los nos serviços. Nunca gere outra chave por
este roteiro, compartilhe a privada, ou leve-a ao cloud/host de leitura. Se são máquinas
diferentes, transfira somente `ops/validation-status.json` assinado ao checkout do operador,
com a mesma chave pública. Referências são descrições sem segredos, não arquivos para ler.

```sh
export APPROVAL_PRIVATE_KEY_FILE="<CAMINHO_CHAVE_EXISTENTE_NA_ASSINADORA>"
uv run arb validate record card_limit --evidence "<REFERENCIA_LIMITE_CARTAO_VERIFICADO>" --root .
uv run arb validate record spend_cap --evidence "<REFERENCIA_SPEND_CAP_VERIFICADO>" --root .
```

Confirmar em TTY somente conteúdo verificado. Registros expiram em sete dias e não autorizam
exposição do motor. A ausência de assinatura válida bloqueia o go/no-go.

## 4. Configurar leitura Meta somente no host do operador

Obtenha pessoalmente token com `ads_read`, confirme permissões/conta e a versão Graph vigente.
Não compartilhar valores nem colocá-los em arquivos versionados; o programa não carrega `.env`.
Os placeholders abaixo são fornecidos pelo humano, não valores sugeridos de conta/versão.

```sh
export META_ACCESS_TOKEN="<TOKEN_LOCAL_ADS_READ>"
export META_AD_ACCOUNT_ID="<ID_CONTA_VERIFICADO>"
export META_API_VERSION="<VERSAO_GRAPH_VERIFICADA>"
```

## 5. Go/no-go de observação

| Conferência humana | Pronto quando |
|---|---|
| Limites externos | cartão/conta/campanha configurados e conferidos |
| Permissão do produtor | true e referência escrita real na oferta |
| Leitura | token ads_read, conta BRL/fuso correto e versão conferida |
| Proteção local | banco migrado, backup recuperável e drill de até 48h |
| Registros | card_limit/spend_cap assinados e recentes |

```sh
uv run arb readiness --scope observe --root . --json
```

Antes de registrar a fumaça, é esperado `ready=false`/exit 1 com `smoke_registered` e
`smoke_offer_permission` pendentes. Corrija as demais pendências e siga apenas para criar a
campanha **pausada**, não para ativá-la. Scope observe autoriza somente leitura; dispensa os
aceites completos F5/F6/rastreio/Graph/host para esta rotina humana. Full continua não pronto.

## 6. Criar a fumaça PAUSADA e registrar os IDs

Crie pessoalmente no Gerenciador uma campanha pausada, um conjunto e três anúncios/criativos.
Confira o limite da campanha e os três IDs reais; não usar IDs dos exemplos. A oferta do
banco precisa corresponder ao produto anunciado. Registrar é somente uma escrita local auditada.

```sh
uv run arb smoke register --campaign <CAMPANHA> --adset <CONJUNTO> --ad <ANUNCIO_1> --ad <ANUNCIO_2> --ad <ANUNCIO_3> --offer <OFERTA> --geo <GEO_VERIFICADO> --cap-cents 25000 --database data/engine.db
uv run arb readiness --scope observe --root . --json
```

Esperado agora: `ready=true`, exit 0. Se continuar não pronto, resolver todos os itens antes
de ativar. Nenhum comando de readiness ou registro ativa a campanha.

## 7. Ativar no Gerenciador

Somente o humano ativa a fumaça depois do go/no-go e da revisão dos limites. O motor não a
pausa, mesmo sob freio/dado atrasado. A observação não é licença para aumentar verba.

## 8. Rotina três vezes ao dia

Rode nos horários de `settings.cycles`, acompanhe pessoalmente e preserve os relatórios.
A janela padrão começa na data local do registro e termina hoje, no fuso configurado.

```sh
uv run arb smoke daily --campaign <CAMPANHA> --database data/engine.db --output-dir reports/smoke --json
```

Se já validou seu formato de vendas, esta é uma alternativa para uma das coletas; forneça
CSV local e mapa declarativo explicitamente. Não presumir formato de exportação do provedor.

```sh
uv run arb smoke daily --campaign <CAMPANHA> --database data/engine.db --sales-csv "<CSV_VENDAS_LOCAL>" --mapping "<MAPA_VENDAS_VALIDADO>" --output-dir reports/smoke --json
```

| Código | O que fazer |
|---|---|
| 0, abaixo de 80% | observar e conferir frescor/números |
| 0, `ATENÇÃO: prepare-se para pausar` | preparar pausa manual e conferir limites |
| 2, `PAUSE AGORA NO GERENCIADOR` | pausar pessoalmente agora; conferir gasto real |
| 3 | coleta falhou, nenhum relatório novo; conferir token/versão/leitura no host e repetir |
| 1 | corrigir registro, janela, mapa ou destino; não remover relatório/banco para contornar |

Gasto bruto e CPM estão em centavos; CTR/hook são frações (0,02 = 2%).
Relatórios JSON/Markdown são datados pelo minuto local e não sobrescrevem anteriores. Uma
segunda coleta no mesmo minuto exige esperar outro minuto ou usar outro diretório. Dado
atrasado recebe aviso; coleta recente não garante que o provedor atualizou todos os números.
Daily lê Meta e opcionalmente importa vendas; não publica ponte nem coleta Worker. Visitas e
checkouts dependem dos eventos da ponte já coletados no banco pelo fluxo de rastreio existente
ou da verificação humana separada. Falta de dado não é zero de conversão nem aceite de V-02.

## 9. O que não fazer

Não ampliar orçamento, ligar C/CAPI, instalar/deployar serviço ou executar exposição Graph por
este roteiro. Nunca compartilhar token, privada, dados pessoais ou fatura completa com o
cloud/Claude. Não interpretar saída observe pronta como prontidão full ou aceite F5/F6.

## 10. Sucesso da fumaça e próxima leitura

Conferir **≥2.000 impressões por criativo**, **≥40 visitas à ponte**, fatura com imposto e
**≥1 checkout casado com ad_id**. São critérios de coleta, não prova de vencedor/ROI.
Guardar evidências redigidas e usar [piloto.md](piloto.md) para perfil observado/calibração;
sem evidência suficiente, o resultado fica pendente. Não autoriza laboratório com dinheiro.

### O que o humano precisa fazer

| Item | Onde | Critério de pronto |
|---|---|---|
| Cartão R$300 | emissor | limite configurado e registro assinado ≤7 dias |
| spend_cap R$300 | conta Meta | limite configurado e registro assinado ≤7 dias |
| Campanha R$220 | Gerenciador | limite efetivo antes de ativar |
| Conta e versão | Meta/host | BRL, America/Sao_Paulo, ads_read e versão verificados |
| Oferta e permissão | produtor/Scout local | permissão escrita, true e evidence_ref |
| Backup | próprio host | banco migrado, restore em quarentena, drill ≤48h |
| Campanha e IDs | Gerenciador/registro local | pausada, três anúncios, cap local 25000 |
| Go/no-go | próprio host | observe ready=true antes de ativar |
| Ativação e pausas | Gerenciador | operação exclusivamente humana e limites conferidos |
| Ponte/vendas/fatura | provedor/host | coleta e casamento verificados; mapa real validado |
| Evidência de sucesso | próprio host | amostras e checkout casado; valores redigidos |
