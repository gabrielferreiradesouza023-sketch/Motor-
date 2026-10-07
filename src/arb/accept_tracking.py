"""Evento sintético assinado; CSV e sincronização em cópia descartável, nunca P&L real."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from arb import safety
from arb.accept import evidence, require_host, suffix
from arb.db import Repository, connect
from arb.launcher.approval import read_document
from arb.launcher.execute import store_approval
from arb.ledger import pending
from arb.models import Action, Approval, BridgeEvent, Entity, SaleEvent
from arb.permissions import private_open, reject_links
from arb.quarantine import require_released
from arb.tracker import entity_map, import_sales
from arb.tracker.sync import sync


def digest(body):
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def endpoint(value):
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError("URL HTTPS de base/origem sem credencial obrigatória")
    return value.rstrip("/")


def propose(
    connection,
    entity_id,
    worker_url,
    origin,
    *,
    tracking_id=None,
    directory=Path("ops/approvals/pending"),
    now=None,
):
    if safety.live_mode():
        raise ValueError("proposta local exige LIVE_MODE=false")
    entity = Repository(connection, Entity).get(entity_id)
    if entity is None or entity.kind != "ad":
        raise ValueError("anúncio local conhecido obrigatório")
    identifier = tracking_id or entity.meta_id or entity.id
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", identifier):
        raise ValueError("id não atende protocolo próprio do Worker")
    if entity_map(connection).get(identifier) != entity_id:
        raise ValueError("rastreio não casa com entidade")
    now = now or datetime.now(UTC)
    event = BridgeEvent(
        id="accept-" + uuid4().hex, kind="view", ad_id=identifier, geo=entity.geo, ts=now
    ).model_dump(mode="json") | {"test": True}
    body = {
        "kind": "tracking_test",
        "url": endpoint(worker_url),
        "origin": endpoint(origin),
        "entity_id": entity.id,
        "event": event,
    }
    approval = Approval(
        id="tracking-" + uuid4().hex,
        kind="tracking_test",
        plan_hash=digest(body),
        summary="Enviar UM evento sintético de rastreio ao Worker indicado; sem gasto",
        max_exposure_cents=0,
        status="pending",
    )
    path = directory / (approval.id + ".json")
    with private_open(path, exclusive=True) as file:
        json.dump(
            {"approval": approval.model_dump(mode="json"), "plan": body},
            file,
            ensure_ascii=False,
            indent=2,
        )
    return path


def financial_fingerprint(connection):
    return digest(
        {
            table: connection.execute(f"SELECT payload FROM {table} ORDER BY payload").fetchall()
            for table in ("metric_snapshots", "metric_adjustments", "sale_events")
        }
    )


def tracking(
    connection,
    worker_url,
    token,
    approval_id,
    *,
    approval_dir=Path("ops/approvals/approved"),
    client=None,
    now=None,
):
    require_host()
    require_released(connection)
    if connection.in_transaction or pending(connection):
        raise ValueError("commit/reconciliação anterior obrigatório")
    # Verificação de id antes de construir caminho de arquivo.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", approval_id):
        raise ValueError("id de aprovação inválido")
    path = approval_dir / (approval_id + ".json")
    reject_links(path)
    approval, plan = read_document(path)
    now = now or datetime.now(UTC)
    if (
        not token
        or plan is None
        or set(plan) != {"kind", "url", "origin", "entity_id", "event"}
        or plan["url"] != endpoint(worker_url)
        or plan["origin"] != endpoint(plan["origin"])
        or plan["kind"] != "tracking_test"
        or plan["event"].get("test") is not True
    ):
        raise ValueError("plano/token do aceite inválido")
    event = BridgeEvent.model_validate({k: v for k, v in plan["event"].items() if k != "test"})
    entity = Repository(connection, Entity).get(plan["entity_id"])
    if (
        not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", event.ad_id)
        or entity is None
        or entity.kind != "ad"
        or event.geo != entity.geo
        or event.kind != "view"
        or entity_map(connection).get(event.ad_id) != entity.id
    ):
        raise ValueError("evento não casa com anúncio aprovado")
    safety.require_external_write(
        "tracking_test", approval_id, fingerprint=digest(plan), approval_dir=approval_dir, now=now
    )
    attempt = "accept-tracking-" + approval_id
    actions = Repository(connection, Action)
    if actions.get(attempt) is not None:
        raise ValueError(
            "aceite já tentado; não reenviar, consultar ledger e export no host humano"
        )
    before = financial_fingerprint(connection)
    with connection:
        store_approval(connection, approval)
        actions.add(
            Action(
                id=attempt,
                ts=now,
                actor="human",
                kind="tracking_test",
                live=True,
                approval_id=approval_id,
                result="intent",
                payload_json={"entity_id": entity.id, "event_id": event.id},
            )
        )
    checks = [
        {"name": name, "ok": False}
        for name in ("event_ack", "test_receipt", "csv_matched", "production_unchanged")
    ]
    owned = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=False)
    try:
        response = client.post(
            plan["url"] + "/event",
            json=plan["event"],
            headers={"Origin": plan["origin"]},
            follow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code != 202 or response.json() != {"status": "accepted"}:
            raise ValueError("evento não confirmado")
        checks[0]["ok"] = True
        with TemporaryDirectory(prefix="arb-tracking-accept-") as directory:
            scratch = connect(Path(directory) / "scratch.db")
            try:
                connection.backup(scratch)
                sync(scratch, plan["url"], token, client=client)
                receipt = scratch.execute(
                    "SELECT payload,applied FROM tracker_receipts WHERE source=? AND id=?",
                    (plan["url"], event.id),
                ).fetchone()
                if receipt is None or json.loads(receipt[0]) != plan["event"] or receipt[1] != 1:
                    raise ValueError("recibo sintético ausente/divergente")
                checks[1]["ok"] = True
                csv = Path(directory) / "test-sale.csv"
                transaction = "acceptance-" + event.id
                with private_open(csv) as file:
                    file.write(
                        "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
                        + f"{transaction},{event.ts.isoformat()},1,approved,{event.ad_id}\n"
                    )
                import_sales(scratch, csv)
                sale = next(
                    s
                    for s in Repository(scratch, SaleEvent).list()
                    if s.hotmart_tx_id == transaction
                )
                if sale.matched_entity_id != entity.id:
                    raise ValueError("venda sintética não casou")
                checks[2]["ok"] = True
            finally:
                scratch.close()
        if financial_fingerprint(connection) != before:
            raise ValueError("dados financeiros locais alterados durante aceite")
        checks[3]["ok"] = True
    except Exception:
        pass  # Evidência fixa e redigida; nunca propagar corpo, URL ou token.
    finally:
        if owned:
            client.close()
    result = evidence("tracking", checks, now=now, ad_suffix=suffix(event.ad_id), synthetic=True)
    with connection:
        actions.add(
            Action(
                id=attempt + "-result",
                ts=now,
                actor="human",
                kind="tracking_test_result",
                live=True,
                approval_id=approval_id,
                payload_json={"attempt_id": attempt},
                result="confirmed" if result["status"] == "passed" else "uncertain",
            )
        )
    return result
