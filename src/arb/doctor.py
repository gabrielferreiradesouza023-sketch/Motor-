"""Diagnóstico local da F0; nunca lê .env nem faz chamadas de rede."""

import os
import sqlite3
from pathlib import Path

from arb.config import validate_config
from arb.db import TABLES, Repository, connect, migrate, migration_catalog
from arb.models import MODEL_TYPES, contract_name, contract_text

INTEGRATION_VARIABLES = (
    "META_ACCESS_TOKEN",
    "META_AD_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_D1_DATABASE_ID",
    "HOTMART_WEBHOOK_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


def diagnose(root: Path) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    from arb.launcher.execute import require_simulation

    try:
        require_simulation()
    except ValueError:
        errors.append("LIVE_MODE precisa ser false na F0 (ausente usa false).")
    try:
        validate_config(root)
    except Exception:
        errors.append("Configuração ausente ou inválida: confira config/*.yaml.")
    for model in MODEL_TYPES:
        path = root / "contracts" / contract_name(model)
        try:
            if path.read_text() != contract_text(model):
                errors.append(f"Contrato divergente: {path.name}.")
        except OSError:
            errors.append(f"Contrato ausente/ilegível: {path.name}.")
    from arb.permissions import inspect_paths

    privacy = inspect_paths(root)
    errors.extend(
        "Caminho financeiro com symlink/indisponível"
        for row in privacy["findings"]
        if row["kind"] != "mode"
    )
    warnings.extend(
        "Permissão financeira aberta: " + row["path"]
        for row in privacy["findings"]
        if row["kind"] == "mode"
    )
    warnings.extend(privacy["warnings"])
    if not errors:
        path = root / "data" / "engine.db"
        connection = None
        try:
            if not path.exists():
                connection = connect(path)
                migrate(connection)
            else:
                connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("integridade")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("referências")
            applied = dict(connection.execute("SELECT version, checksum FROM schema_migrations"))
            expected = {number: data[1] for number, data in migration_catalog().items()}
            if applied != expected:
                raise ValueError("migrações")
            for model in TABLES:
                Repository(connection, model).list()  # valida payloads persistidos
            from arb.ledger import pending

            if count := len(pending(connection)):
                warnings.append(f"{count} intenções pendentes: reconciliar antes de nova escrita.")
            triggers = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            }
            if (
                not {
                    f"{name}_no_{operation}"
                    for name in ("snapshots", "decisions", "actions")
                    for operation in ("update", "delete")
                }
                <= triggers
            ):
                raise ValueError("proteção append-only ausente")
        except Exception:
            errors.append("Banco inválido: confira integridade, migrações, referências e payloads.")
        finally:
            if connection is not None:
                connection.close()
    for name in INTEGRATION_VARIABLES:
        if not os.environ.get(name):
            warnings.append(f"{name}: ausente (opcional na F0; integração futura).")
    from arb.launcher.approval import configured_public_key

    try:
        configured_public_key(root / "config/settings.yaml")
    except ValueError:
        warnings.append(
            "approval_public_key: ausente; launch/activate recusados até o humano rodar "
            "`arb approve keygen` e versionar a chave pública (ADR-022)."
        )
    from arb import hostinfo

    warnings.extend(hostinfo.inspect()["warnings"])
    return errors, warnings
