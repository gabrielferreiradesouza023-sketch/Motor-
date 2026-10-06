import httpx
from test_execute import setup_launch

from arb.db import Repository
from arb.models import Action, SaleEvent
from arb.scheduler.alerts import Telegram, collect, dispatch


def test_pending_unmatched_and_disabled_by_default(tmp_path, records):
    conn, _, _, _ = setup_launch(tmp_path)
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    pending = records[7]
    (pending_dir / "pending.json").write_text(pending.model_dump_json())
    (pending_dir / "broken.json").write_text("{}")
    with conn:
        Repository(conn, SaleEvent).add(records[5].model_copy(update={"matched_entity_id": None}))
    try:
        messages = collect(conn, ["emergency: freio", "stale: atrasados"], approval_dir=pending_dir)
        assert len(messages) == 5
        assert any(m.startswith("unmatched_sales:") for m in messages)
        assert any(m.startswith("approval_pending:") for m in messages)

        def forbidden(_):
            raise AssertionError("não enviar")

        first = dispatch(conn, "cycle", messages, sender=forbidden)
        assert first["status"] == "disabled"
        assert dispatch(conn, "cycle", messages, sender=forbidden) == first
        assert len(Repository(conn, Action).list()) == 1
        assert not Repository(conn, Action).list()[0].live
    finally:
        conn.close()


def test_telegram_mock_success_and_sanitized_audit(tmp_path):
    conn, _, _, _ = setup_launch(tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    token = "12345:synthetic_fixture_only"  # pragma: allowlist secret (synthetic test fixture)
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            sender = Telegram(client, token, "123")
            result = dispatch(conn, "cycle", ["stale: dados atrasados"], sender=sender, send=True)
            assert result["status"] == "sent"
            assert (
                dispatch(conn, "cycle", ["stale: dados atrasados"], sender=sender, send=True)
                == result
            )
        assert len(calls) == 1
        assert token not in repr(sender)
        assert token not in "\n".join(a.model_dump_json() for a in Repository(conn, Action).list())
    finally:
        conn.close()


def test_uncertain_delivery_never_auto_retried(tmp_path):
    conn, _, _, _ = setup_launch(tmp_path)
    calls = []

    def broken(messages):
        calls.append(messages)
        raise RuntimeError("error may contain credentials; must not persist")

    try:
        result = dispatch(conn, "cycle", ["emergency: freio"], sender=broken, send=True)
        assert result["status"] == "uncertain"
        assert dispatch(conn, "cycle", ["emergency: freio"], sender=broken, send=True) == result
        assert len(calls) == 1
        assert "credentials" not in "\n".join(
            a.model_dump_json() for a in Repository(conn, Action).list()
        )
    finally:
        conn.close()


def test_telegram_redirect_error_not_followed():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.invalid"})

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        sender = Telegram(
            client, "12345:synthetic_fixture_only", "123"
        )  # pragma: allowlist secret (synthetic test fixture)
        assert not sender(["stale: dados atrasados"])
    assert len(calls) == 1
