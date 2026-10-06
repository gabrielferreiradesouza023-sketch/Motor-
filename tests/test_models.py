import json
from datetime import datetime

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from arb.cli import app
from arb.models import MODEL_TYPES, contract_name, export_contracts


@pytest.mark.parametrize("index", range(9))
def test_round_trip_every_model(records, index):
    record = records[index]
    assert type(record).model_validate_json(record.model_dump_json()) == record
    assert type(record).model_validate(record.model_dump()) == record


@pytest.mark.parametrize("index", range(9))
def test_extra_fields_refused(records, index):
    record = records[index]
    with pytest.raises(ValidationError):
        type(record).model_validate(record.model_dump() | {"unexpected": "value"})


@pytest.mark.parametrize("value", [-1, 12.5, "100", True])
@pytest.mark.parametrize(
    "index,field",
    [
        (0, "commission_brl_cents"),
        (0, "price_local"),
        (3, "daily_budget_cents"),
        (4, "spend_platform_cents"),
        (5, "commission_cents"),
        (7, "max_exposure_cents"),
    ],
)
def test_money_is_nonnegative_integer(records, index, field, value):
    with pytest.raises(ValidationError):
        type(records[index]).model_validate(records[index].model_dump() | {field: value})


@pytest.mark.parametrize(
    "index,field,value",
    [
        (0, "status", "unknown"),
        (0, "score", 101),
        (0, "sales_page_url", "not-a-url"),
        (1, "status", "unknown"),
        (2, "format", "pdf"),
        (2, "policy_lint", "unknown"),
        (3, "gate", "4"),
        (3, "geo", "colombia"),
        (4, "impressions", -1),
        (5, "source", "manual"),
        (6, "verdict", "unknown"),
        (7, "plan_hash", "bad"),
        (8, "actor", "anonymous"),
    ],
)
def test_invalid_fields(records, index, field, value):
    with pytest.raises(ValidationError):
        type(records[index]).model_validate(records[index].model_dump() | {field: value})


@pytest.mark.parametrize(
    "index,field", [(4, "ts"), (5, "ts"), (6, "ts"), (7, "decided_at"), (8, "ts")]
)
def test_timezone_required(records, index, field):
    with pytest.raises(ValidationError):
        type(records[index]).model_validate(
            records[index].model_dump() | {field: datetime(2026, 10, 5)}
        )


def test_contract_export_deterministic(tmp_path):
    result = CliRunner().invoke(app, ["contracts", "export", "--output", str(tmp_path)])
    assert result.exit_code == 0, result.output
    first = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    assert len(first) == len(MODEL_TYPES)
    export_contracts(tmp_path)
    assert first == {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    for model in MODEL_TYPES:
        assert json.loads(first[contract_name(model)]) == model.model_json_schema()
