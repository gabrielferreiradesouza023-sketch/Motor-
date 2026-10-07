import json
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

import arb.drill as drill
from arb.cli import app
from arb.db import Repository
from arb.models import Approval, Entity, MetricSnapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("seed", [7, 42, 101])
def test_three_seeds_match_reference_and_repeat(seed):
    expected = json.loads((ROOT / f"docs/validation/drill-seed-{seed}.json").read_text())
    first = drill.run(seed)
    assert first == expected == drill.run(seed)
    assert first["entities"] == 1 + 4 * (1 + seed % 3)
    assert first["remote_calls"] == first["remote_effects"] == first["entities"] + 5
    assert first["totals"]["platform_cents"] == 2 * (500 + seed % 100)
    assert first["totals"]["profit_cents"] == -first["totals"]["gross_cents"]


@pytest.mark.parametrize(
    "violation", ["authority", "audit", "unique", "paused", "quarantine", "totals"]
)
def test_each_invariant_detects_planted_violation(violation):
    def plant(conn, writer, restored):
        if violation == "authority":
            with conn:
                value = next(a for a in Repository(conn, Approval).list() if a.kind == "launch")
                value.signature = None
                Repository(conn, Approval).update(value)
        elif violation == "audit":
            writer.calls.append({"key": "no-intent", "operation": "pause"})
        elif violation == "unique":
            writer.effects.append(writer.effects[0].copy())
        elif violation == "paused":
            identifier = next(iter(writer.entities))
            writer.entities[identifier] = writer.entities[identifier].model_copy(
                update={"status": "active"}
            )
        elif violation == "quarantine":
            with restored:
                restored.execute("UPDATE restore_quarantine SET released_at=NULL")
        else:
            with conn:
                entity = next(e for e in Repository(conn, Entity).list() if e.kind == "ad")
                Repository(conn, MetricSnapshot).add(
                    MetricSnapshot(
                        entity_id=entity.id,
                        ts=drill.BASE + timedelta(days=2),
                        impressions=0,
                        video_3s_views=0,
                        link_clicks=0,
                        spend_platform_cents=1,
                        bridge_views=0,
                        checkout_clicks=0,
                    )
                )

    with pytest.raises(ValueError, match=violation):
        drill.run(42, _inject=plant)


def test_cli_under_two_minutes_and_invalid_seed():
    start = time.monotonic()
    result = CliRunner().invoke(app, ["drill", "run", "--seed", "42", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["remote_effects"] == 10
    assert time.monotonic() - start < 120
    text = CliRunner().invoke(app, ["drill", "run", "--seed", "42"])
    assert text.exit_code == 0 and "apenas simulação" in text.output
    assert CliRunner().invoke(app, ["drill", "run", "--seed", "-1"]).exit_code != 0


@pytest.mark.parametrize("seed", [True, -1, 2**31])
def test_invalid_seed_refused(seed):
    with pytest.raises(ValueError, match="seed"):
        drill.run(seed)


def test_isolation_and_cleanup_with_no_private_pointer(tmp_path, monkeypatch):
    import httpx

    monkeypatch.chdir(tmp_path)
    sentinel = tmp_path / "data/engine.db"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"preserve real database sentinel")
    settings = (ROOT / "config/settings.yaml").read_bytes()
    monkeypatch.delenv("APPROVAL_PRIVATE_KEY_FILE")
    original = httpx.Client

    def only_mock(*args, **kwargs):
        assert isinstance(kwargs.get("transport"), httpx.MockTransport), "rede real proibida"
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", only_mock)
    assert drill.run(7)["pending"] == 0
    assert Path.cwd() == tmp_path and "APPROVAL_PRIVATE_KEY_FILE" not in os.environ
    assert sentinel.read_bytes() == b"preserve real database sentinel"
    assert (ROOT / "config/settings.yaml").read_bytes() == settings


def test_missing_crash_and_missing_refusal_are_not_accepted(monkeypatch):
    with pytest.raises(ValueError, match="não recusou"):
        drill._refused(lambda: None)
    with pytest.raises(ValueError, match="diferente"):
        drill._refused(lambda: (_ for _ in ()).throw(ValueError("wrong")), "expected")
    # Omitir scheduler também omite a queda: o ensaio deve falhar.
    original = drill.run_cycle

    def omitted(conn, *args, **kwargs):
        return original(conn, *args, **kwargs) if drill.current(conn) else {}

    monkeypatch.setattr(drill, "run_cycle", omitted)
    with pytest.raises(ValueError, match="queda não exercitada"):
        drill.run(42)


def test_missing_ledger_evidence_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(drill, "pending", lambda *a, **kw: [])
    with pytest.raises(ValueError, match="cenário não exercitado"):
        drill.run(42)
