"""Synthetic confirmation fixtures; references use Decimal at 80 digits, independently."""

from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from arb.config import GateC, Rules
from arb.metrics import p_roi_positive
from arb.rules import confirmation_context, evaluate, load_rules, scale_allowed, winner_gates


def confirmation_rules():
    return load_rules().model_copy(
        update={
            "gate_C": GateC(cap_cents=15000, min_sales_total=4, min_roi=0, min_p_roi_positive=0.8)
        }
    )


@pytest.mark.parametrize(
    "sales,spent,net",
    [
        (0, 6000, 5100),
        (2, 5000, 5100),
        (100, 500000, 5000),
        (1000, 1000000, 5100),
        (0, 10000000, 1),
    ],
)
def test_posterior_independent_decimal_reference(sales, spent, net):
    with localcontext() as ctx:
        ctx.prec = 80
        x = Decimal(spent + 1) / Decimal(net)
        term = Decimal(1)
        total = term
        for n in range(1, sales + 1):
            term *= x / Decimal(n)
            total += term
        expected = float((-x).exp() * total)
    assert p_roi_positive(sales, spent, net) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    "args",
    [
        (-1, 1, 1),
        (True, 1, 1),
        (1, -1, 1),
        (1, True, 1),
        (1, 1, -1),
        (1, 1, float("inf")),
        (1, 1, float("nan")),
    ],
)
def test_posterior_rejects_invalid(args):
    with pytest.raises(ValueError):
        p_roi_positive(*args)


def test_zero_exposure_or_commission():
    assert p_roi_positive(0, 0, 5000) is None
    assert p_roi_positive(1, 5000, 0) is None


def decision(records, *, sales=4, spend=5000, gate="C", baseline=3000, stale=False, rules=None):
    entity = records[3].model_copy(update={"gate": gate})
    snapshot = records[4].model_copy(update={"spend_platform_cents": spend})
    rows = [
        records[5].model_copy(update={"id": str(n), "hotmart_tx_id": str(n)}) for n in range(sales)
    ]
    return evaluate(
        entity,
        snapshot,
        rows,
        5000,
        rules or confirmation_rules(),
        snapshot.ts + timedelta(hours=7 if stale else 0),
        confirmation_start_cents=baseline,
    )


@pytest.mark.parametrize(
    "count,spend,stale,verdict",
    [
        (2, 5000, False, "insufficient_data"),
        (4, 5000, False, "pass"),
        (2, 16000, False, "kill"),
        (4, 16000, False, "kill"),
        (4, 14000, False, "hold"),
        (4, 5000, True, "insufficient_data"),
        (2, 16000, True, "kill"),
        (0, 5000, False, "insufficient_data"),
    ],
)
def test_confirmation_planted_samples_and_cap(records, count, spend, stale, verdict):
    d = decision(records, sales=count, spend=spend, stale=stale)
    assert d.verdict == verdict
    assert d.metrics_json["cap_cents"] == 18000
    assert d.metrics_json["confirmation_start_cents"] == 3000
    assert d.metrics_json["confirmation_geo"] == "CO"


@pytest.mark.parametrize("baseline", [None, -1, True, 999999])
def test_missing_or_corrupt_confirmation_baseline(records, baseline):
    with pytest.raises(ValueError, match="gasto inicial"):
        decision(records, baseline=baseline)


def test_disabled_candidate_transfer_and_scale(records):
    r = confirmation_rules()
    d = decision(records, gate="3", sales=2)
    assert d.verdict == "pass" and "Candidato" in d.reason
    old = decision(records, gate="3", sales=2, rules=load_rules())
    assert old.verdict == "pass" and old.reason == "Combo validado: vendas, ROI e CPC"
    assert old.metrics_json["p_roi_positive"] == d.metrics_json["p_roi_positive"]
    assert winner_gates(r) == {"C", "T"} and winner_gates(load_rules()) == {"3", "T"}
    assert decision(records, gate="T").rule_id == "gT.confirmation"
    assert decision(records, gate="T", spend=16000).verdict == "kill"
    now = records[4].ts
    args = (r, 1000, 1200, now - timedelta(hours=24), now)
    assert not scale_allowed(*args, approved=True)
    assert scale_allowed(*args, approved=True, confirmed=True)
    with pytest.raises(ValueError, match="desligado"):
        decision(records, rules=load_rules())


def test_confirmed_transfer_and_context_geo_and_latest(records):
    e = records[3].model_copy(update={"gate": "T"})
    d = decision(records, gate="3", sales=2)
    c = decision(records)
    c.id = "later"
    c.ts += timedelta(seconds=1)
    assert confirmation_context(e, [c, d]) == (5650, True)
    changed = e.model_copy(update={"geo": "PE"})
    assert confirmation_context(changed, [c, d]) == (None, False)
    lost = c.model_copy(update={"id": "lost", "ts": c.ts + timedelta(seconds=1), "verdict": "kill"})
    assert confirmation_context(e, [d, c, lost]) == (5650, False)
    sales = [
        records[5].model_copy(update={"id": str(i), "hotmart_tx_id": str(i)}) for i in range(4)
    ]
    result = evaluate(
        e, records[4], sales, 5000, confirmation_rules(), records[4].ts, confirmed=True
    )
    assert result.verdict == "pass"


def test_lab_requires_confirmation_and_preserves_default():
    from arb.sim.lab import run_lab

    base = run_lab(42)
    off = run_lab(42, rules=Rules.model_validate(load_rules().model_dump()))
    assert base.summary() == off.summary()
    on = run_lab(42, rules=confirmation_rules())
    assert on.winners
    for winner in on.winners:
        assert any(
            d.entity_id == "set-" + winner and d.gate == "C" and d.verdict == "pass"
            for d in on.decisions
        )


