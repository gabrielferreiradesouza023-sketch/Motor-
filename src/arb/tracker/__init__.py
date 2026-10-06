"""Vendas normalizadas e casamento determinístico pelo id do anúncio."""

import csv
import hashlib
import sqlite3
from pathlib import Path

from arb.db import Repository
from arb.models import Entity, SaleEvent

HEADERS = ["hotmart_tx_id", "ts", "commission_cents", "status", "tracking_param"]


def entity_map(connection: sqlite3.Connection) -> dict[str, str]:
    aliases = {}
    for entity in Repository(connection, Entity).list():
        for key in [entity.id, entity.meta_id]:
            if not key:
                continue
            if key in aliases and aliases[key] != entity.id:
                raise ValueError("id de rastreio ambíguo")
            aliases[key] = entity.id
    return aliases


def ingest(connection: sqlite3.Connection, sale: SaleEvent) -> bool:
    repo = Repository(connection, SaleEvent)
    previous = next((s for s in repo.list() if s.hotmart_tx_id == sale.hotmart_tx_id), None)
    sale = sale.model_copy(
        update={"matched_entity_id": entity_map(connection).get(sale.tracking_param)}
    )
    if previous:
        if (
            previous.commission_cents != sale.commission_cents
            or previous.tracking_param != sale.tracking_param
        ):
            raise ValueError("Transação já existe com comissão ou rastreio divergente")
        if sale.ts < previous.ts:
            return False
        if previous.status != "approved" and sale.status == "approved":
            return False  # nunca desfazer reembolso com replay de venda antiga
        if sale.status == previous.status:
            return False
        sale = sale.model_copy(
            update={
                "id": previous.id,
                "matched_entity_id": previous.matched_entity_id or sale.matched_entity_id,
            }
        )
        repo.update(sale)
    else:
        repo.add(sale)
    return True


def import_sales(connection: sqlite3.Connection, path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != HEADERS:
            raise ValueError("Cabeçalho de vendas inválido; esperado: " + ",".join(HEADERS))
        parsed = []
        for number, row in enumerate(reader, 2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("colunas inválidas")
                parsed.append(
                    SaleEvent(
                        id="sale-" + hashlib.sha256(row["hotmart_tx_id"].encode()).hexdigest(),
                        source="csv",
                        hotmart_tx_id=row["hotmart_tx_id"],
                        ts=row["ts"],
                        commission_cents=int(row["commission_cents"]),
                        status=row["status"],
                        tracking_param=row["tracking_param"] or None,
                    )
                )
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Venda inválida na linha {number}") from exc
    with connection:
        return sum(ingest(connection, sale) for sale in parsed)


def match(connection: sqlite3.Connection) -> int:
    aliases = entity_map(connection)
    count = 0
    repository = Repository(connection, SaleEvent)
    with connection:
        for sale in repository.list():
            entity = aliases.get(sale.tracking_param)
            if sale.matched_entity_id is None and entity:
                repository.update(sale.model_copy(update={"matched_entity_id": entity}))
                count += 1
    return count
