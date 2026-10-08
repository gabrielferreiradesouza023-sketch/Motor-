# Host persistente — pacote para revisão humana

Use Linux/WSL persistente, operador isolado e ACLs verificadas. Instalação/habilitação é
uma ação humana posterior, fora deste batch. O agente não executa systemctl.

No host humano, após checkout revisado e uv sync --frozen, preparar banco, backups e um ciclo
em simulação, gerando a trava. Renderizar:

```
uv run arb service render --root /caminho/absoluto/Motor- --user seu_usuario --output data/service
uv run arb service check --output data/service --json
```

As seis unidades renderizadas ficam em data/service, com manifest/hash. Revisar caminhos,
usuário, permissões, executável e timers antes de instalar manualmente. Arquivos-fonte em
 deploy/systemd são templates e não devem ser instalados sem renderização.

Scheduler: 09:00/18:00/23:30 America/Sao_Paulo, seguindo settings.cycles. A zona IANA delega
mudanças futuras de DST ao tzdata/systemd; não fixa UTC-3 para sempre. Backup: 00:10 UTC;
drill de restore: 00:20 UTC. Persistent permite catch-up; once registra slots perdidos sem
regras retroativas. Durante o drill só há cópia temporária em quarentena.

EnvironmentFile referencia /etc/arb/runtime.env; seu conteúdo nunca é lido pelo render/check.
Segredos são provisionados pelo humano fora do Git/cloud. A chave privada fica na máquina
assinadora, nunca no host do motor. ExecStart força LIVE_MODE=false mesmo se EnvironmentFile
contiver outro valor. Este pacote é para simulação; alteração para live exige revisão futura.

UMask=0077, NoNewPrivileges, PrivateTmp, ProtectSystem e ProtectHome reduzem acesso. A
verificação não comprova instalação, disponibilidade 24/7, conta/permissões Meta, limite
físico do cartão ou aceite F5/F6. Não instalar enquanto check falhar. Após instalação humana,
verificar reinício, timers, journal, backups e alertas. Dinheiro real continua bloqueado.

## Diagnosticar e gerar o plano (BATCH-05)

```sh
uv run arb service status --json
uv run arb service install-plan --output data/service
```

`status` só consulta informações do host e `systemctl show`; avisos de WSL não confirmam
persistência. No WSL, editar `/etc/wsl.conf` no próprio host, preservando outras seções:

```ini
[boot]
systemd=true
```

Depois executar `wsl --shutdown` no PowerShell do Windows e reabrir a distribuição. Isso
encerra todas as distribuições WSL e pode interromper trabalho; revisar antes. Mesmo com
systemd habilitado, WSL pode suspender. Não considerar esse ajuste prova de host sempre ligado.

`install-plan` verifica novamente as seis unidades, seus hashes e manifest, modos,
executável e trava. Em erro, exit 1 e nenhum plano. Em sucesso, imprime os comandos com os
caminhos absolutos do render, instalação, timers, execução manual única do scheduler,
conferência pelo journal e rollback. Não executa subprocessos nem lê runtime.env.
O operador revisa os comandos e confirma permissões do usuário renderizado; o pacote
continua forçando simulação. O rollback interrompe timers/serviços e remove somente as seis
unidades; dados/backups permanecem. Antes de retomar, revisar ledger e recuperação de ciclos.

Registro de disponibilidade real requer `arb validate record persistent_host` e
`arb validate record service_installed`, assinados na máquina humana com referências
redigidas. Diagnóstico/check/plano não preenchem esses registros. Roteiro completo:
[Guia do operador](operador.md) (T-76, entregue no mesmo batch).
