from datetime import timedelta

from arb.analyst.report import generate_report
from arb.db import Repository, connect
from arb.models import Decision
from arb.sim.lab import persist, run_lab


def test_simulated_report_mobile_escaped_single_question(tmp_path):
    database = tmp_path / "simulation.db"
    persist(run_lab(42), database)
    connection = connect(database)
    decision = max(Repository(connection, Decision).list(), key=lambda d: d.ts)
    with connection:
        Repository(connection, Decision).add(
            decision.model_copy(
                update={
                    "id": "malicious",
                    "verdict": "kill",
                    "ts": decision.ts + timedelta(seconds=1),
                    "reason": "<script>alert(1)</script>",
                }
            )
        )
    result = generate_report(connection, tmp_path / "reports")
    text = result.read_text()
    assert 'name="viewport"' in text and "auto-fit" in text
    assert text.count('<p class="decision-question">') == 1
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "Caixa restante" in text and "Mortos e promovidos" in text
    assert len(list(result.parent.glob("*.html"))) == 2
    connection.close()
