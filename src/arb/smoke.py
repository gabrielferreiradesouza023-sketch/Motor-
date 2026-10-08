"""Campanhas humanas: registro local, leitura e alertas; nunca RemoteWriter."""

import re
from datetime import UTC, datetime
from uuid import uuid4

from arb.db import Repository
from arb.metrics import divide, spend_gross
from arb.models import Action, Entity, MetricAdjustment, MetricSnapshot, Offer, SaleEvent


def ids(connection, campaign=None) -> set[str]:
    rows = connection.execute(
        "WITH RECURSIVE protected(id) AS ("
        "SELECT entity_id FROM smoke_entities WHERE (? IS NULL OR campaign_id=?) "
        "UNION SELECT e.id FROM entities e JOIN protected p ON e.parent_id=p.id) "
        "SELECT id FROM protected",
        (campaign, campaign),
    )
    return {row[0] for row in rows}


def require_automatic(connection, entity_id):
    protected = ids(connection)
    if not protected:
        return
    family = {entity_id}
    entities = Repository(connection, Entity).list()
    while True:
        expanded = family | {e.id for e in entities if e.parent_id in family}
        if expanded == family:
            break
        family = expanded
    if family & protected:
        raise ValueError("smoke: operação exclusivamente humana; não é aceite F6")


