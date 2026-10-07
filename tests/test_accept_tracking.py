import json
from datetime import UTC, datetime

import httpx
import pytest
from typer.testing import CliRunner

import arb.accept_tracking as kit
from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.launcher.approval import read_document, sign
from arb.ledger import pending
from arb.models import Action, Entity, MetricSnapshot, SaleEvent
from arb.tracker.sync import sync

NOW = datetime(2026, 10, 7, tzinfo=UTC)
URL = "https://worker.example"
ORIGIN = "https://bridge.example"


@pytest.fixture
def seeded(tmp_path, records):
    conn = connect(tmp_path / "db.sqlite")
    migrate(conn)
    with conn:
        for record in records[:4]:
            if isinstance(record, Entity):
                record = record.model_copy(update={"meta_id": "123456789"})
            Repository(conn, type(record)).add(record)
        conn.execute("INSERT INTO tracking_ids VALUES ('short','entity')")
    yield conn, tmp_path
    conn.close()


def approved(seeded, alias="123456789", change=None):
    conn, tmp = seeded
    path = kit.propose(
        conn, "entity", URL, ORIGIN, tracking_id=alias, directory=tmp / "pending", now=NOW
    )
    approval, plan = read_document(path)
    if change:
        change(plan)
        approval.plan_hash = kit.digest(plan)
    approval.status = "approved"
    approval.decided_at = NOW
    approval = sign(approval)
    directory = tmp / "approved"
    directory.mkdir(exist_ok=True)
    (directory / path.name).write_text(
        json.dumps({"approval": approval.model_dump(mode="json"), "plan": plan})
    )
    return approval, plan, directory


def transport(conn, fault=None):
    calls, posted = [], []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert pending(conn) and not conn.in_transaction
            assert request.headers["Origin"] == ORIGIN
            body = json.loads(request.content)
            assert body["test"] is True
            posted.append(body)
            if fault == "post_network":
                raise httpx.ReadTimeout("synthetic-hidden")
            return httpx.Response(
                403 if fault == "origin" else 202,
                json={"status": "wrong" if fault == "bad_ack" else "accepted"},
            )
        assert request.method == "GET" and request.url.path == "/export"
        assert request.headers["Authorization"] == "Bearer synthetic-hidden"
        if fault == "auth":
            return httpx.Response(401, json={"error": "synthetic-hidden"})
        if fault == "network":
            raise httpx.ReadTimeout("synthetic-hidden")
        event = dict(posted[0])
        if fault == "lost_flag":
            event.pop("test")
        if fault == "divergent":
            event["geo"] = "MX"
        return httpx.Response(
            200,
            json={
                "events": [] if fault == "missing" else [event | {"cursor": 1}],
                "sales": [],
                "more": False,
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), calls, posted


@pytest.mark.parametrize("alias", ["123456789", "short"])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "auth",
        "network",
        "missing",
        "lost_flag",
        "divergent",
        "post_network",
        "origin",
        "bad_ack",
        "csv_match",
    ],
)
def test_tracking_matrix_isolated_finances(seeded, monkeypatch, alias, fault):
    conn, _ = seeded
    approval, plan, directory = approved(seeded, alias)
    baseline = kit.financial_fingerprint(conn)
    client, calls, posted = transport(conn, fault)
    if fault == "csv_match":
        monkeypatch.setattr(kit, "import_sales", lambda *_: None)
    monkeypatch.setenv("LIVE_MODE", "true")
    with client:
        result = kit.tracking(
            conn,
            URL,
            "synthetic-hidden",
            approval.id,
            approval_dir=directory,
            client=client,
            now=NOW,
        )
        assert result["status"] == ("failed" if fault else "passed")
        assert bool(pending(conn)) == bool(fault)
        assert posted == [plan["event"]]
        assert len([r for r in calls if r.method == "POST"]) == 1
        assert kit.financial_fingerprint(conn) == baseline
        assert not Repository(conn, SaleEvent).list()
        assert not Repository(conn, MetricSnapshot).list()
        raw = json.dumps(result)
        assert "synthetic-hidden" not in raw and "123456789" not in raw and "short" not in raw
        if fault is None:
            with pytest.raises(ValueError, match="já tentado"):
                kit.tracking(
                    conn,
                    URL,
                    "synthetic-hidden",
                    approval.id,
                    approval_dir=directory,
                    client=client,
                    now=NOW,
                )
            # Later normal production sync must retain the test receipt but not metrics.
            assert sync(conn, URL, "synthetic-hidden", client=client) == {"events": 0, "sales": 0}
            assert not Repository(conn, MetricSnapshot).list()
            receipt = conn.execute("SELECT payload,applied FROM tracker_receipts").fetchone()
            assert json.loads(receipt[0])["test"] is True and receipt[1] == 1


