"""Kits para o host humano. Cloud só exercita com MockTransport."""

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from arb import safety
from arb.launcher import approval
from arb.permissions import inspect_paths, private_open, reject_links
from arb.rules import load_rules


def require_host():
    if not safety.live_mode():
        raise ValueError("kit de aceite exige LIVE_MODE=true no host humano; cloud só usa mocks")


def suffix(identifier):
    value = str(identifier).removeprefix("act_")
    return "…" + value[-4:] if len(value) > 4 else "[redigido]"


def evidence(kind, checks, *, now=None, **facts):
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("evidência exige timestamp com fuso")
    body = {
        "schema": 1,
        "kind": kind,
        "checked_at": now.astimezone(UTC).isoformat(),
        "status": "passed" if all(row["ok"] for row in checks) else "failed",
        "checks": checks,
        **facts,
    }
    body["sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return body


def save(body, out: Path):
    with private_open(out, exclusive=True) as file:
        file.write(json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return out


def f5(reader, *, root: Path = Path("."), now=None):
    require_host()
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("aceite requer fuso")
    checks = []

    def record(name, ok):
        checks.append(
            {
                "name": name,
                "ok": bool(ok),
                "message": "verificado"
                if ok
                else "falhou; corrigir no host humano, detalhes externos omitidos",
            }
        )

    version = reader.base.rsplit("/", 1)[-1]
    record("graph_version", bool(re.fullmatch(r"v[0-9]+\.[0-9]+", version)))
    privacy = inspect_paths(root)
    record("permissions", privacy["ok"])
    if not privacy["ok"]:
        return evidence(
            "f5", checks, now=now, graph_version=version, account_suffix=suffix(reader.account_id)
        )
    try:
        reader.account()
        account_ok = True
    except Exception:
        account_ok = False
    record("account_brl_sao_paulo", account_ok)
    until = now.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    try:
        reader.insights(until - timedelta(days=1), until)
        insights_ok = True
    except Exception:
        insights_ok = False
    record("insights_read", insights_ok)
    try:
        reader.ads()
        ads_ok = True
    except Exception:
        ads_ok = False
    record("ads_read", ads_ok)
    amount = 0
    try:
        cap = load_rules(root / "config/rules.yaml").controls.total_cap_cents
        raw = reader.get(reader.account_id, {"fields": "spend_cap"}).get("spend_cap")
        amount = (
            int(raw)
            if type(raw) is int or (isinstance(raw, str) and raw.isascii() and raw.isdigit())
            else 0
        )
        cap_ok = account_ok and 0 < amount <= cap
    except Exception:
        cap_ok = False
    record("spend_cap", cap_ok)
    return evidence(
        "f5",
        checks,
        now=now,
        graph_version=version,
        account_suffix=suffix(reader.account_id),
        spend_cap_cents=amount if cap_ok else None,
        window={"since": (until - timedelta(days=1)).isoformat(), "until": until.isoformat()},
    )


def read_evidence(path: Path) -> dict:
    reject_links(path)
    body = json.loads(path.read_text())
    if not isinstance(body, dict) or body.get("kind") not in {"f5", "f6_pause", "tracking"}:
        raise ValueError("evidência de aceite inválida")
    unsigned = {key: value for key, value in body.items() if key not in {"signature", "sha256"}}
    if body.get("sha256") != hashlib.sha256(approval.canonical_document(unsigned)).hexdigest():
        raise ValueError("hash da evidência inválido")
    return body


def verify_evidence(path: Path, *, settings=approval.SETTINGS) -> dict:
    body = read_evidence(path)
    approval.verify_document(body, settings=settings)
    return body


def replace_document(path: Path, body: dict, original: str) -> None:
    """Publicação atômica 0600; recusa caminhos indiretos ou edição concorrente."""
    reject_links(path)
    if path.read_text() != original:
        raise ValueError("documento mudou durante a confirmação")
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".signed-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
        reject_links(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sign_evidence(path: Path, confirm) -> dict:
    if not approval.is_interactive():
        raise ValueError("assinatura exige tty interativo na máquina humana")
    body = read_evidence(path)
    original = path.read_text()
    if json.loads(original) != body:
        raise ValueError("documento mudou durante a leitura")
    if body.get("signature"):
        raise ValueError("evidência já assinada")
    if not confirm(f"Assinar evidência {body['kind']}; hash={body['sha256']}?"):
        raise ValueError("assinatura cancelada pelo humano")
    signed = approval.sign_document(body)
    replace_document(path, signed, original)
    return signed
