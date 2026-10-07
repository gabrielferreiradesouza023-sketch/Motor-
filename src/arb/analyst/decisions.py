"""Fila somente leitura; idade do arquivo é informativa, nunca autorização/expiração."""

import re
import shlex
from datetime import UTC, datetime
from pathlib import Path

from arb.launcher.approval import read_document


def queue(directory: Path = Path("ops/approvals/pending"), *, now=None) -> dict:
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("fila exige fuso")
    rows, invalid = [], 0
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        return {"items": [], "invalid": 1}
    for path in sorted(directory.glob("*.json")):
        try:
            if path.is_symlink():
                raise ValueError("symlink recusado")
            approval, _ = read_document(path)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", approval.id) or path.stem != approval.id:
                raise ValueError("id/caminho inválido")
            if approval.status != "pending":
                continue
            age = max(0, int(now.timestamp() - path.stat().st_mtime))
            summary = re.sub(
                r"(?i)(?:token|secret|password|private[_ ]?key|authorization)\s*[:=][^\r\n]*",
                "[redigido]",
                approval.summary,
            )
            if "PRIVATE KEY" in summary:
                summary = "[redigido]"
            rows.append(
                {
                    "id": approval.id,
                    "kind": approval.kind,
                    "summary": summary[:240],
                    "max_exposure_cents": approval.max_exposure_cents,
                    "age_seconds": age,
                    "plan_hash_short": approval.plan_hash[:12],
                    "command": "arb approve sign " + shlex.quote(str(path)),
                    "expiry_suggestion": "Revisar proposta antiga; não expira automaticamente"
                    if age >= 86400
                    else "Revisar antes de assinar",
                }
            )
        except (OSError, ValueError):
            invalid += 1
    rows.sort(key=lambda row: (-row["max_exposure_cents"], -row["age_seconds"], row["id"]))
    return {"items": rows, "invalid": invalid}


def question(result):
    if result["items"]:
        row = result["items"][0]
        return f"Aprovar ou rejeitar a proposta {row['kind']} {row['id']}?"
    return "Manter a simulação até a próxima revisão?"
