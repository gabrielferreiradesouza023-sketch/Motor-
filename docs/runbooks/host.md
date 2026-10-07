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
