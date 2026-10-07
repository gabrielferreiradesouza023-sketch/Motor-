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
from arb.launcher.actions import intent_hash
from arb.launcher.approval import read_document
from arb.launcher.execute import store_approval
from arb.models import Action, SaleEvent
from arb.safety import require_external_write


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
            approval, _ = read_document(path)
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


def notification_hash(messages: list[str], destination: str = "injected") -> str:
    return intent_hash(
        {"kind": "notification", "messages": sorted(set(messages)), "destination": destination}
    )


@dataclass(repr=False)
class Telegram:
    """Adaptador explicitamente injetado. A CLI não habilita nem cria cliente real.

    Testes usam httpx.MockTransport. Operador futuro precisa autorizar envio real,
    fornecer configuração segura e verificar o chat de destino separadamente.
    """

    client: httpx.Client = field(repr=False)
    token: str = field(repr=False)
    chat_id: str = field(repr=False)
    approval_id: str | None = None
    approval_dir: Path = Path("ops/approvals/approved")

    @property
    def destination(self) -> str:
        return self.token.split(":", 1)[0] + "/" + self.chat_id

    def __post_init__(self):
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", self.token):
            raise ValueError("formato de token Telegram inválido")
        if not re.fullmatch(r"-?[0-9]+", self.chat_id):
            raise ValueError("chat Telegram inválido")

    def __call__(self, messages: list[str]) -> bool:
        require_external_write(
            "notification",
            self.approval_id,
            approval_dir=self.approval_dir,
            fingerprint=notification_hash(messages, self.destination),
        )
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
    approval_id: str | None = None,
    approval_dir: Path = Path("ops/approvals/approved"),
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
    authorization = None
    if send:
        approval_id = approval_id or getattr(sender, "approval_id", None)
        approval_dir = getattr(sender, "approval_dir", approval_dir)
        authorization = require_external_write(
            "notification",
            approval_id,
            approval_dir=approval_dir,
            fingerprint=notification_hash(messages, getattr(sender, "destination", "injected")),
            now=now,
        ).approval
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = Repository(connection, Action).get(action_id)
        if existing:
            connection.rollback()
            final = Repository(connection, Action).get(action_id + "-result")
            return {"status": final.result if final else existing.result, "count": len(messages)}
        if authorization:
            store_approval(connection, authorization)
        attempt = Action(
            id=action_id,
            ts=now,
            actor="engine",
            kind="notification",
            payload_json={"cycle_id": cycle_id, "messages": messages},
            live=send,
            approval_id=approval_id if send else None,
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
                approval_id=approval_id,
                result=result,
            )
        )
    return {"status": result, "count": len(messages)}


CRITICAL = frozenset({"daily_cap", "emergency", "checkpoint", "project_cap", "stale", "unknown"})


def uncertain(connection) -> list[dict]:
    """Só códigos; não reproduzir mensagens/payloads potencialmente sensíveis."""
    rows = []
    for (payload,) in connection.execute(
        "SELECT payload FROM actions WHERE action_kind IN ('notification','notify_hook') "
        "AND action_result='uncertain' ORDER BY id"
    ):
        attempt = Action.model_validate_json(payload)
        results = connection.execute(
            "SELECT action_result FROM actions WHERE action_attempt_id=?", (attempt.id,)
        ).fetchall()
        if any(row[0] in {"sent", "completed"} for row in results):
            continue
        ack = Repository(connection, Action).get("alert-ack-" + attempt.id)
        if (
            ack is not None
            and ack.actor == "human"
            and ack.kind == "alert_ack"
            and ack.payload_json == {"alert_id": attempt.id}
            and ack.result == "acknowledged"
        ):
            continue
        messages = attempt.payload_json.get("messages")
        if attempt.kind == "notify_hook":
            cycle = connection.execute(
                "SELECT payload FROM scheduler_runs WHERE id=?",
                (attempt.payload_json.get("cycle_id"),),
            ).fetchone()
            messages = json.loads(cycle[0]).get("alerts") if cycle else None
        if not isinstance(messages, list) or not messages:
            codes = ["unknown"]
        else:
            allowed = CRITICAL | {
                "approval_pending",
                "approval_invalid",
                "unmatched_sales",
                "notification_failed",
                "remote_pause_pending",
                "pause_failed",
                "sync_failed",
                "missed_cycle",
            }
            codes = sorted(
                {
                    m.split(":", 1)[0]
                    if isinstance(m, str) and m.split(":", 1)[0] in allowed
                    else "unknown"
                    for m in messages
                }
            )
        rows.append(
            {
                "id": attempt.id,
                "kind": attempt.kind,
                "codes": codes,
                "critical": bool(CRITICAL & set(codes)),
            }
        )
    return rows


def acknowledge(connection, alert_id, *, now=None):
    from arb.launcher.approval import is_interactive

    if not is_interactive():
        raise ValueError("ack exige tty humano")
    if connection.in_transaction:
        raise ValueError("ack exige commit anterior")
    connection.execute("BEGIN IMMEDIATE")
    try:
        identity = "alert-ack-" + alert_id
        existing = Repository(connection, Action).get(identity)
        if existing:
            if (
                existing.actor != "human"
                or existing.kind != "alert_ack"
                or existing.payload_json != {"alert_id": alert_id}
                or existing.result != "acknowledged"
            ):
                raise ValueError("id de ack em conflito")
            connection.rollback()
            return existing
        if not any(row["id"] == alert_id for row in uncertain(connection)):
            raise ValueError("alerta incerto não encontrado")
        action = Action(
            id=identity,
            ts=now or datetime.now(UTC),
            actor="human",
            kind="alert_ack",
            payload_json={"alert_id": alert_id},
            live=False,
            result="acknowledged",
        )
        Repository(connection, Action).add(action)
        connection.commit()
        return action
    except BaseException:
        connection.rollback()
        raise
