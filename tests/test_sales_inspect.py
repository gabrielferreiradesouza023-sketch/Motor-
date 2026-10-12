"""Synthetic personal data is planted; inspection may expose metadata only."""

import csv
import io
import json

import pytest
import yaml
from typer.testing import CliRunner

from arb.cli import app
from arb.config import SalesCSV

PRIVATE = [
    "SYNTHETIC Buyer Name",
    "synthetic.buyer@example.invalid",
    "111.222.333-44",
    "PRIVATE_UNKNOWN_STATUS",
]
HEADERS = [
    "hotmart_tx_id",
    "ts",
    "commission_cents",
    "status",
    "tracking_param",
    "name",
    "email",
    "cpf",
    "decimal_dot",
    "decimal_comma",
    "empty",
]


def source(tmp_path, *, delimiter=",", encoding="utf-8", unknown=False):
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter)
    writer.writerow(HEADERS)
    for index in range(2):
        writer.writerow(
            [
                str(index),
                "2026-10-12T12:00:00Z",
                "5000",
                PRIVATE[3] if unknown and index else "approved",
                "3",
                *PRIVATE[:3],
                "1.25",
                "1,25",
                "",
            ]
        )
    path = tmp_path / "synthetic.csv"
    path.write_bytes(output.getvalue().encode(encoding))
    return path


def mapping(tmp_path, **updates):
    value = SalesCSV(strict_headers=False).model_dump() | updates
    path = tmp_path / "mapping.yaml"
    path.write_text(yaml.safe_dump(value))
    return path


def inspect(path, *args):
    return CliRunner().invoke(app, ["sales", "inspect", "--csv", str(path), *args])


def assert_private(result):
    for value in PRIVATE:
        assert value not in result.output
    assert "hash" not in result.output.lower()


@pytest.mark.parametrize("json_flag", [False, True])
def test_metadata_reference_and_no_writes(tmp_path, monkeypatch, json_flag):
    import arb.db

    def forbidden(*args, **kwargs):
        raise AssertionError("inspection must not open database")

    monkeypatch.setattr(arb.db, "connect", forbidden)
    path = source(tmp_path)
    map_path = mapping(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = inspect(path, "--mapping", str(map_path), *(["--json"] if json_flag else []))
    assert result.exit_code == 0, result.output
    assert_private(result)
    if json_flag:
        value = json.loads(result.stdout)
        assert value["separator"] == "," and value["encoding"] == "utf-8"
        assert value["rows"] == 2
        assert {c["name"]: c["type"] for c in value["columns"]} == {
            "hotmart_tx_id": "inteiro",
            "ts": "data ISO",
            "commission_cents": "inteiro",
            "status": "texto",
            "tracking_param": "inteiro",
            "name": "texto",
            "email": "texto",
            "cpf": "texto",
            "decimal_dot": "decimal com .",
            "decimal_comma": "decimal com ,",
            "empty": "vazio",
        }
        assert value["mapping"]["compatible"] is True
        assert value["mapping"]["missing_columns"] == []
        assert value["mapping"]["unused_columns"] == HEADERS[5:]
        assert value["mapping"]["statuses"] == {"mapped": 2, "unmapped": 0}
    else:
        assert "Linhas de dados: 2" in result.stdout and "email: texto" in result.stdout
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize("violation", ["missing", "unknown_status", "strict", "invalid_map"])
def test_mapping_incompatibilities_without_values(tmp_path, violation):
    path = source(tmp_path, unknown=violation == "unknown_status")
    map_path = mapping(tmp_path, strict_headers=violation == "strict")
    if violation == "missing":
        value = yaml.safe_load(map_path.read_text())
        value["columns"]["status"] = "missing_status_column"
        map_path.write_text(yaml.safe_dump(value))
    elif violation == "invalid_map":
        map_path.write_text("columns: {}\nstatuses: {}\n")
    result = inspect(path, "--mapping", str(map_path), "--json")
    assert result.exit_code == 1
    assert_private(result)
    if violation != "invalid_map":
        value = json.loads(result.stdout)
        assert not value["mapping"]["compatible"]
        if violation == "missing":
            assert value["mapping"]["missing_columns"] == ["missing_status_column"]
        if violation == "unknown_status":
            assert value["mapping"]["statuses"] == {"mapped": 1, "unmapped": 1}


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_detect_separator_bom_and_only_compatible_import_delimiter(tmp_path, delimiter):
    path = source(tmp_path, delimiter=delimiter, encoding="utf-8-sig")
    result = inspect(path, "--json")
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert (
        value["separator"] == delimiter and value["encoding"] == "utf-8-sig" and value["rows"] == 2
    )
    result = inspect(path, "--mapping", str(mapping(tmp_path)), "--json")
    assert result.exit_code == (0 if delimiter == "," else 1)
    assert_private(result)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xef\xbb\xbf",
        b"nome\nJo\xe3o\n",
        b"a,a\n1,2\n",
        b"a,b\n1,2,3\n",
        b'a,b\n"unterminated',
    ],
)
def test_empty_unsupported_encoding_and_malformed_refused(tmp_path, content):
    path = tmp_path / "synthetic.csv"
    path.write_bytes(content)
    result = inspect(path, "--json")
    assert result.exit_code == 1
    assert_private(result)
    assert path.read_bytes() == content


def test_missing_input_and_mixed_types_do_not_expose_cells(tmp_path):
    assert inspect(tmp_path / "missing").exit_code == 1
    path = tmp_path / "synthetic.csv"
    path.write_text("mixed,stamp\n1,2026-99-99\nPRIVATE_UNKNOWN_STATUS,2026-10-12\n")
    result = inspect(path, "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["columns"] == [
        {"name": "mixed", "type": "texto"},
        {"name": "stamp", "type": "texto"},
    ]
    assert_private(result)


@pytest.mark.parametrize(
    "content,expected",
    [
        ("only\n", [{"name": "only", "type": "vazio"}]),
        ("only\n12\n", [{"name": "only", "type": "inteiro"}]),
        (
            "name,empty\nPRIVATE_UNKNOWN_STATUS,\n\n",
            [{"name": "name", "type": "texto"}, {"name": "empty", "type": "vazio"}],
        ),
    ],
)
def test_header_only_single_column_and_blank_lines(tmp_path, content, expected):
    path = tmp_path / "synthetic.csv"
    path.write_text(content)
    result = inspect(path, "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["columns"] == expected
    assert_private(result)


def test_mapping_errors_and_unmapped_status_sanitized_in_text(tmp_path):
    path = source(tmp_path, unknown=True)
    map_path = mapping(tmp_path)
    result = inspect(path, "--mapping", str(map_path))
    assert result.exit_code == 1 and "não mapeados: 1" in result.stdout
    assert_private(result)
    map_path.write_text("columns: [PRIVATE_UNKNOWN_STATUS")
    result = inspect(path, "--mapping", str(map_path))
    assert result.exit_code == 1
    assert_private(result)
