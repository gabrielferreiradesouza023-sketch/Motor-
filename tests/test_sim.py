import random

from arb.sim import aggregate, population, traffic


def test_population_truth_and_seed(records):
    p = population(42)
    assert len(p.offers) == 3 and len(p.angles) == 9 and len(p.creatives) == 27
    assert sum(t.winner for t in p.truth.values()) == 3
    assert p.truth == population(42).truth
    assert p.truth != population(43).truth
    ad = next(e for e in p.entities if e.kind == "ad")
    ts = records[4].ts
    a = traffic(ad, p.truth[ad.id], random.Random(42), ts, impressions=10000)
    b = traffic(ad, p.truth[ad.id], random.Random(42), ts, impressions=10000)
    assert a == b
    snapshot, sales = a
    assert 150 < snapshot.link_clicks < 350
    assert snapshot.checkout_clicks <= snapshot.bridge_views <= snapshot.link_clicks
    assert sales and all(s.matched_entity_id == ad.id for s in sales)
    total = aggregate([snapshot, snapshot], ad.id, ts)
    assert total.impressions == snapshot.impressions * 2