@pytest.mark.parametrize(
    "violation",
    [
        "false",
        "missing_token",
        "bad_id",
        "url",
        "plan_keys",
        "flag",
        "entity",
        "geo",
        "kind",
        "tracking",
        "hash",
        "signature",
        "quarantine",
        "transaction",
        "pending",
        "symlink",
    ],
)
def test_refusals_no_post(seeded, monkeypatch, violation):
    conn, tmp = seeded
    changes = {
        "plan_keys": lambda p: p.update(extra=True),
        "flag": lambda p: p["event"].update(test=False),
        "entity": lambda p: p.update(entity_id="missing"),
        "geo": lambda p: p["event"].update(geo="MX"),
        "kind": lambda p: p["event"].update(kind="checkout_click"),
        "tracking": lambda p: p["event"].update(ad_id="missing"),
    }
    approval, _, directory = approved(seeded, change=changes.get(violation))
    client, calls, _ = transport(conn)
    monkeypatch.setenv("LIVE_MODE", "true")
    token, identifier, url = "synthetic-hidden", approval.id, URL
    if violation == "false":
        monkeypatch.setenv("LIVE_MODE", "false")
    elif violation == "missing_token":
        token = ""
    elif violation == "bad_id":
        identifier = "../bad"
    elif violation == "url":
        url = "https://other.example"
    elif violation in {"hash", "signature"}:
        file = directory / (approval.id + ".json")
        doc = json.loads(file.read_text())
        doc["approval"]["plan_hash" if violation == "hash" else "signature"] = "0" * (
            64 if violation == "hash" else 128
        )
        file.write_text(json.dumps(doc))
    elif violation == "quarantine":
        with conn:
            conn.execute(
                "INSERT INTO restore_quarantine VALUES ('q','backup',?, ?,NULL)",
                ("0" * 64, NOW.isoformat()),
            )
    elif violation == "transaction":
        conn.execute("BEGIN")
    elif violation == "pending":
        with conn:
            Repository(conn, Action).add(
                Action(
                    id="orphan",
                    ts=NOW,
                    actor="human",
                    kind="pause",
                    live=True,
                    result="intent",
                    payload_json={},
                )
            )
    elif violation == "symlink":
        link = tmp / "approved-link"
        link.symlink_to(directory, target_is_directory=True)
        directory = link
    with client, pytest.raises(ValueError):
        kit.tracking(conn, url, token, identifier, approval_dir=directory, client=client, now=NOW)
    assert not calls
    conn.rollback()


@pytest.mark.parametrize(
    "violation", ["live", "unknown", "parent", "alias", "url", "origin", "unsafe_id"]
)
def test_proposal_refusals(seeded, monkeypatch, violation):
    conn, tmp = seeded
    entity_id, url, origin, alias = "entity", URL, ORIGIN, None
    if violation == "live":
        # No request is made; still bound to a MockTransport context as required.
        monkeypatch.setenv("LIVE_MODE", "true")
    elif violation == "unknown":
        entity_id = "missing"
    elif violation == "parent":
        with conn:
            entity = Repository(conn, Entity).get("entity")
            entity.kind = "campaign"
            Repository(conn, Entity).update(entity)
    elif violation == "alias":
        alias = "unknown"
    elif violation == "url":
        url = "http://worker.example"
    elif violation == "origin":
        origin = "https://name@bridge.example"
    elif violation == "unsafe_id":
        alias = "bad,csv"
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
        pytest.raises(ValueError),
    ):
        kit.propose(conn, entity_id, url, origin, tracking_id=alias, directory=tmp / "pending")
    assert not (tmp / "pending").exists()


def test_owned_mock_client_closed_and_cli_false(seeded, monkeypatch):
    conn, tmp = seeded
    approval, _, directory = approved(seeded)
    client, _, _ = transport(conn)
    monkeypatch.setattr(kit.httpx, "Client", lambda **_: client)
    monkeypatch.setenv("LIVE_MODE", "true")
    assert (
        kit.tracking(conn, URL, "synthetic-hidden", approval.id, approval_dir=directory, now=NOW)[
            "status"
        ]
        == "passed"
    )
    assert client.is_closed
    monkeypatch.setenv("LIVE_MODE", "false")
    result = CliRunner().invoke(
        app,
        [
            "accept",
            "tracking",
            "--url",
            URL,
            "--approval-id",
            approval.id,
            "--out",
            str(tmp / "proof.json"),
        ],
    )
    assert result.exit_code == 1 and not (tmp / "proof.json").exists()


@pytest.mark.parametrize("marker", [False, None, 1, "true"])
def test_invalid_marker_rolls_back_export(seeded, marker):
    conn, _ = seeded

    def handler(_):
        return httpx.Response(
            200,
            json={
                "events": [
                    {
                        "cursor": 1,
                        "id": "bad-marker",
                        "kind": "view",
                        "ad_id": "entity",
                        "geo": "CO",
                        "ts": NOW.isoformat(),
                        "test": marker,
                    }
                ],
                "sales": [],
                "more": False,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(ValueError):
        sync(conn, URL, "synthetic-hidden", client=client)
    assert conn.execute("SELECT COUNT(*) FROM tracker_receipts").fetchone()[0] == 0
    assert not Repository(conn, MetricSnapshot).list()


@pytest.mark.parametrize("violation", ["wrong_csv_entity", "production_changed"])
def test_planted_financial_violations_fail_proof(seeded, records, monkeypatch, violation):
    conn, _ = seeded
    approval, _, directory = approved(seeded)
    baseline = kit.financial_fingerprint(conn)
    client, _, _ = transport(conn)
    original_import = kit.import_sales

    def corrupt(scratch, path):
        original_import(scratch, path)
        if violation == "wrong_csv_entity":
            sale = Repository(scratch, SaleEvent).list()[0]
            with scratch:
                Repository(scratch, SaleEvent).update(
                    sale.model_copy(update={"matched_entity_id": None})
                )
        else:
            # Another actor changes production during the drill: must not claim unchanged.
            with conn:
                Repository(conn, MetricSnapshot).add(records[4])

    monkeypatch.setattr(kit, "import_sales", corrupt)
    monkeypatch.setenv("LIVE_MODE", "true")
    with client:
        result = kit.tracking(
            conn,
            URL,
            "synthetic-hidden",
            approval.id,
            approval_dir=directory,
            client=client,
            now=NOW,
        )
    failed = "csv_matched" if violation == "wrong_csv_entity" else "production_unchanged"
    assert result["status"] == "failed" and pending(conn)
    assert not next(c for c in result["checks"] if c["name"] == failed)["ok"]
    assert (kit.financial_fingerprint(conn) == baseline) == (violation == "wrong_csv_entity")
