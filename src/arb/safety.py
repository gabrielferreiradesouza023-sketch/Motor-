"""Guarda única: simulação por padrão, pausa autônoma, demais efeitos assinados."""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from arb.models import Approval

KINDS = frozenset(
    {"pause", "launch", "activate", "scale", "new_offer", "notification", "tracking_test"}
)
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WriteIntent:
    kind: str
    live: bool
    approval: Approval | None = None


def live_mode() -> bool:
    value = os.environ.get("LIVE_MODE", "false").lower()
    if value not in {"false", "true"}:
        raise ValueError("LIVE_MODE inválido: use false ou true")
    return value == "true"


def require_external_write(
    kind: str,
    approval_id: str | None = None,
    *,
    fingerprint: str | None = None,
    exposure: int = 0,
    approval_dir: Path = Path("ops/approvals/approved"),
    now: datetime | None = None,
    simulation: bool = False,
) -> WriteIntent:
    if kind not in KINDS:
        raise ValueError("tipo de escrita proibido; nunca delete")
    live = live_mode()
    approval = None
    if simulation:
        if live:
            raise ValueError("operação local exige LIVE_MODE=false; escrita live não implementada")
    elif not live:
        raise ValueError("escrita externa recusada: LIVE_MODE=false")
    elif kind != "pause":
        if not approval_id or not fingerprint:
            raise ValueError("escrita externa exige aprovação assinada da intenção exata")
        from arb.launcher.execute import approved_file

        approval = approved_file(
            approval_id,
            kind=kind,
            fingerprint=fingerprint,
            exposure=exposure,
            directory=approval_dir,
            now=now or datetime.now(UTC),
        )
    # Nunca registrar chave, credenciais ou corpo HTTP. Caller persiste Action antes do HTTP.
    LOGGER.info("write_intent kind=%s live=%s approval_id=%s", kind, live, approval_id)
    return WriteIntent(kind, live, approval)
