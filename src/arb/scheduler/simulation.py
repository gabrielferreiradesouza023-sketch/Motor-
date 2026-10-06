"""Três dias acelerados com tráfego plantado; banco novo exclusivo e nenhum acesso externo."""

import random
from datetime import date, datetime, timedelta
from pathlib import Path

from arb.db import Repository, connect, migrate
from arb.models import Angle, Creative, Entity, MetricSnapshot, Offer, SaleEvent
from arb.scheduler import run_cycle, schedule
from arb.sim import population, traffic


def simulate(
    database: Path,
    *,
    start: date = date(2026, 10, 5),
    seed: int = 42,
    output: Path = Path("reports/scheduler-sim"),
    root: Path = Path("."),
) -> dict:
    database.parent.mkdir(parents=True, exist_ok=True)
    database.touch(exist_ok=False)  # Recusa sobrescrita inclusive de banco vazio existente.
    connection = connect(database)
    try:
        migrate(connection)
        pop = population(seed)
        with connection:
            for model, rows in (
                (Offer, pop.offers),
                (Angle, pop.angles),
                (Creative, pop.creatives),
                (Entity, pop.entities),
            ):
                for row in rows:
                    Repository(connection, model).add(row)
        rng = random.Random(seed)

        def source(db, now: datetime):
            with db:
                for entity in Repository(db, Entity).list():
                    if entity.kind != "ad" or entity.status != "active":
                        continue
                    parent = Repository(db, Entity).get(entity.parent_id)
                    if parent.status != "active":
                        continue
                    snapshot, sales = traffic(
                        entity, pop.truth[entity.id], rng, now, impressions=1000
                    )
                    Repository(db, MetricSnapshot).add(snapshot)
                    for sale in sales:
                        Repository(db, SaleEvent).add(sale)
            return now

        cycles = []
        for slot in schedule(start, start + timedelta(days=2)):
            result = run_cycle(
                connection, slot, now=slot, sync_source=source, root=root, output=output
            )
            assert result == run_cycle(
                connection, slot, now=slot, sync_source=source, root=root, output=output
            )
            cycles.append(result)
        return {
            "mode": "simulation",
            "cycles": cycles,
            "cycle_count": len(cycles),
            "snapshots": len(Repository(connection, MetricSnapshot).list()),
            "paused": sum(e.status == "paused" for e in Repository(connection, Entity).list()),
        }
    finally:
        connection.close()
