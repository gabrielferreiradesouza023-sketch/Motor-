"""F4 E2E local: JS da ponte -> D1 -> export -> SQLite -> venda/reembolso."""

import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from arb.analyst import pnl
from arb.bridge import build
from arb.db import Repository, connect, migrate
from arb.models import Entity, MetricSnapshot, Offer, SaleEvent
from arb.scout import import_offers
from arb.tracker.sync import sync

ROOT = Path(__file__).resolve().parents[2]


def main():
    ad = "e2e-" + str(uuid.uuid4())
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        connection = connect(directory / "engine.db")
        migrate(connection)
        offer = import_offers(ROOT / "examples/scout/offers.csv")[0].offer
        with connection:
            Repository(connection, Offer).add(offer)
            Repository(connection, Entity).add(
                Entity(
                    id=ad,
                    kind="ad",
                    offer_id=offer.id,
                    geo="CO",
                    gate="1",
                    daily_budget_cents=0,
                    status="paused",
                )
            )
        page = build(
            offer,
            (ROOT / "examples/bridge/content.txt").read_text(),
            "excel",
            worker_url="http://127.0.0.1:8787",
            pixel_id="123456",
            tracking_key="sck",
            output=directory / "bridges",
        )
        subprocess.run(["node", str(ROOT / "worker/test/e2e_page.mjs"), str(page), ad], check=True)
        transaction = "test-" + str(uuid.uuid4())
        sale = {
            "id": str(uuid.uuid4()),
            "hotmart_tx_id": transaction,
            "ts": datetime.now(UTC).isoformat(),
            "commission_cents": 6000,
            "status": "approved",
            "tracking_param": ad,
        }
        with httpx.Client() as client:
            response = client.post(
                "http://127.0.0.1:8787/sale",
                json=sale,
                headers={"X-Hotmart-Hottok": "local-sale-fixture-only"},
            )
            assert response.status_code == 202
        result = sync(connection, "http://127.0.0.1:8787", "local-sync-fixture-only")
        snapshots = Repository(connection, MetricSnapshot).list()
        assert sum(s.bridge_views for s in snapshots) == 1
        assert sum(s.checkout_clicks for s in snapshots) == 1
        matched = next(
            s for s in Repository(connection, SaleEvent).list() if s.hotmart_tx_id == transaction
        )
        assert matched.matched_entity_id == ad
        assert sync(connection, "http://127.0.0.1:8787", "local-sync-fixture-only") == {
            "events": 0,
            "sales": 0,
        }
        assert pnl(connection)["totals"]["rev_expected"] == 5100
        refund = sale | {
            "id": str(uuid.uuid4()),
            "status": "refunded",
            "ts": datetime.now(UTC).isoformat(),
        }
        with httpx.Client() as client:
            assert (
                client.post(
                    "http://127.0.0.1:8787/sale",
                    json=refund,
                    headers={"X-Hotmart-Hottok": "local-sale-fixture-only"},
                ).status_code
                == 202
            )
        sync(connection, "http://127.0.0.1:8787", "local-sync-fixture-only")
        assert pnl(connection)["totals"]["rev_expected"] == 0
        connection.close()
        print("F4 E2E OK: visita → clique → venda falsa casada → repetição → reembolso", result)


if __name__ == "__main__":
    main()
