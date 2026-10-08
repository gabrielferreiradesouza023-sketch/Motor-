"""Confirmações humanas vinculadas ao item; leitura nunca consulta a chave privada."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arb.accept import replace_document
from arb.launcher import approval
from arb.permissions import reject_links

HUMAN_ITEMS = tuple(f"V-{n:02d}" for n in range(1, 7)) + (
    "card_limit",
    "spend_cap",
    "persistent_host",
    "service_installed",
)


def fresh(stamp, now, *, days=7):
    if not isinstance(stamp, str):
        return False
    try:
        value = datetime.fromisoformat(stamp)
        return value.utcoffset() is not None and timedelta(0) <= now - value <= timedelta(days=days)
    except ValueError:
        return False


def load_registry(path: Path) -> dict:
    reject_links(path)
    document = json.loads(path.read_text())
    if (
        not isinstance(document, dict)
        or type(document.get("schema")) is not int
        or document["schema"] != 1
        or not isinstance(document.get("items"), dict)
        or set(document["items"]) != set(HUMAN_ITEMS)
    ):
        raise ValueError("registro humano inválido")
    return document


def valid_record(item, row, now, *, settings=approval.SETTINGS) -> bool:
    try:
        if (
            not isinstance(row, dict)
            or row.get("kind") != "human_validation"
            or row.get("item") != item
            or row.get("status") != "confirmed"
            or row.get("by") != "human"
            or not fresh(row.get("checked_at"), now)
            or not isinstance(row.get("evidence"), str)
            or not row["evidence"].strip()
        ):
            return False
        reject_links(settings)
        approval.verify_document(row, settings=settings)
        return True
    except (ValueError, OSError):
        return False


def record(item, evidence, confirm, *, root=Path("."), now=None):
    if item not in HUMAN_ITEMS:
        raise ValueError("item desconhecido")
    if not approval.is_interactive():
        raise ValueError("registro exige tty interativo na máquina humana")
    if not evidence.strip():
        raise ValueError("evidência/referência obrigatória; nunca inserir segredos")
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("registro exige timestamp com fuso")
    path = root / "ops/validation-status.json"
    document = load_registry(path)
    original = path.read_text()
    if json.loads(original) != document:
        raise ValueError("registro mudou durante a leitura")
    settings = root / "config/settings.yaml"
    reject_links(settings)
    if not confirm(f"Confirmar {item} com a referência {evidence}? Não autoriza gasto."):
        raise ValueError("registro cancelado pelo humano")
    row = {
        "kind": "human_validation",
        "item": item,
        "status": "confirmed",
        "by": "human",
        "checked_at": now.astimezone(UTC).isoformat(),
        "evidence": evidence.strip(),
    }
    document["items"][item] = approval.sign_document(row, settings=settings)
    replace_document(path, document, original)
    return document["items"][item]


def show(*, root=Path("."), now=None):
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("registro exige timestamp com fuso")
    document = load_registry(root / "ops/validation-status.json")
    return {
        item: {
            "valid": valid_record(item, row, now, settings=root / "config/settings.yaml"),
            "status": "confirmed"
            if valid_record(item, row, now, settings=root / "config/settings.yaml")
            else "pending",
        }
        for item, row in document["items"].items()
    }
