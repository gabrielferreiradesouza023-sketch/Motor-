"""Alertas opcionais. Sem envio por padrão; credenciais nunca entram em payload/auditoria."""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from arb.db import Repository
from arb.models import Action, Approval, SaleEvent


def collect(
    connection: sqlite3.Connection,
    control_messages: list[str],
    *,
    approval_dir: Path = Path("ops/approvals/pending"),
) -> list[str]:
    messages = list(control_messages)
    pending, invalid = 0, 0
    for path in approval_dir.glob("*.json"):
        try:
            approval = Approval.model_validate_json(path.read_text())
            pending += approval.status == "pending"
        except (OSError, ValueError):
            invalid += 1
    if pending:
        messages.append(f"approval_pending: {pending} propostas aguardando revisão humana")
    if invalid:
        messages.append(f"approval_invalid: {invalid} arquivos exigem revisão")
    unmatched = sum(
        s.status == "approved" and s.matched_entity_id is None
        for s in Repository(connection, SaleEvent).list()
    )
    if unmatched:
        messages.append(f"unmatched_sales: {unmatched} vendas aprovadas sem casamento")
    return sorted(set(messages))


@dataclass(repr=False)
class Telegram:
    """Adaptador explicitamente injetado. A CLI não habilita nem cria cliente real.

    Testes usam httpx.MockTransport. Operador futuro precisa autorizar envio real,
    fornecer configuração segura e verificar o chat de destino separadamente.
    """

    client: httpx.Client = field(repr=False)
    token: str = field(repr=False)
    chat_id: str = field(repr=False)

    def __post_init__(self):
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", self.token):
            raise ValueError("formato de token Telegram inválido")
        if not re.fullmatch(r"-?[0-9]+", self.chat_id):
            raise ValueError("chat Telegram inválido")

    def __call__(self, messages: list[str]) -> bool:
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": "arb-engine\n" + "\n".join(messages)[:3500],
                    "disable_web_page_preview": True,
                },
                follow_redirects=False,
                timeout=10,
            )
            # Não seguir redirects e não propagar corpo/URL de erro que contém token.
            return response.status_code == 200 and response.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False


def dispatch(
    connection: sqlite3.Connection,
    cycle_id: str,
    messages: list[str],
    *,
    sender: Callable[[list[str]], bool] | None = None,
    send: bool = False,
    now: datetime | None = None,
) -> dict:
    if connection.in_transaction:
        raise ValueError("alerta requer commit anterior")
    if not messages:
        return {"status": "empty", "count": 0}
    if send and sender is None:
        raise ValueError("envio exige adaptador explícito")
    messages = sorted(set(messages))
    identity = hashlib.sha256(json.dumps([cycle_id, messages], sort_keys=True).encode()).hexdigest()
    action_id = "notification-" + identity
    now = now or datetime.now(UTC)
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = Repository(connection, Action).get(action_id)
        if existing:
            connection.rollback()
            final = Repository(connection, Action).get(action_id + "-result")
            return {"status": final.result if final else existing.result, "count": len(messages)}
        attempt = Action(
            id=action_id,
            ts=now,
            actor="engine",
            kind="notification",
            payload_json={"cycle_id": cycle_id, "messages": messages},
            live=send,
            result="uncertain" if send else "disabled",
        )
        Repository(connection, Action).add(attempt)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    if not send:
        return {"status": "disabled", "count": len(messages)}
    try:
        ok = sender(messages)
    except Exception:
        ok = False
    # Falha/timeout pode significar entrega sem ACK; não reenviar automaticamente.
    result = "sent" if ok else "uncertain"
    with connection:
        Repository(connection, Action).add(
            Action(
                id=action_id + "-result",
                ts=now,
                actor="engine",
                kind="notification_result",
                payload_json={"attempt_id": action_id, "count": len(messages)},
                live=True,
                result=result,
            )
        )
    return {"status": result, "count": len(messages)}
