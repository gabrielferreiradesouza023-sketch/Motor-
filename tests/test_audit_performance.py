import json
import random
from datetime import UTC, datetime, timedelta
from time import perf_counter

from arb.db import Repository, connect, migrate, migration_catalog
from arb.launcher.scale import last_increase
from arb.ledger import pending
from arb.models import Action

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def reference_pending(actions):
    rows = []
    for a in actions:
        if a.result != "intent":
            continue
        outcomes = [r for r in actions if r.payload_json.get("attempt_id") == a.id]
        if any(r.result != "uncertain" for r in outcomes):
            continue
        rows.append(
            {
                "attempt_id": a.id,
                "entity_id": a.payload_json.get("entity_id"),
                "meta_id": a.payload_json.get("meta_id"),
                "kind": a.kind,
                "age_seconds": max(0, int((NOW - a.ts).total_seconds())),
                "state": "uncertain" if outcomes else "orphan",
            }
        )
    return sorted(rows, key=lambda r: r["attempt_id"])


def test_100k_equivalence_and_200ms_bound(tmp_path):
    conn = connect(tmp_path / "audit.db")
    migrate(conn)
    rng = random.Random(42)
    actions = []
    for i in range(100_000):
        kind, result, payload = "example", "simulated", {}
        if i < 30:
            kind, result, payload = "pause", "intent", {"entity_id": "entity", "meta_id": "123"}
        elif i < 50:
            kind, result, payload = (
                "pause_result",
                "uncertain" if i % 2 else "reconciled_paused",
                {"attempt_id": "audit-" + str(i - 30)},
            )
        elif i % 1000 == 0:
            kind, result, payload = (
                "scale",
                "intent" if i % 3000 == 0 else "applied",
                {"entity_id": "entity"},
            )
        elif i % 1000 == 1:
            kind, payload = "launch", {"input": {"entities": [{"id": "entity"}]}}
        actions.append(
            Action(
                id="audit-" + str(i),
                ts=NOW - timedelta(seconds=rng.randrange(100000)),
                actor="engine",
                kind=kind,
                result=result,
                payload_json=payload,
                live=False,
            )
        )
    with conn:
        conn.executemany(
            "INSERT INTO actions(id,payload) VALUES(?,?)",
            [(a.id, a.model_dump_json()) for a in actions],
        )
    expected = reference_pending(actions)
    expected_time = max(
        [datetime(1970, 1, 1, tzinfo=UTC)]
        + [
            a.ts
            for a in actions
            if (
                a.kind == "scale"
                and a.payload_json.get("entity_id") == "entity"
                and a.result != "intent"
            )
            or (
                a.kind == "launch"
                and any(
                    e["id"] == "entity" for e in a.payload_json.get("input", {}).get("entities", [])
                )
            )
        ]
    )
    timings = {}
    for name, call, reference in [
        ("pending", lambda: pending(conn, now=NOW), expected),
        ("last_increase", lambda: last_increase(conn, "entity"), expected_time),
    ]:
        start = perf_counter()
        actual = call()
        timings[name] = (perf_counter() - start) * 1000
        assert actual == reference
        assert timings[name] < 200
    print("100k audit timings ms:", json.dumps(timings, sort_keys=True))
    from arb.analyst.report import operational_status

    ops = operational_status(conn, now=NOW)
    assert ops["uncertain_results"] == sum(a.result == "uncertain" for a in actions)
    assert (
        ops["last_reconciliation"]
        == max(a.ts for a in actions if a.result.startswith("reconciled_")).isoformat()
    )
    conn.close()


def test_indexes_populate_existing_payloads(tmp_path):
    conn = connect(tmp_path / "old.db")
    conn.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,checksum TEXT NOT NULL)"
    )
    for number, (sql, sha) in migration_catalog().items():
        if number >= 8:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations VALUES(?,?)", (number, sha))
        conn.commit()
    action = Action(
        id="old-intent",
        ts=NOW,
        actor="engine",
        kind="pause",
        result="intent",
        live=False,
        payload_json={"entity_id": "entity"},
    )
    with conn:
        Repository(conn, Action).add(action)
    migrate(conn)
    assert pending(conn, now=NOW) == reference_pending([action])
    assert conn.execute("SELECT action_entity_id FROM actions").fetchone() == ("entity",)
    assert "actions_attempt_idx" in {r[1] for r in conn.execute("PRAGMA index_list(actions)")}
    conn.close()