def test_library_rejects_g3_candidate(tmp_path):
    from arb.analyst.library import archive, query
    from arb.db import connect
    from arb.sim.lab import persist, run_lab

    path = tmp_path / "synthetic.db"
    persist(run_lab(42), path)
    connection = connect(path)
    archive(connection, rules=confirmation_rules())
    assert all(row.verdict != "pass" for row in query(connection, "excel_produtividade"))
    connection.close()


def test_scheduler_candidate_becomes_c_then_confirmed(tmp_path, records):
    import shutil
    from datetime import date
    from pathlib import Path

    import yaml
    from test_scheduler import seeded

    from arb.db import Repository
    from arb.models import Decision, Entity, SaleEvent
    from arb.scheduler import run_cycle, schedule

    root = tmp_path / "root"
    shutil.copytree(Path("config"), root / "config")
    (root / "config/rules.yaml").write_text(yaml.safe_dump(confirmation_rules().model_dump()))
    conn = seeded(tmp_path, records)
    with conn:
        e = Repository(conn, Entity).get("entity")
        e.gate = "3"
        Repository(conn, Entity).update(e)
        Repository(conn, type(records[4])).add(records[4])
        for i in range(2):
            Repository(conn, SaleEvent).add(
                records[5].model_copy(update={"id": str(i), "hotmart_tx_id": str(i)})
            )
    slots = schedule(date(2026, 10, 5), date(2026, 10, 5))

    def source(db, now):
        return now

    run_cycle(
        conn, slots[0], now=slots[0], root=root, output=tmp_path / "reports", sync_source=source
    )
    assert Repository(conn, Entity).get("entity").gate == "C"
    assert Repository(conn, Entity).get("entity").status == "active"
    with conn:
        Repository(conn, type(records[4])).add(records[4].model_copy(update={"ts": slots[1]}))
        for i in range(2, 4):
            Repository(conn, SaleEvent).add(
                records[5].model_copy(update={"id": str(i), "hotmart_tx_id": str(i)})
            )
    run_cycle(
        conn, slots[1], now=slots[1], root=root, output=tmp_path / "reports", sync_source=source
    )
    assert any(d.gate == "C" and d.verdict == "pass" for d in Repository(conn, Decision).list())
    conn.close()


def test_scale_consumer_cannot_use_g3_candidate(tmp_path, monkeypatch):
    from test_scale import NOW, seeded

    import arb.launcher.scale as module
    from arb.db import Repository
    from arb.models import Decision

    conn, e = seeded(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "load_rules", confirmation_rules)
    with pytest.raises(ValueError):
        module.propose(conn, e.id, 2400, directory=tmp_path / "pending", now=NOW)
    with conn:
        Repository(conn, Decision).add(
            Decision(
                id="confirmed",
                ts=NOW,
                entity_id=e.id,
                gate="C",
                verdict="pass",
                metrics_json={"confirmation_geo": "CO"},
                rule_id="gC.pass",
                reason="synthetic verified winner",
            )
        )
    assert module.propose(conn, e.id, 2400, directory=tmp_path / "pending", now=NOW).exists()
    conn.close()


def test_confirmation_no_cost_is_not_profit_evidence(records):
    assert decision(records, spend=0, baseline=0).verdict == "hold"
    e = records[3].model_copy(update={"gate": "C"})
    with pytest.raises(ValueError, match="comissão"):
        evaluate(
            e, records[4], [], 0, confirmation_rules(), records[4].ts, confirmation_start_cents=0
        )


@pytest.mark.parametrize("enabled", [False, True])
def test_scheduler_confirmation_rollback_keeps_other_pauses(tmp_path, records, enabled):
    """A rolled-back C configuration/baseline must not stop unrelated protection."""
    import shutil
    from datetime import date
    from pathlib import Path

    import yaml
    from test_scheduler import seeded

    from arb.db import Repository
    from arb.models import Action, Decision, Entity, MetricSnapshot
    from arb.scheduler import run_cycle, schedule

    root = tmp_path / "root"
    shutil.copytree(Path("config"), root / "config")
    if enabled:
        (root / "config/rules.yaml").write_text(yaml.safe_dump(confirmation_rules().model_dump()))
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 5), date(2026, 10, 5))[0]
    with conn:
        entity = Repository(conn, Entity).get("entity")
        entity.gate = "C"
        Repository(conn, Entity).update(entity)
        Repository(conn, Entity).add(entity.model_copy(update={"id": "other", "gate": "1"}))
        for eid in ("entity", "other"):
            Repository(conn, MetricSnapshot).add(
                records[4].model_copy(update={"entity_id": eid, "ts": slot, "link_clicks": 0})
            )
    try:
        args = dict(
            now=slot, root=root, output=tmp_path / "reports", sync_source=lambda db, now: now
        )
        result = run_cycle(conn, slot, **args)
        assert result["stages"] == ["sync", "rules", "actions", "report", "alerts"]
        assert not conn.in_transaction
        assert {e.id for e in Repository(conn, Entity).list() if e.status == "paused"} == {
            "entity",
            "other",
        }
        decisions = {d.entity_id: d for d in Repository(conn, Decision).list()}
        assert decisions["entity"].verdict == "insufficient_data"
        assert decisions["entity"].rule_id == "gC.unavailable"
        assert decisions["other"].verdict == "kill"
        assert any("confirmation_unavailable: entity" in a for a in result["alerts"])
        actions = Repository(conn, Action).list()
        assert sum(a.kind == "pause" for a in actions) == 2
        assert run_cycle(conn, slot, **args) == result
        assert len(Repository(conn, Decision).list()) == 2
        assert Repository(conn, Action).list() == actions
    finally:
        conn.close()
