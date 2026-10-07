"""Kits para o host humano. Cloud só exercita com MockTransport."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from arb import safety
from arb.permissions import inspect_paths, private_open
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
