"""Vendas normalizadas e casamento determinístico pelo id do anúncio."""

import csv
import hashlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from arb.config import SalesCSV
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
    for token, entity_id in connection.execute("SELECT token,entity_id FROM tracking_ids"):
        if token in aliases and aliases[token] != entity_id:
            raise ValueError("id de rastreio ambíguo")
        aliases[token] = entity_id
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


def mapped_row(row, mapping):
    values = {key: row[column] for key, column in mapping.columns.items()}
    if values["status"] not in mapping.statuses:
        raise ValueError("status desconhecido; ajustar mapa de status")
    values["status"] = mapping.statuses[values["status"]]
    raw_money = values["commission_cents"]
    try:
        if mapping.money_format == "cents":
            values["commission_cents"] = int(raw_money)
        else:
            separator = re.escape(mapping.decimal_separator)
            if not re.fullmatch(r"[0-9]+(?:" + separator + r"[0-9]{1,2})?", raw_money):
                raise ValueError("decimal inválido")
            whole, _, fraction = raw_money.partition(mapping.decimal_separator)
            values["commission_cents"] = int(whole) * 100 + int(fraction.ljust(2, "0"))
    except ValueError:
        raise ValueError(
            "valor monetário inválido; sem arredondamento ou separador implícito"
        ) from None
    if mapping.date_format is not None or mapping.timezone is not None:
        try:
            stamp = (
                datetime.strptime(values["ts"], mapping.date_format)
                if mapping.date_format is not None
                else datetime.fromisoformat(values["ts"])
            )
            if stamp.utcoffset() is None:
                if mapping.timezone is None:
                    raise ValueError("data sem fuso")
                zone = ZoneInfo(mapping.timezone)
                if (
                    stamp.replace(tzinfo=zone, fold=0).utcoffset()
                    != stamp.replace(tzinfo=zone, fold=1).utcoffset()
                ):
                    raise ValueError("data ambígua/inexistente")
                stamp = stamp.replace(tzinfo=zone)
            values["ts"] = stamp
        except ValueError:
            raise ValueError("data, formato ou fuso inválido; não inferir timezone") from None
    return values


def import_sales(
    connection: sqlite3.Connection, path: Path, *, mapping: SalesCSV | None = None
) -> int:
    mapping = mapping or SalesCSV()
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        expected = [mapping.columns[key] for key in HEADERS]
        fields = reader.fieldnames or []
        if (
            len(fields) != len(set(fields))
            or not set(expected) <= set(fields)
            or (mapping.strict_headers and fields != expected)
        ):
            raise ValueError("Cabeçalho de vendas inválido; conferir mapeamento declarado")
        parsed = []
        for number, row in enumerate(reader, 2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("colunas inválidas")
                row = mapped_row(row, mapping)
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
                message = (
                    "campos inválidos ou timestamp sem fuso"
                    if isinstance(exc, ValidationError)
                    else str(exc)
                )
                raise ValueError(f"Venda inválida na linha {number}: {message}") from None
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
