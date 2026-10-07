from datetime import UTC, date, datetime

import httpx
import pytest

from arb.analyst import pnl
from arb.db import Repository, connect, migrate
from arb.meta.read import Reader
from arb.meta.sync import sync as meta_sync
from arb.models import MetricSnapshot, SaleEvent
from arb.tracker import import_sales
from arb.tracker.sync import sync as tracker_sync

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


def seeded(path, records):
    conn = connect(path)
    migrate(conn)
    with conn:
        for record in records[:4]:
            Repository(conn, type(record)).add(record)
    return conn


def csv_file(path, *, status="approved", reverse=False, commission=5000):
    rows = [f"tx{i},2026-10-07T12:00:00Z,{commission},{status},entity\n" for i in range(3)]
    path.write_text(
        "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
        + "".join(rows[::-1] if reverse else rows)
    )
    return path


@pytest.mark.parametrize(
    "case", ["replay", "reordered", "refunded", "chargeback", "conflict", "crash"]
)
def test_csv_matches_reference(tmp_path, records, monkeypatch, case):
    import arb.tracker as tracker

    reference = seeded(tmp_path / "ref.db", records)
    interrupted = seeded(tmp_path / "work.db", records)
    path = csv_file(tmp_path / "sales.csv")
    import_sales(reference, path)
    original = tracker.ingest
    calls = []

    def ingest(conn, sale):
        result = original(conn, sale)
        calls.append(sale.id)
        if case == "crash" and len(calls) == 2:
            raise KeyboardInterrupt("middle of csv")
        return result

    monkeypatch.setattr(tracker, "ingest", ingest)
    if case == "crash":
        with pytest.raises(KeyboardInterrupt):
            import_sales(interrupted, path)
        assert Repository(interrupted, SaleEvent).list() == []
    monkeypatch.setattr(tracker, "ingest", original)
    import_sales(interrupted, path)
    if case in {"refunded", "chargeback"}:
        path = csv_file(path, status=case)
        import_sales(reference, path)
        import_sales(interrupted, path)
        path = csv_file(path)
    elif case == "reordered":
        path = csv_file(path, reverse=True)
    elif case == "conflict":
        path = csv_file(path, commission=9999)
        with pytest.raises(ValueError):
            import_sales(interrupted, path)
        path = csv_file(path)
    import_sales(interrupted, path)
    assert Repository(interrupted, SaleEvent).list() == Repository(reference, SaleEvent).list()
    assert {k: v for k, v in pnl(interrupted)["totals"].items() if k != "ts"} == {
        k: v for k, v in pnl(reference)["totals"].items() if k != "ts"
    }
    interrupted.close()
    reference.close()


def events():
    return [
        {
            "cursor": i,
            "id": f"event-{i}",
            "kind": "view" if i != 2 else "checkout_click",
            "ad_id": "entity",
            "geo": "CO",
            "ts": NOW.isoformat(),
        }
        for i in range(1, 4)
    ]


def sync_events(conn, *, handler=None):
    def default(request):
        cursor = int(request.url.params["after_event"])
        return httpx.Response(
            200,
            json={
                "events": [e for e in events() if e["cursor"] > cursor],
                "sales": [],
                "more": False,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler or default)) as client:
        return tracker_sync(conn, "https://worker.example", "synthetic", client=client)


@pytest.mark.parametrize("boundary", ["read", "receipt", "cursor-before", "cursor-after"])
def test_receipts_crash_replay_matches_reference(tmp_path, records, monkeypatch, boundary):
    reference = seeded(tmp_path / "ref.db", records)
    conn = seeded(tmp_path / "work.db", records)
    sync_events(reference)
    crashed = []
    original_add = Repository.add

    def add(repo, record):
        original_add(repo, record)
        if boundary == "receipt" and isinstance(record, MetricSnapshot) and not crashed:
            crashed.append(True)
            raise SystemExit("after snapshot, before applied/cursor")

    monkeypatch.setattr(Repository, "add", add)
    original = conn

    class Connection:
        def __getattr__(self, name):
            return getattr(original, name)

        def __enter__(self):
            original.__enter__()
            return self

        def __exit__(self, *args):
            return original.__exit__(*args)

        def execute(self, sql, params=()):
            cursor_write = sql.startswith("INSERT INTO tracker_cursors") and not crashed
            if cursor_write and boundary == "cursor-before":
                crashed.append(True)
                raise SystemExit("before cursor")
            result = original.execute(sql, params)
            if cursor_write and boundary == "cursor-after":
                crashed.append(True)
                raise SystemExit("after cursor")
            return result

    conn = Connection()

    def cut(request):
        if boundary == "read" and not crashed:
            crashed.append(True)
            raise SystemExit("after read")
        return httpx.Response(200, json={"events": events(), "sales": [], "more": False})

    with pytest.raises(SystemExit):
        sync_events(conn, handler=cut)
    assert not conn.in_transaction
    sync_events(conn)
    sync_events(conn)
    assert pnl(conn)["totals"] == pnl(reference)["totals"]
    assert Repository(conn, MetricSnapshot).list() == Repository(reference, MetricSnapshot).list()
    assert conn.execute("SELECT event_cursor FROM tracker_cursors").fetchone()[0] == 3
    conn.close()
    reference.close()


