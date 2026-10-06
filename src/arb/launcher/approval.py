"""HMAC humano. Chave só no ambiente do operador; nunca em arquivos ou auditoria."""

import hashlib
import hmac
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from arb.models import Approval


def canonical(approval: Approval) -> bytes:
    return json.dumps(
        approval.model_dump(mode="json", exclude={"signature"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _key() -> bytes:
    value = os.environ.get("APPROVAL_SIGNING_KEY")
    if not value:
        raise ValueError("APPROVAL_SIGNING_KEY ausente; configure somente na máquina humana")
    return value.encode("utf-8")


def sign(approval: Approval) -> Approval:
    """Primitiva usada pelo comando humano; não decide status nem concede aprovação."""
    signature = hmac.new(_key(), canonical(approval), hashlib.sha256).hexdigest()
    return Approval.model_validate(approval.model_dump() | {"signature": signature})


def verify(approval: Approval) -> None:
    key = _key()
    if not approval.signature:
        raise ValueError("aprovação sem assinatura humana")
    expected = hmac.new(key, canonical(approval), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, approval.signature):
        raise ValueError("assinatura humana inválida")


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def sign_file(source: Path, confirm, *, now: datetime | None = None) -> Path:
    if not is_interactive():
        raise ValueError("aprovação exige tty interativo na máquina humana")
    if source.parent.name != "pending" or source.is_symlink() or not source.is_file():
        raise ValueError("use um arquivo regular em pending/")
    approval = Approval.model_validate_json(source.read_text())
    if source.name != approval.id + ".json" or approval.status != "pending":
        raise ValueError("proposta pending com id correspondente ao arquivo é obrigatória")
    if approval.signature or approval.decided_at:
        raise ValueError("proposta já contém decisão ou assinatura")
    message = (
        f"Aprovar {approval.id}: kind={approval.kind}; "
        f"exposição máxima={approval.max_exposure_cents} centavos; "
        f"plan_hash={approval.plan_hash}; resumo={approval.summary}?"
    )
    if not confirm(message):
        raise ValueError("aprovação cancelada pelo humano")
    now = now or datetime.now(UTC)
    decided = Approval.model_validate(
        approval.model_dump() | {"status": "approved", "decided_at": now}
    )
    signed = sign(decided)
    directory = source.parent.parent / "approved"
    if directory.is_symlink():
        raise ValueError("diretório approved não pode ser symlink")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / source.name
    # Publicar sem sobrescrever; remover pending só após gravação completa.
    with destination.open("x", encoding="utf-8") as file:
        file.write(signed.model_dump_json(indent=2) + "\n")
    source.unlink()
    return destination
