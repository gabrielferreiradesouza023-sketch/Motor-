from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arb.launcher import approval as approval_module
from arb.launcher.approval import public_hex
from arb.models import (
    Action,
    Angle,
    Approval,
    Creative,
    Decision,
    Entity,
    MetricSnapshot,
    Offer,
    SaleEvent,
)


@pytest.fixture
def records():
    ts = datetime(2026, 10, 5, 12, tzinfo=UTC)
    return [
        Offer(
            id="offer",
            hotmart_product_id="123",
            name="Excel",
            niche="excel_produtividade",
            language="es",
            commission_brl_cents=5000,
            price_local=10000,
            currency="BRL",
            allows_paid_traffic=True,
            sales_page_url="https://example.com/sales",
            affiliate_link="https://example.com/affiliate",
            score=70,
            status="candidate",
        ),
        Angle(
            id="angle",
            offer_id="offer",
            hypothesis="Prática",
            promise="Aprender",
            audience_pain="Tempo",
            hook_line="Planilhas",
            status="candidate",
        ),
        Creative(
            id="creative",
            angle_id="angle",
            format="image",
            copy_primary="Aprenda",
            headline="Excel",
            asset_path="assets/image.png",
            policy_lint="passed",
            status="candidate",
        ),
        Entity(
            id="entity",
            kind="ad",
            offer_id="offer",
            angle_id="angle",
            creative_id="creative",
            geo="CO",
            gate="1",
            daily_budget_cents=1000,
            status="paused",
        ),
        MetricSnapshot(
            entity_id="entity",
            ts=ts,
            impressions=1000,
            video_3s_views=0,
            link_clicks=20,
            spend_platform_cents=1000,
            bridge_views=19,
            checkout_clicks=3,
        ),
        SaleEvent(
            id="sale",
            source="csv",
            hotmart_tx_id="tx1",
            ts=ts,
            commission_cents=5000,
            status="approved",
            tracking_param="entity",
            matched_entity_id="entity",
        ),
        Decision(
            id="decision",
            ts=ts,
            entity_id="entity",
            gate="1",
            verdict="hold",
            metrics_json={"ctr_link": 0.02},
            rule_id="g1",
            reason="Exemplo de contrato",
        ),
        Approval(
            id="approval",
            plan_hash="a" * 64,
            kind="launch",
            summary="Teste local",
            max_exposure_cents=1000,
            status="pending",
        ),
        Action(
            id="action",
            ts=ts,
            actor="agent:codex",
            kind="example",
            payload_json={"input": {}, "output": {}},
            approval_id="approval",
            live=False,
            result="simulated",
        ),
    ]


SYNTHETIC_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
SYNTHETIC_PUBLIC_HEX = public_hex(SYNTHETIC_PRIVATE_KEY)
REAL_CONFIGURED_PUBLIC_KEY = approval_module.configured_public_key


@pytest.fixture(autouse=True)
def synthetic_approval_key(monkeypatch, tmp_path_factory):
    """Par Ed25519 sintético e determinístico; nunca uma chave de produção.

    A chave privada fica em arquivo 0600 fora do repo; a pública substitui a de
    config/settings.yaml (que é null até o humano gerar a sua).
    """
    path = tmp_path_factory.mktemp("human") / "approval_ed25519"
    path.write_text(SYNTHETIC_PRIVATE_KEY.private_bytes_raw().hex() + "\n")
    path.chmod(0o600)
    monkeypatch.setenv("APPROVAL_PRIVATE_KEY_FILE", str(path))
    monkeypatch.setattr(
        approval_module,
        "configured_public_key",
        lambda settings=None: SYNTHETIC_PRIVATE_KEY.public_key(),
    )


def pinned_rules():
    """Regras com G3 anterior ao ADR-018 (2× teto, 3 vendas).

    Testes de lógica e o histórico `planted` foram escritos com esses valores; fixá-los
    mantém os limites exatos independentes da calibração vigente em rules.yaml.
    """
    from arb.rules import load_rules

    rules = load_rules()
    return rules.model_copy(
        update={
            "gate_3": rules.gate_3.model_copy(
                update={"commission_cap_multiplier": 2, "min_sales": 3}
            )
        }
    )
