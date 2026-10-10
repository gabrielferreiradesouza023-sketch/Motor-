"""Assinatura humana Ed25519 (ADR-022).

Chave privada só na máquina do humano (arquivo fora do repositório, apontado por
APPROVAL_PRIVATE_KEY_FILE). O motor e os agentes só conhecem a chave pública versionada em
config/settings.yaml: verificar nunca permite assinar.
"""

import hashlib
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from arb.models import Approval
from arb.permissions import private_directory, private_open, reject_links

SETTINGS = Path("config/settings.yaml")


def canonical_document(document: dict) -> bytes:
    return json.dumps(
        {key: value for key, value in document.items() if key != "signature"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical(approval: Approval) -> bytes:
    return canonical_document(approval.model_dump(mode="json"))


def sign_document(document: dict, *, settings: Path = SETTINGS) -> dict:
    private = _private_key()
    expected = configured_public_key(settings).public_bytes(Encoding.Raw, PublicFormat.Raw)
    if public_hex(private) != expected.hex():
        raise ValueError("chave privada não corresponde à approval_public_key versionada")
    return document | {"signature": private.sign(canonical_document(document)).hex()}


def verify_document(document: dict, *, settings: Path = SETTINGS) -> None:
    signature = document.get("signature")
    if not signature:
        raise ValueError("documento não assinado")
    key = configured_public_key(settings)
    try:
        key.verify(bytes.fromhex(signature), canonical_document(document))
    except (InvalidSignature, ValueError, TypeError):
        raise ValueError("assinatura humana inválida") from None


def public_hex(private: Ed25519PrivateKey) -> str:
    return private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def configured_public_key(settings: Path = SETTINGS) -> Ed25519PublicKey:
    """Chave pública versionada; ausente → toda aprovação é recusada (fail-closed)."""
    try:
        data = yaml.safe_load(settings.read_text())
    except (OSError, yaml.YAMLError):
        data = None
    value = data.get("approval_public_key") if isinstance(data, dict) else None
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("approval_public_key ausente em config/settings.yaml")
    try:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(value))
    except ValueError:
        raise ValueError("approval_public_key inválida em config/settings.yaml") from None


def _private_key() -> Ed25519PrivateKey:
    location = os.environ.get("APPROVAL_PRIVATE_KEY_FILE")
    if not location:
        raise ValueError("APPROVAL_PRIVATE_KEY_FILE ausente; assinar só na máquina humana")
    path = Path(location).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("arquivo da chave privada humana ausente")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("chave privada com permissão aberta; use chmod 600")
    try:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(path.read_text().strip()))
    except ValueError:
        raise ValueError("arquivo da chave privada humana inválido") from None


def sign(approval: Approval, *, settings: Path = SETTINGS) -> Approval:
    """Primitiva do comando humano; não decide status nem concede aprovação."""
    return Approval.model_validate(
        sign_document(approval.model_dump(mode="json"), settings=settings)
    )


def verify(approval: Approval, *, settings: Path = SETTINGS) -> None:
    if not approval.signature:
        raise ValueError("aprovação sem assinatura humana")
    verify_document(approval.model_dump(mode="json"), settings=settings)


def keygen(destination: Path, repository: Path) -> str:
    """Gera a chave humana fora do repositório (0600) e devolve a chave pública em hex."""
    reject_links(destination.expanduser())
    destination = destination.expanduser().resolve()
    if destination.is_relative_to(repository.resolve()):
        raise ValueError("chave privada nunca pode ficar dentro do repositório")
    private_directory(destination.parent)
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes_raw().hex()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(raw + "\n")
    return public_hex(private)


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def read_document(path: Path) -> tuple[Approval, dict | None]:
    document = json.loads(path.read_text())
    if isinstance(document, dict) and set(document) == {"approval", "plan"}:
        approval = Approval.model_validate(document["approval"])
        plan = document["plan"]
        if approval.kind not in {
            "new_offer",
            "creative_set",
            "scale",
            "tracking_test",
            "gate_c_confirmation",
        } or not isinstance(plan, dict):
            raise ValueError("envelope de aprovação inválido")
        digest = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        if digest != approval.plan_hash or plan.get("kind") != approval.kind:
            raise ValueError("plano do envelope diverge da aprovação")
        return approval, plan
    return Approval.model_validate(document), None


def sign_file(source: Path, confirm, *, now: datetime | None = None) -> Path:
    if not is_interactive():
        raise ValueError("aprovação exige tty interativo na máquina humana")
    if source.parent.name != "pending" or source.is_symlink() or not source.is_file():
        raise ValueError("use um arquivo regular em pending/")
    approval, plan = read_document(source)
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
    private_directory(directory)
    destination = directory / source.name
    # Publicar sem sobrescrever; remover pending só após gravação completa.
    with private_open(destination, exclusive=True) as file:
        file.write(
            (
                json.dumps(
                    {"approval": signed.model_dump(mode="json"), "plan": plan},
                    ensure_ascii=False,
                    indent=2,
                )
                if plan is not None
                else signed.model_dump_json(indent=2)
            )
            + "\n"
        )
    source.unlink()
    return destination