def register(connection, campaign, adset, ads, offer_id, geo, cap_cents, *, now=None):
    if connection.in_transaction:
        raise ValueError("registro exige commit anterior")
    identifiers = [campaign, adset, *ads]
    if (
        not ads
        or any(not isinstance(i, str) or not re.fullmatch(r"[0-9]+", i) for i in identifiers)
        or len(set(identifiers)) != len(identifiers)
        or not re.fullmatch(r"[A-Z]{2}", geo)
        or type(cap_cents) is not int
        or cap_cents <= 0
    ):
        raise ValueError("ids/geo/teto smoke inválidos ou duplicados")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if Repository(connection, Offer).get(offer_id) is None:
            raise ValueError("oferta desconhecida")
        existing = Repository(connection, Entity).list()
        if any(
            e.meta_id in identifiers or e.id in {"meta-" + i for i in identifiers} for e in existing
        ):
            raise ValueError("ids já registrados")
        for index, remote_id in enumerate(identifiers):
            kind = "campaign" if index == 0 else "adset" if index == 1 else "ad"
            parent = None if index == 0 else "meta-" + (campaign if index == 1 else adset)
            Repository(connection, Entity).add(
                Entity(
                    id="meta-" + remote_id,
                    meta_id=remote_id,
                    kind=kind,
                    parent_id=parent,
                    offer_id=offer_id,
                    geo=geo,
                    gate="0",
                    daily_budget_cents=0,
                    status="paused",
                )
            )
        connection.execute(
            "INSERT INTO smoke_campaigns VALUES (?,?)", ("meta-" + campaign, cap_cents)
        )
        connection.executemany(
            "INSERT INTO smoke_entities VALUES (?,?)",
            [("meta-" + i, "meta-" + campaign) for i in identifiers],
        )
        Repository(connection, Action).add(
            Action(
                id="smoke-register-" + uuid4().hex,
                ts=now or datetime.now(UTC),
                actor="human",
                kind="smoke_register",
                live=False,
                result="registered_read_only",
                payload_json={
                    "campaign": campaign,
                    "adset": adset,
                    "ads": list(ads),
                    "offer": offer_id,
                    "geo": geo,
                    "cap_cents": cap_cents,
                    "acceptance_f6": False,
                },
            )
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {
        "campaign_id": "meta-" + campaign,
        "entities": sorted(ids(connection, "meta-" + campaign)),
    }


def record_invoice(connection, campaign, platform_cents, total_cents, evidence_ref, *, now=None):
    if connection.in_transaction:
        raise ValueError("fatura exige commit anterior")
    if (
        type(platform_cents) is not int
        or platform_cents <= 0
        or type(total_cents) is not int
        or total_cents < 0
        or not evidence_ref.strip()
    ):
        raise ValueError("fatura/evidência inválida")
    if not connection.execute(
        "SELECT 1 FROM smoke_campaigns WHERE campaign_id=?", (campaign,)
    ).fetchone():
        raise ValueError("campanha smoke desconhecida")
    with connection:
        Repository(connection, Action).add(
            Action(
                id="smoke-invoice-" + uuid4().hex,
                ts=now or datetime.now(UTC),
                actor="human",
                kind="smoke_invoice",
                live=False,
                result="recorded_local",
                payload_json={
                    "campaign_id": campaign,
                    "platform_cents": platform_cents,
                    "total_cents": total_cents,
                    "evidence_ref": evidence_ref,
                },
            )
        )


def report(connection, campaign=None, *, media_tax_rate=0.13):
    if (
        campaign is not None
        and not connection.execute(
            "SELECT 1 FROM smoke_campaigns WHERE campaign_id=?", (campaign,)
        ).fetchone()
    ):
        raise ValueError("campanha smoke desconhecida")
    snapshots = Repository(connection, MetricSnapshot).list()
    adjustments = Repository(connection, MetricAdjustment).list()
    sales = Repository(connection, SaleEvent).list()
    actions = Repository(connection, Action).list()
    excluded = {r[0] for r in connection.execute("SELECT entity_id FROM acceptance_test_entities")}
    campaigns = []
    roots = {r[0] for r in connection.execute("SELECT campaign_id FROM smoke_campaigns")}
    entity_map = {e.id: e for e in Repository(connection, Entity).list()}

    def owner(entity):
        seen = set()
        while entity is not None and entity.id not in seen:
            if entity.id in roots:
                return entity.id
            seen.add(entity.id)
            entity = entity_map.get(entity.parent_id)
        return None  # Original binding remains if no registered root is observed.

    for identifier, cap in connection.execute(
        "SELECT campaign_id,cap_cents FROM smoke_campaigns "
        "WHERE (? IS NULL OR campaign_id=?) ORDER BY campaign_id",
        (campaign, campaign),
    ):
        family = ids(connection, identifier) - excluded
        entities = Repository(connection, Entity).list()
        leaves = {
            e.id
            for e in entities
            if e.id in family and e.kind == "ad" and owner(e) in (None, identifier)
        }
        counters = {
            key: sum(getattr(s, key) for s in snapshots if s.entity_id in leaves)
            + sum(a.deltas.get(key, 0) for a in adjustments if a.entity_id in leaves)
            for key in (
                "impressions",
                "video_3s_views",
                "link_clicks",
                "spend_platform_cents",
                "bridge_views",
                "checkout_clicks",
            )
        }
        matched = [s for s in sales if s.matched_entity_id in leaves]
        invoices = sorted(
            [
                a
                for a in actions
                if a.kind == "smoke_invoice"
                and a.actor == "human"
                and a.payload_json.get("campaign_id") == identifier
            ],
            key=lambda a: (a.ts, a.id),
        )
        invoice = invoices[-1].payload_json if invoices else None
        observed_tax = (
            divide(invoice["total_cents"], invoice["platform_cents"]) - 1
            if invoice and invoice["platform_cents"] == counters["spend_platform_cents"]
            else None
        )
        gross = spend_gross(counters["spend_platform_cents"], media_tax_rate)
        alerts = (
            [f"smoke_cap_reached: {identifier}; pausar manualmente; motor não opera fumaça"]
            if max(gross, invoice["total_cents"] if observed_tax is not None else 0) >= cap
            else []
        )
        campaigns.append(
            {
                "campaign_id": identifier,
                "cap_cents": cap,
                **counters,
                "spend_gross": gross,
                "gross_basis": "configured_tax_estimate",
                "cpm_gross": divide(gross * 1000, counters["impressions"]),
                "ctr_link": divide(counters["link_clicks"], counters["impressions"]),
                "hook_rate": divide(counters["video_3s_views"], counters["impressions"]),
                "bridge_checkout_rate": divide(
                    counters["checkout_clicks"], counters["bridge_views"]
                ),
                "matched_sales": sum(s.status == "approved" for s in matched),
                "matched_transactions": len(matched),
                "implicit_tax_rate": observed_tax,
                "checklist": {
                    "V-02": "observado" if any(s.tracking_param for s in matched) else "pendente",
                    "V-04": "observado" if observed_tax is not None else "pendente",
                },
                "alerts": alerts,
                "acceptance_f6": False,
            }
        )
    return {
        "campaigns": campaigns,
        "unmatched_sales_bank": sum(
            s.status == "approved" and s.matched_entity_id is None for s in sales
        ),
        "unmatched_scope": "banco inteiro; não atribuíveis à campanha",
        "signed_acceptance": False,
    }


def markdown(value):
    lines = [
        "# Teste-fumaça — observação local",
        "",
        "Observado não é aceite assinado nem F6. Não pronto para dinheiro real.",
        "",
    ]
    for row in value["campaigns"]:
        lines += [
            f"## {row['campaign_id']}",
            "",
            f"Gasto bruto estimado: {row['spend_gross']} centavos; "
            f"vendas casadas: {row['matched_sales']}.",
            f"CPM bruto: {row['cpm_gross']}; CTR: {row['ctr_link']}; hook: {row['hook_rate']}.",
            f"Ponte→checkout: {row['bridge_checkout_rate']}; imposto implícito: "
            f"{row['implicit_tax_rate']}.",
            f"V-02: {row['checklist']['V-02']}; V-04: {row['checklist']['V-04']}.",
            *row["alerts"],
            "",
        ]
    lines += [
        f"Vendas não casadas no banco: {value['unmatched_sales_bank']}; atribuição desconhecida.",
        "",
    ]
    return "\n".join(lines)
