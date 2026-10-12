"""CSV metadata only: no cell samples, hashes, database access or provider acceptance."""

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from arb.config import load_sales_csv
from arb.tracker import validate_sales_headers


def cell_type(value):
    value = value.strip()
    if not value:
        return "vazio"
    if re.fullmatch(r"[+-]?[0-9]+", value):
        return "inteiro"
    for separator in (".", ","):
        if re.fullmatch(r"[+-]?[0-9]+" + re.escape(separator) + r"[0-9]+", value):
            return "decimal com " + separator
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T.*)?", value):
        try:
            datetime.fromisoformat(value)
            return "data ISO"
        except ValueError:
            pass
    return "texto"


def inspect_csv(path: Path, *, mapping: Path | None = None):
    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    text = raw.decode(encoding)
    if not text.strip() or "\x00" in text:
        raise ValueError("CSV vazio ou inválido")
    try:
        separator = csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
    except csv.Error:
        if any(c in text for c in ",;\t|"):
            raise ValueError("Separador ou estrutura do CSV inválidos") from None
        separator = ","  # single column; comma parser is also used by import_sales
    try:
        rows = [
            row
            for row in csv.reader(io.StringIO(text, newline=""), delimiter=separator, strict=True)
            if row
        ]
    except csv.Error:
        raise ValueError("Estrutura do CSV inválida") from None
    headers, *rows = rows
    if len(headers) != len(set(headers)) or any(not name.strip() for name in headers):
        raise ValueError("Cabeçalhos vazios ou duplicados")
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("Número de colunas inconsistente")
    columns = []
    for index, name in enumerate(headers):
        kinds = {cell_type(row[index]) for row in rows} - {"vazio"}
        kind = next(iter(kinds)) if len(kinds) == 1 else "texto" if kinds else "vazio"
        columns.append({"name": name, "type": kind})
    result = {
        "separator": separator,
        "encoding": encoding,
        "rows": len(rows),
        "columns": columns,
        "mapping": None,
    }
    if mapping is not None:
        declared = load_sales_csv(mapping)
        expected = set(declared.columns.values())
        missing = sorted(expected - set(headers))
        unused = [name for name in headers if name not in expected]
        issues = []
        try:
            validate_sales_headers(headers, declared)
        except ValueError:
            issues.append("Cabeçalho incompatível com o mapa declarado")
        if separator != ",":
            issues.append("Importador atual exige separador vírgula; revisar exportação no host")
        counts = {"mapped": 0, "unmapped": 0}
        status_column = declared.columns["status"]
        if status_column in headers:
            index = headers.index(status_column)
            for row in rows:
                counts["mapped" if row[index] in declared.statuses else "unmapped"] += 1
        if counts["unmapped"]:
            issues.append("Há status não mapeados; revisar mapa no host")
        result["mapping"] = {
            "compatible": not issues,
            "missing_columns": missing,
            "unused_columns": unused,
            "statuses": counts,
            "issues": issues,
        }
    return result


def summary(value):
    lines = [
        f"Separador: {value['separator']!r}; codificação: {value['encoding']}",
        f"Linhas de dados: {value['rows']}",
    ]
    lines.extend(f"{column['name']}: {column['type']}" for column in value["columns"])
    mapped = value["mapping"]
    if mapped is not None:
        lines.extend(
            [
                "Mapa: " + ("compatível" if mapped["compatible"] else "incompatível"),
                "Colunas ausentes: " + ", ".join(mapped["missing_columns"]),
                "Colunas não usadas: " + ", ".join(mapped["unused_columns"]),
                f"Status mapeados: {mapped['statuses']['mapped']}; "
                f"não mapeados: {mapped['statuses']['unmapped']}",
                *mapped["issues"],
            ]
        )
    return "\n".join(lines)
