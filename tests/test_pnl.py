from datetime import timedelta

from arb.analyst import pnl
from arb.db import Repository, connect, migrate
from arb.models import Decision, SaleEvent


def test_late_sale_refund_reopens_without_losing_history(tmp_path, records):
    connection = connect(tmp_path / "pnl.db")
    migrate(connection)
    with connection:
        for record in records[:5]:
            Repository(connection, type(record)).add(record)
        kill = records[6].model_copy(update={"verdict": "kill"})
        Repository(connection, Decision).add(kill)
    before = pnl(connection)
    assert before["totals"]["spend_gross"] == 1130
    assert before["totals"]["rev_expected"] == 0
    late = records[5].model_copy(update={"ts": records[5].ts + timedelta(days=4)})
    with connection:
        Repository(connection, SaleEvent).add(late)
    after = pnl(connection)
    assert after["totals"]["rev_expected"] == 4250
    assert after["groups"]["daily"][0]["rev_expected"] == 4250
    assert after["groups"]["creative"][0]["reopened"]
    assert after["totals"]["cash_remaining_cents"] == 240000 - 1130
    with connection:
        Repository(connection, SaleEvent).update(late.model_copy(update={"status": "refunded"}))
    assert pnl(connection)["totals"]["rev_expected"] == 0
    assert Repository(connection, Decision).list() == [kill]
    connection.close()
