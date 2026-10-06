"""Execução exclusivamente local. Arquivo humano aprovado é obrigatório até no dry-run."""

import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from arb.db import Repository
from arb.launcher import plan_hash, serialize, validate_plan
from arb.models import Action, Angle, Approval, Creative, Entity, LaunchPlan, Offer


def require_simulation() -> None:
    if os.environ.get("LIVE_MODE", "false").lower() != "false":
        raise ValueError("escrita live não implementada/permitida; LIVE_MODE precisa ser false")


def approved_file(
    approval_id: str, *, kind: str, fingerprint: str, exposure: int, directory: Path, now: datetime
) -> Approval:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", approval_id):
        raise ValueError("id de aprovação inválido")
    path = directory / f"{approval_id}.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("arquivo de aprovação humana ausente")
    approval = Approval.model_validate_json(path.read_text())
    if (
        approval.id != approval_id
        or approval.kind != kind
        or approval.status != "approved"
        or approval.plan_hash != fingerprint
        or approval.max_exposure_cents < exposure
        or approval.decided_at is None
        or approval.decided_at > now
    ):
        raise ValueError("aprovação inválida: tipo, hash, exposição, status ou data")
    return approval


def store_approval(connection: sqlite3.Connection, approval: Approval) -> None:
    repo = Repository(connection, Approval)
    existing = repo.get(approval.id)
    if existing is None:
        repo.add(approval)
    elif existing == approval:
        return
    elif (
        existing.status == "pending"
        and existing.decided_at is None
        and existing.model_copy(update={"status": "approved", "decided_at": approval.decided_at})
        == approval
    ):
        repo.update(approval)
    else:
        raise ValueError("aprovação armazenada divergente")


def execute(
    connection: sqlite3.Connection,
    value: LaunchPlan,
    approval_id: str,
    *,
    approval_dir: Path = Path("ops/approvals/approved"),
    output: Path = Path("ops/dry_runs"),
    now: datetime | None = None,
) -> Action:
    require_simulation()
    validate_plan(value)
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("timestamp precisa de fuso horário")
    fingerprint = plan_hash(value)
    approval = approved_file(
        approval_id,
        kind="launch",
        fingerprint=fingerprint,
        exposure=value.daily_budget_cents,
        directory=approval_dir,
        now=now,
    )
    if connection.in_transaction:
        raise ValueError("execute requer conexão sem transação pendente")
    connection.execute("BEGIN IMMEDIATE")
    try:
        for model, records in (
            (Offer, [value.offer]),
            (Angle, value.angles),
            (Creative, value.creatives),
        ):
            for record in records:
                if Repository(connection, model).get(record.id) != record:
                    raise ValueError("entradas do plano divergem do banco; regenere aprovação")
        existing = Repository(connection, Action).get("launch-" + fingerprint)
        if existing:
            connection.rollback()
            return existing
        store_approval(connection, approval)
        for entity in value.entities:
            Repository(connection, Entity).add(entity)
        action = Action(
            id="launch-" + fingerprint,
            ts=now,
            actor="engine",
            kind="launch",
            payload_json={
                "plan_hash": fingerprint,
                "input": value.model_dump(mode="json"),
                "output": {"entities": len(value.entities), "status": "paused"},
            },
            approval_id=approval.id,
            live=False,
            result="simulated",
        )
        output.mkdir(parents=True, exist_ok=True)
        # Arquivo completo publicado atomicamente; é proposta simulada, não prova de chamada Meta.
        with NamedTemporaryFile(mode="w", dir=output, delete=False, encoding="utf-8") as file:
            temporary = Path(file.name)
            file.write(serialize(value) + "\n")
        try:
            temporary.replace(output / f"{fingerprint}.json")
        finally:
            temporary.unlink(missing_ok=True)
        Repository(connection, Action).add(action)
        connection.commit()
        return action
    except Exception:
        connection.rollback()
        raise
