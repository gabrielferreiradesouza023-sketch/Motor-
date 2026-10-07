from datetime import date

import pytest
from test_scheduler import ROOT, seeded

from arb.db import Repository
from arb.models import Action, Decision, Entity
from arb.scheduler import run_cycle, schedule


@pytest.mark.parametrize(
    "boundary", ["sync", "decision", "pause", "report", "dispatch", "notify", "checkpoint"]
)
@pytest.mark.parametrize("side", ["before", "after"])
def test_local_crash_matches_clean_reference(tmp_path, records, monkeypatch, boundary, side):
    import arb.scheduler as module
    import arb.scheduler.alerts as alerts

    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    reference = seeded(tmp_path / "reference", records)
    run_cycle(reference, slot, now=slot, root=ROOT, output=tmp_path / "ref-report")
    expected = [a.kind for a in Repository(reference, Action).list()]
    conn = seeded(tmp_path / "interrupted", records)
    delivered = []
    crashed = []

    def cut(fn):
        def wrapped(*args, **kwargs):
            if not crashed and side == "before":
                crashed.append(True)
                raise KeyboardInterrupt("planted before")
            result = fn(*args, **kwargs)
            if not crashed and side == "after":
                crashed.append(True)
                raise KeyboardInterrupt("planted after")
            return result

        return wrapped

    def source(c, n):
        return None

    reporter = module.generate_report

    def notify(messages):
        delivered.append(list(messages))

    if boundary == "sync":
        source = cut(source)
    elif boundary == "report":
        reporter = cut(reporter)
    elif boundary == "notify":
        notify = cut(notify)
    elif boundary == "pause":
        monkeypatch.setattr(module, "pause", cut(module.pause))
    elif boundary == "dispatch":
        monkeypatch.setattr(alerts, "dispatch", cut(alerts.dispatch))
    elif boundary == "decision":
        original = Repository.add
        wrapped = cut(original)

        def add(repo, record):
            return wrapped(repo, record) if isinstance(record, Decision) else original(repo, record)

        monkeypatch.setattr(Repository, "add", add)
    else:
        original = conn

        class Connection:
            def __getattr__(self, name):
                return getattr(original, name)

            def __enter__(self):
                original.__enter__()
                return self

            def __exit__(self, *args):
                return original.__exit__(*args)

            def execute(self, sql, parameters=()):
                if sql.startswith("INSERT INTO scheduler_runs") and parameters[2] == "complete":
                    return cut(original.execute)(sql, parameters)
                return original.execute(sql, parameters)

        conn = Connection()
    with pytest.raises(KeyboardInterrupt):
        run_cycle(
            conn,
            slot,
            now=slot,
            root=ROOT,
            output=tmp_path / "report",
            sync_source=source,
            report_fn=reporter,
            notify=notify,
        )
    result = run_cycle(
        conn,
        slot,
        now=slot,
        root=ROOT,
        output=tmp_path / "report",
        sync_source=source,
        report_fn=reporter,
        notify=notify,
    )
    assert result["stages"] == ["sync", "rules", "actions", "report", "alerts"]
    assert conn.execute("SELECT status FROM scheduler_runs").fetchone()[0] == "complete"
    assert Repository(conn, Entity).get("entity").status == "paused"
    actual = [
        a.kind
        for a in Repository(conn, Action).list()
        if a.kind not in {"notify_hook", "notify_hook_result"}
    ]
    assert sorted(actual) == sorted(expected)
    assert len(Repository(conn, Decision).list()) == len(Repository(reference, Decision).list())
    assert {p.name for p in (tmp_path / "report").glob("*.html")} == {
        p.name for p in (tmp_path / "ref-report").glob("*.html")
    }
    assert len(delivered) <= 1
    conn.close()
    reference.close()


@pytest.mark.parametrize("boundary", ["http-before", "http-after", "pause-before", "pause-after"])
def test_remote_crash_reconcile_before_retry(tmp_path, records, monkeypatch, boundary):
    import httpx

    import arb.scheduler as module
    from arb.ledger import pending
    from arb.meta.pause import PauseWriter
    from arb.meta.read import Reader
    from arb.reconcile import reconcile

    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    with conn:
        entity = Repository(conn, Entity).get("entity")
        entity.meta_id = "123"
        Repository(conn, Entity).update(entity)
    state = {"status": "ACTIVE", "effects": 0, "posts": 0, "crashed": False}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "123", "status": state["status"]}]})
        assert pending(conn), "effect without durable intent"
        state["posts"] += 1
        if boundary == "http-before" and not state["crashed"]:
            state["crashed"] = True
            raise SystemExit("before effect")
        if state["status"] != "PAUSED":
            state["status"] = "PAUSED"
            state["effects"] += 1
        if boundary == "http-after" and not state["crashed"]:
            state["crashed"] = True
            raise SystemExit("after effect")
        return httpx.Response(200, json={"success": True})

    original = module.pause

    def pause(*args, **kwargs):
        if boundary == "pause-before" and not state["crashed"]:
            state["crashed"] = True
            raise SystemExit("before pause")
        result = original(*args, **kwargs)
        if boundary == "pause-after" and not state["crashed"]:
            state["crashed"] = True
            raise SystemExit("after pause")
        return result

    monkeypatch.setattr(module, "pause", pause)
    monkeypatch.setenv("LIVE_MODE", "true")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        writer = PauseWriter("synthetic", "v99.0", client)
        with pytest.raises(SystemExit):
            run_cycle(conn, slot, now=slot, root=ROOT, output=tmp_path / "out", writer=writer)
        assert conn.execute("SELECT status FROM scheduler_runs").fetchone()[0] == "failed"
        reconcile(conn, Reader("synthetic", "123", "v99.0", client=client), now=slot)
        result = run_cycle(conn, slot, now=slot, root=ROOT, output=tmp_path / "out", writer=writer)
        assert result["stages"][-1] == "alerts"
        assert state["status"] == "PAUSED" and state["effects"] == 1
        assert not pending(conn)
        assert Repository(conn, Entity).get("entity").status == "paused"
        posts = state["posts"]
        run_cycle(conn, slot, now=slot, root=ROOT, output=tmp_path / "out", writer=writer)
        assert state["posts"] == posts
    conn.close()
