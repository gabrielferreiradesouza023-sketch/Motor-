from arb.analyst.library import archive, query
from arb.db import connect
from arb.models import AngleLearning
from arb.sim.lab import persist, run_lab


def test_library_round_trip_niche_and_idempotence(tmp_path):
    path = tmp_path / "sim.db"
    persist(run_lab(42), path)
    connection = connect(path)
    count = archive(connection)
    assert count > 0
    rows = query(connection, "excel_produtividade")
    assert rows and any(r.verdict == "pass" and r.gate == "3" for r in rows)
    assert all(r.reason and r.metrics_json and r.formats for r in rows)
    assert all(AngleLearning.model_validate_json(r.model_dump_json()) == r for r in rows)
    assert archive(connection) == count
    assert query(connection, "excel_produtividade") == rows
    assert query(connection, "pets") == []
    connection.close()