def test_concurrent_older_page_never_regresses_cursor(tmp_path, records):
    conn = seeded(tmp_path / "work.db", records)
    other = connect(tmp_path / "work.db")
    reference = seeded(tmp_path / "ref.db", records)
    sync_events(reference)

    def delayed_page(request):
        # A segunda coleta ingere e confirma 1..3 enquanto a primeira espera a resposta 1.
        sync_events(other)
        return httpx.Response(200, json={"events": events()[:1], "sales": [], "more": False})

    sync_events(conn, handler=delayed_page)
    assert pnl(conn)["totals"] == pnl(reference)["totals"]
    assert conn.execute("SELECT event_cursor FROM tracker_cursors").fetchone()[0] == 3
    conn.close()
    other.close()
    reference.close()


def meta_reader(*, correction=False, reverse=False):
    ad = {
        "id": "3",
        "status": "PAUSED",
        "adset": {
            "id": "2",
            "status": "PAUSED",
            "daily_budget": "1000",
            "campaign": {"id": "1", "status": "PAUSED"},
        },
    }
    rows = [
        {
            "ad_id": "3",
            "date_start": day,
            "date_stop": day,
            "impressions": "1000",
            "inline_link_clicks": "10",
            "spend": spend,
            "actions": [],
        }
        for day, spend in [
            ("2026-10-05", "9.00" if correction else "10.00"),
            ("2026-10-06", "5.00"),
        ]
    ]

    def handler(request):
        assert request.method == "GET"
        if request.url.path.endswith("/ads"):
            return httpx.Response(200, json={"data": [ad]})
        if request.url.path.endswith("/insights"):
            return httpx.Response(200, json={"data": rows[::-1] if reverse else rows})
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    return Reader(
        "synthetic", "123", "v99.0", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def collect_meta(conn, **kwargs):
    reader = meta_reader(**kwargs)
    try:
        return meta_sync(
            conn,
            reader,
            date(2026, 10, 5),
            date(2026, 10, 6),
            mapping={"3": {"offer_id": "offer", "geo": "CO"}},
            now=NOW,
        )
    finally:
        reader.client.close()


@pytest.mark.parametrize("case", ["replay", "overlap", "correction", "crash"])
def test_meta_windows_match_clean_totals(tmp_path, records, monkeypatch, case):
    reference = seeded(tmp_path / "ref.db", records)
    conn = seeded(tmp_path / "work.db", records)
    collect_meta(reference, correction=case == "correction")
    original = Repository.add
    count = []

    def add(repo, record):
        original(repo, record)
        if isinstance(record, MetricSnapshot):
            count.append(1)
            if len(count) == 2:
                raise KeyboardInterrupt("middle of window")

    if case == "crash":
        monkeypatch.setattr(Repository, "add", add)
        with pytest.raises(KeyboardInterrupt):
            collect_meta(conn)
        assert Repository(conn, MetricSnapshot).list() == []
        monkeypatch.setattr(Repository, "add", original)
    collect_meta(conn)
    collect_meta(conn, correction=case == "correction", reverse=case == "overlap")
    collect_meta(conn, correction=case == "correction")
    assert pnl(conn)["totals"] == pnl(reference)["totals"]
    assert conn.execute("SELECT count(*) FROM meta_daily").fetchone()[0] == 2
    conn.close()
    reference.close()
