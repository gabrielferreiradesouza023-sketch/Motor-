import pytest
from test_tracker import tracking_db as _tracking_db

from arb.config import SalesCSV, load_sales_csv
from arb.db import Repository
from arb.models import SaleEvent
from arb.tracker import import_sales

tracking_db = _tracking_db
HEADER = "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"


def test_default_preserves_serialized_sale(tracking_db, tmp_path, records):
    path = tmp_path / "sales.csv"
    path.write_text(HEADER + "tx1,2026-10-05T12:00:00Z,5000,approved,entity\n")
    assert load_sales_csv() == SalesCSV()
    assert import_sales(tracking_db, path) == 1
    original = Repository(tracking_db, SaleEvent).list()[0].model_dump_json()
    assert import_sales(tracking_db, path, mapping=load_sales_csv()) == 0
    assert Repository(tracking_db, SaleEvent).list()[0].model_dump_json() == original
    sale = Repository(tracking_db, SaleEvent).list()[0]
    assert sale.model_copy(update={"id": "sale"}) == records[5]


def alternate(**kwargs):
    return SalesCSV(
        columns=dict(
            hotmart_tx_id="txn",
            ts="quando",
            commission_cents="valor",
            status="situacao",
            tracking_param="rastro",
        ),
        statuses={"pago": "approved"},
        date_format="%d/%m/%Y %H:%M",
        timezone="America/Sao_Paulo",
        money_format="decimal",
        decimal_separator=",",
        **kwargs,
    )


def test_synthetic_mapping_decimal_timezone_and_extra_columns(tracking_db, tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        "extra,rastro,situacao,valor,quando,txn\n"
        'ignorado,entity,pago,"12,50",05/10/2026 09:00,tx1\n'
    )
    assert import_sales(tracking_db, path, mapping=alternate(strict_headers=False)) == 1
    sale = Repository(tracking_db, SaleEvent).list()[0]
    assert sale.commission_cents == 1250 and sale.status == "approved"
    assert sale.ts.isoformat() == "2026-10-05T09:00:00-03:00"
    assert sale.matched_entity_id == "entity"


@pytest.mark.parametrize(
    "changes",
    [
        {"columns": {}},
        {
            "columns": dict(
                hotmart_tx_id="x", ts="x", commission_cents="c", status="s", tracking_param="t"
            )
        },
        {"statuses": {}},
        {"statuses": {"pago": "unknown"}},
        {"timezone": "invalid/zone"},
        {"date_format": ""},
        {"decimal_separator": ";"},
    ],
)
def test_invalid_mapping_rejected(changes):
    with pytest.raises(ValueError):
        SalesCSV(**changes)


@pytest.mark.parametrize(
    "line,reason",
    [
        ("tx1,2026-10-05T12:00:00Z,5000,unknown,entity", "status desconhecido"),
        ("tx1,2026-10-05T12:00:00,5000,approved,entity", "fuso"),
        ("tx1,2026-10-05T12:00:00Z,5.5,approved,entity", "monetário"),
    ],
)
def test_bad_row_rejected_atomically(tracking_db, tmp_path, line, reason):
    path = tmp_path / "sales.csv"
    path.write_text(HEADER + "first,2026-10-05T12:00:00Z,5000,approved,entity\n" + line + "\n")
    with pytest.raises(ValueError, match=reason):
        import_sales(tracking_db, path)
    assert Repository(tracking_db, SaleEvent).list() == []


@pytest.mark.parametrize("value", ["12,345", "1.000,00", "1e2", "-1,00"])
def test_decimal_never_rounds_or_guesses(tracking_db, tmp_path, value):
    path = tmp_path / "sales.csv"
    path.write_text(
        'txn,quando,valor,situacao,rastro\ntx1,05/10/2026 09:00,"' + value + '",pago,entity\n'
    )
    with pytest.raises(ValueError, match="monetário"):
        import_sales(tracking_db, path, mapping=alternate())
    assert not Repository(tracking_db, SaleEvent).list()


@pytest.mark.parametrize("stamp", ["01/11/2026 01:30", "08/03/2026 02:30"])
def test_dst_ambiguous_or_nonexistent_refused(tracking_db, tmp_path, stamp):
    path = tmp_path / "sales.csv"
    path.write_text("txn,quando,valor,situacao,rastro\ntx1," + stamp + ",12,pago,entity\n")
    mapping = alternate().model_copy(update={"timezone": "America/New_York"})
    with pytest.raises(ValueError, match="fuso"):
        import_sales(tracking_db, path, mapping=mapping)
