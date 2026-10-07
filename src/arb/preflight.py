"""Checklist read-only. Nenhuma chave de assinatura é lida; rede exige opt-in humano."""

import fcntl
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from arb.analyst.report import operational_status
from arb.db.restore import restore_new
from arb.launcher.approval import configured_public_key
from arb.launcher.panic import panic
from arb.meta.pause import PauseWriter
from arb.meta.read import Reader
from arb.rules import load_rules

REQUIRED_CREDENTIALS = (
    "META_ACCESS_TOKEN",
    "META_AD_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_D1_DATABASE_ID",
    "HOTMART_WEBHOOK_SECRET",
)


def make_reader(version: str) -> Reader:
    """Somente chamado pelo humano com --read-meta; nunca acessa chave HMAC."""
    return Reader(
        os.environ.get("META_ACCESS_TOKEN", ""), os.environ.get("META_AD_ACCOUNT_ID", ""), version
    )


def inspect(
    *,
    root: Path = Path("."),
    database: Path = Path("data/engine.db"),
    reader: Reader | None = None,
    allow_meta_read: bool = False,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("preflight requer timestamp com fuso horário")
    checks = []
    names = frozenset(os.environ)  # Somente NOMES; preflight nunca lê a chave privada.

    def record(name, ok, message, fix, *, warning=False):
        checks.append(
            {
                "name": name,
                "status": "ok" if ok else "aviso" if warning else "erro",
                "message": message,
                "fix": "" if ok else fix,
            }
        )

    cap = None
    try:
        cap = load_rules(root / "config/rules.yaml").controls.total_cap_cents
        record("rules", True, "Tetos estruturais válidos", "")
    except Exception:
        record(
            "rules", False, "Configuração de tetos inválida", "Restaurar config/rules.yaml aprovado"
        )
    missing = sorted(set(REQUIRED_CREDENTIALS) - names)
    record(
        "credentials",
        not missing,
        "Credenciais declaradas por nome"
        if not missing
        else "Nomes ausentes: " + ", ".join(missing),
        "Configurar no host humano; não enviar valores a agentes",
    )
    try:
        configured_public_key(root / "config/settings.yaml")
        public_ok = True
    except ValueError:
        public_ok = False
    record(
        "approval_public_key",
        public_ok,
        "Chave pública Ed25519 do humano versionada"
        if public_ok
        else "approval_public_key ausente/inválida em config/settings.yaml",
        "Na máquina humana: arb approve keygen; colar a chave pública em settings.yaml via PR",
    )
    version = os.environ.get("META_API_VERSION", "")
    version_ok = isinstance(version, str) and bool(re.fullmatch(r"v[0-9]+\.[0-9]+", version))
    record(
        "graph_version",
        version_ok,
        "Versão Graph definida" if version_ok else "Versão Graph ausente/inválida",
        "Definir META_API_VERSION após validação humana V-06",
    )
    owned = False
    account_ok = False
    account_message = "Conta Meta não verificada; nenhuma rede por padrão"
    try:
        if reader is None and allow_meta_read and version_ok and not missing:
            reader = make_reader(version)
            owned = True
        if reader is not None:
            reader.account()  # também exige BRL e America/Sao_Paulo
            body = reader.get(reader.account_id, {"fields": "spend_cap"})
            raw = body.get("spend_cap")
            amount = (
                int(raw)
                if type(raw) is int or (isinstance(raw, str) and raw.isascii() and raw.isdigit())
                else 0
            )
            account_ok = cap is not None and 0 < amount <= cap
            account_message = (
                "Limite Meta dentro do teto total"
                if account_ok
                else "Limite Meta ausente, desativado ou acima do teto"
            )
    except Exception:
        account_message = "Leitura/validação Meta falhou (detalhes externos omitidos)"
    finally:
        if owned:
            reader.close()
    record(
        "meta_spend_cap",
        account_ok,
        account_message,
        "Humano: configurar spend_cap positivo <= total_cap_cents e usar --read-meta para GET",
    )
    raw_card = os.environ.get("CARD_LIMIT_CENTS", "")
    try:
        card_cents = int(raw_card) if raw_card.isascii() and raw_card.isdigit() else 0
    except ValueError:
        card_cents = 0
    card_ok = cap is not None and 0 < card_cents <= cap
    record(
        "card_limit",
        card_ok,
        "Orçamento do cartão dentro do teto total"
        if card_ok
        else "CARD_LIMIT_CENTS ausente/inválido/acima do teto",
        "Declarar CARD_LIMIT_CENTS positivo <= total_cap_cents; confirmar limite no emissor",
    )
    database = database if database.is_absolute() else root / database
    from arb.permissions import inspect_paths

    privacy = inspect_paths(root, database=database)
    record(
        "permissions",
        privacy["ok"],
        "Permissões financeiras fechadas"
        if privacy["ok"]
        else "Permissões abertas ou symlink em caminhos financeiros",
        "Humano: fechar modos/ACLs e remover symlinks no host",
    )
    if privacy["warnings"]:
        record(
            "permissions_platform",
            False,
            privacy["warnings"][0],
            "Humano: validar ACLs no Windows ou usar host Linux/WSL",
            warning=True,
        )
    backup = database.parent / "backups" / f"engine-{now.astimezone(UTC).date().isoformat()}.db"
    backup_ok = False
    try:
        if not database.is_file():
            raise ValueError("banco ausente")
        with TemporaryDirectory(prefix="arb-preflight-") as temporary:
            restore_new(backup, Path(temporary) / "restored.db")
        backup_ok = True
    except Exception:
        pass
    record(
        "backup_restore",
        backup_ok,
        "Backup do dia UTC restaura íntegro"
        if backup_ok
        else "Backup do dia ausente ou não restaurável",
        "Executar arb db backup e ensaiar restore em destino novo; nunca sobrescrever o banco",
    )
    operational = None
    try:
        with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as source:
            operational = operational_status(source, now=now)
    except Exception:
        pass  # Não imprimir payloads, caminhos ou exceções do banco.
    for name, ok, message, fix in (
        (
            "ledger",
            operational is not None and not operational["pending"],
            "Ledger vazio",
            "Executar arb ops pending; reconciliar por leitura antes de retomar",
        ),
        (
            "restore_quarantine",
            operational is not None and not operational["quarantine"],
            "Banco fora de quarentena",
            "Pausar, reconciliar e usar arb db release no terminal humano",
        ),
        (
            "backup_drill",
            operational is not None and operational["drill"]["status"] == "passed",
            "Drill de backup íntegro",
            "Executar arb db drill e corrigir backup falho antes de retomar",
        ),
    ):
        record(
            name, ok, message if ok else message + ": condição não satisfeita ou indisponível", fix
        )
    record(
        "alert_ack",
        operational is not None
        and not any(row["critical"] for row in operational["unacked_alerts"]),
        (
            f"Alertas incertos sem ack: {len(operational['unacked_alerts'])}; "
            f"críticos: {sum(row['critical'] for row in operational['unacked_alerts'])}"
            if operational is not None
            else "Estado de alertas indisponível"
        ),
        "Humano: arb ops alerts; ler relatório e arb ops ack <id> no tty",
    )
    lock_ok = False
    try:
        # Não criar nem editar a trava do scheduler; testar o mesmo arquivo existente.
        with database.with_suffix(database.suffix + ".scheduler.lock").open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock_ok = True
    except OSError:
        pass
    record(
        "scheduler_lock",
        lock_ok,
        "Trava do scheduler disponível" if lock_ok else "Trava ausente/ocupada/ilegível",
        "Preparar um ciclo local para criar a trava ou aguardar o ciclo atual; usar host Linux/WSL",
    )
    alert_ok = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"} <= names
    record(
        "alerts",
        alert_ok,
        "Configuração de alerta declarada (envio não testado)"
        if alert_ok
        else "Alerta opcional não configurado completamente",
        "Se desejado, configurar ambos os nomes e aprovar destinatário/envio no host humano",
        warning=True,
    )
    writer_ok = callable(panic) and callable(getattr(PauseWriter, "pause", None))
    record(
        "panic_writer",
        writer_ok,
        "Escritor de pausa/panic disponível (somente testes mock)"
        if writer_ok
        else "Escritor de pausa/panic ausente",
        "Instalar versão com T-36 e revisar testes de pausa antes do aceite real",
    )
    return {
        "ok": all(c["status"] != "erro" for c in checks),
        "checks": checks,
        "checked_at": now.astimezone(UTC).isoformat(),
        "scope": "read-only; presença por nome não valida valores/credenciais; sem habilitar live",
    }
