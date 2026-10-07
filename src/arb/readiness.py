"""Prontidão baseada em evidência local; não habilita live nem consulta rede."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arb import preflight, service
from arb.launcher.approval import configured_public_key
from arb.permissions import inspect_paths, reject_links
from arb.rules import load_rules

HUMAN_ITEMS = tuple(f"V-{n:02d}" for n in range(1, 7)) + (
    "card_limit",
    "spend_cap",
    "persistent_host",
    "service_installed",
)
PROOF_CHECKS = {
    "f5": {
        "graph_version",
        "permissions",
        "account_brl_sao_paulo",
        "insights_read",
        "ads_read",
        "spend_cap",
    },
    "f6_pause": {"observed_paused"},
    "tracking": {"event_ack", "test_receipt", "csv_matched", "production_unchanged"},
}


def read_json(path):
    reject_links(path)
    return json.loads(path.read_text())


def fresh(stamp, now, *, days=7):
    if not isinstance(stamp, str):
        return False
    try:
        value = datetime.fromisoformat(stamp)
        return value.utcoffset() is not None and timedelta(0) <= now - value <= timedelta(days=days)
    except ValueError:
        return False


def proof(path, kind, now, *, cap=None):
    try:
        document = read_json(path)
        hashed = document.pop("sha256")
        actual = hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        checks = document["checks"]
        if (
            type(document["schema"]) is not int
            or document["schema"] != 1
            or document["kind"] != kind
            or document["status"] != "passed"
            or not fresh(document["checked_at"], now)
            or actual != hashed
            or not checks
            or {c["name"] for c in checks} != PROOF_CHECKS[kind]
            or len(checks) != len(PROOF_CHECKS[kind])
            or any(c["ok"] is not True for c in checks)
        ):
            return False
        if kind == "f5":
            return (
                bool(re.fullmatch(r"v[0-9]+\.[0-9]+", document["graph_version"]))
                and type(document["spend_cap_cents"]) is int
                and cap is not None
                and 0 < document["spend_cap_cents"] <= cap
            )
        if kind == "f6_pause":
            return document["before"] in {"ACTIVE", "PAUSED"} and document["after"] == "PAUSED"
        return document["synthetic"] is True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def confirmations(root, now):
    try:
        document = read_json(root / "ops/validation-status.json")
        if (
            type(document["schema"]) is not int
            or document["schema"] != 1
            or set(document["items"]) != set(HUMAN_ITEMS)
        ):
            raise ValueError("registro humano inválido")
        return {
            name: isinstance(row, dict)
            and row.get("status") == "confirmed"
            and row.get("by") == "human"
            and fresh(row.get("checked_at"), now)
            and isinstance(row.get("evidence"), str)
            and bool(row["evidence"].strip())
            for name, row in document["items"].items()
        }
    except (OSError, ValueError, KeyError, TypeError):
        return dict.fromkeys(HUMAN_ITEMS, False)


def inspect(*, root=Path("."), now=None):
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("prontidão requer timestamp com fuso")
    items = []

    def record(name, ok, reason, next_step):
        items.append(
            {
                "name": name,
                "ok": bool(ok),
                "reason": "verificado" if ok else reason,
                "next_step": "" if ok else next_step,
            }
        )

    safe_config = True
    cap = None
    try:
        for name in ("settings.yaml", "rules.yaml"):
            reject_links(root / "config" / name)
        cap = load_rules(root / "config/rules.yaml").controls.total_cap_cents
    except (OSError, ValueError):
        safe_config = False
    human = confirmations(root, now)
    proofs = {
        kind: proof(root / f"ops/validation/{kind}.json", kind, now, cap=cap)
        for kind in PROOF_CHECKS
    }
    # Preflight continua sem rede. Uma evidência F5 íntegra + confirmação humana pode
    # satisfazer só o check remoto do spend_cap, jamais substituir outros erros locais.
    try:
        if not safe_config:
            raise ValueError("configuração insegura")
        local = preflight.inspect(root=root, now=now, allow_meta_read=False)
        errors = [
            c["name"]
            for c in local["checks"]
            if c["status"] == "erro"
            and not (c["name"] == "meta_spend_cap" and proofs["f5"] and human["spend_cap"])
        ]
    except Exception:
        errors = ["indisponível"]
    record(
        "preflight",
        not errors,
        "Preflight pendente: " + ", ".join(errors),
        "Humano: corrigir arb preflight no host; aceite F5 fornece evidência da leitura remota",
    )
    try:
        drill = read_json(root / "data/backups/drill.json")
        drill_ok = drill["status"] == "passed" and fresh(drill["checked_at"], now, days=2)
    except (OSError, ValueError, KeyError, TypeError):
        drill_ok = False
    record(
        "drill_recent",
        drill_ok,
        "Drill de backup ausente/falho ou mais antigo que 48h",
        "Executar arb db backup e arb db drill no host, sem sobrescrever produção",
    )
    privacy = inspect_paths(root)
    record(
        "permissions",
        privacy["ok"] and not privacy["warnings"],
        "Modos/symlinks inadequados ou ACLs ainda não verificáveis",
        "Humano: fechar permissões; usar host Linux/WSL e validar ACLs quando aplicável",
    )
    try:
        if not safe_config:
            raise ValueError("configuração insegura")
        configured_public_key(root / "config/settings.yaml")
        public_ok = True
    except (OSError, ValueError):
        public_ok = False
    record(
        "approval_public_key",
        public_ok,
        "Chave pública ausente/inválida; privada nunca consultada",
        "Revisar chave pública existente via PR; manter privada apenas no host do signatário",
    )
    for kind in PROOF_CHECKS:
        record(
            kind,
            proofs[kind],
            "Aceite humano ausente, inválido, falho ou antigo (>7 dias)",
            f"Humano: executar kit {kind}; revisar ops/validation/{kind}.json no próprio host",
        )
    for name in HUMAN_ITEMS[:6]:
        record(
            name,
            human[name],
            "Validação do provedor ainda não registrada pelo humano",
            f"Humano: resolver {name}; versionar data/referência em ops/validation-status.json",
        )
    record(
        "graph_executor",
        False,
        "T-55: executor de exposição Graph ausente; somente FakeMeta",
        "Humano: resolver V-06 e aprovar contrato; executor exige implementação/revisão separada",
    )
    # CARD_LIMIT_CENTS é limite público, não credencial; preflight valida seu valor e teto.
    card_ok = human["card_limit"] and not errors and proofs["f5"]
    record(
        "card_limit",
        card_ok,
        "Limite do cartão não confirmado ou preflight/teto pendente",
        "Humano: confirmar teto no emissor e declarar CARD_LIMIT_CENTS <= total_cap_cents",
    )
    record(
        "spend_cap",
        human["spend_cap"] and proofs["f5"],
        "spend_cap real não confirmado dentro do teto",
        "Humano: configurar limite Meta e revisar prova F5; registrar confirmação sem credenciais",
    )
    record(
        "persistent_host",
        human["persistent_host"],
        "Host persistente ainda não confirmado",
        "Humano: selecionar e validar disponibilidade, disco privado, relógio e backups do host",
    )
    try:
        package_ok = safe_config and service.check(output=root / "data/service")["ok"]
    except Exception:
        package_ok = False
    record(
        "service_package",
        package_ok,
        "Pacote de serviço ausente/inválido; nenhuma instalação executada",
        "Renderizar arb service render e verificar arb service check no host correto",
    )
    record(
        "service_installed",
        human["service_installed"] and package_ok,
        "Instalação/disponibilidade do serviço ainda não confirmada pelo humano",
        "Humano: revisar pacote, instalar no próprio host e registrar evidência de disponibilidade",
    )
    ready = all(item["ok"] for item in items)
    return {
        "ready": ready,
        "status": "pronto" if ready else "não pronto",
        "checked_at": now.astimezone(UTC).isoformat(),
        "items": items,
        "pending": [item["name"] for item in items if not item["ok"]],
    }
