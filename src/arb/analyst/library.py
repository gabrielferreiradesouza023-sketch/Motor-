"""Arquivo de aprendizados e consulta pública para o gerador futuro."""

import sqlite3

from arb.db import Repository
from arb.models import Angle, AngleLearning, Creative, Decision, Entity, Offer


def archive(connection: sqlite3.Connection) -> int:
    entities = {e.id: e for e in Repository(connection, Entity).list()}
    angles = {a.id: a for a in Repository(connection, Angle).list()}
    offers = {o.id: o for o in Repository(connection, Offer).list()}
    creatives = Repository(connection, Creative).list()
    latest = {}
    for decision in sorted(Repository(connection, Decision).list(), key=lambda d: d.ts):
        entity = entities[decision.entity_id]
        if entity.angle_id:
            latest[(entity.angle_id, entity.geo)] = decision
    count = 0
    repository = Repository(connection, AngleLearning)
    with connection:
        for (angle_id, geo), d in latest.items():
            group = [e for e in entities.values() if e.angle_id == angle_id and e.geo == geo]
            if any(e.status == "active" for e in group):
                continue
            if d.verdict != "kill" and not (d.verdict == "pass" and d.gate in ("3", "T")):
                continue
            angle = angles[angle_id]
            learning = AngleLearning(
                id=f"{angle_id}:{geo}",
                angle_id=angle_id,
                offer_id=angle.offer_id,
                niche=offers[angle.offer_id].niche,
                promise=angle.promise,
                audience_pain=angle.audience_pain,
                hook_line=angle.hook_line,
                formats=sorted({c.format for c in creatives if c.angle_id == angle_id}),
                geo=geo,
                gate=d.gate,
                verdict=d.verdict,
                metrics_json=d.metrics_json,
                reason=d.reason,
                archived_at=d.ts,
            )
            if repository.get(learning.id):
                repository.update(learning)
            else:
                repository.add(learning)
            count += 1
    return count


def query(connection: sqlite3.Connection, niche: str) -> list[AngleLearning]:
    return [
        record for record in Repository(connection, AngleLearning).list() if record.niche == niche
    ]
