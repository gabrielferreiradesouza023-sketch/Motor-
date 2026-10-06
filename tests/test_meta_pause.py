import httpx
import pytest
from test_execute import setup_launch

from arb import safety
from arb.db import Repository
from arb.launcher.actions import pause
from arb.launcher.execute import execute
from arb.launcher.panic import panic
from arb.meta.pause import MetaPauseError, PauseWriter
from arb.models import Action, Entity

TOKEN = "synthetic-meta-pause-token"  # pragma: allowlist secret (synthetic test fixture)


@pytest.fixture
def permitted(monkeypatch):
    monkeypatch.setattr(safety, "live_mode", lambda: True)


def test_exact_payload_idempotent_and_hidden_token(permitted):
    seen = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: seen.append(r) or httpx.Response(200, json={"success": True})
        ),
        trust_env=False,
    ) as client:
        writer = PauseWriter(TOKEN, "v99.0", client)
        assert writer.pause("123")["status"] == "paused"
        assert writer.pause("123")["status"] == "already_paused"
        assert writer.pause("456", already_paused=True)["status"] == "already_paused"
        assert len(seen) == 1
        request = seen[0]
        assert (
            request.method == "POST" and str(request.url) == "https://graph.facebook.com/v99.0/123"
        )
        assert request.content == b"status=PAUSED"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in repr(writer)


@pytest.mark.parametrize("fields", [{"status": "ACTIVE"}, {}, {"status": "PAUSED", "budget": 10}])
def test_other_fields_impossible(fields):
    with pytest.raises(ValueError, match="única escrita"):
        PauseWriter(TOKEN, "v99.0").pause("123", fields=fields)


def test_false_never_constructs_real_transport(monkeypatch):
    monkeypatch.setattr(safety, "live_mode", lambda: False)

    def forbidden(*args, **kwargs):
        raise AssertionError("transporte real proibido")

    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "HTTPTransport", forbidden)
    assert PauseWriter(TOKEN, "v99.0").pause("123") == {"status": "disabled"}
    with pytest.raises(ValueError, match="LIVE_MODE=false"):
        PauseWriter.from_environment()


@pytest.mark.parametrize(
    "status,body",
    [
        (400, {"error": {"code": 190, "message": TOKEN}}),
        (400, {"error": {"code": 100, "message": TOKEN}}),
        (503, {"error": {"message": TOKEN}}),
        (302, {}),
        (200, {"success": False}),
        (200, []),
    ],
)
def test_failures_sanitized_without_retry(permitted, status, body):
    seen = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: seen.append(r) or httpx.Response(status, json=body)
        ),
        trust_env=False,
    ) as client:
        with pytest.raises(MetaPauseError) as error:
            PauseWriter(TOKEN, "v99.0", client).pause("123")
        assert TOKEN not in str(error.value) and len(seen) == 1
        if status == 400 and isinstance(body, dict) and body.get("error", {}).get("code") == 190:
            assert "190" in str(error.value)


def test_invalid_json_and_transport(permitted):
    for response in (httpx.Response(200, text=TOKEN), None):

        def handler(request, response=response):
            if response is None:
                raise httpx.ReadTimeout(TOKEN, request=request)
            return response

        with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
            with pytest.raises(MetaPauseError) as error:
                PauseWriter(TOKEN, "v99.0", client).pause("123")
            assert TOKEN not in str(error.value)


def test_panic_mixed_entities_audits_before_http(tmp_path, monkeypatch):
    conn, value, approval, directory = setup_launch(tmp_path)
    execute(conn, value, approval.id, approval_dir=directory, output=tmp_path / "out")
    entities = value.entities
    with conn:
        for i, meta_id in [(0, None), (1, "123"), (5, "124")]:
            entity = entities[i].model_copy(update={"status": "active", "meta_id": meta_id})
            Repository(conn, Entity).update(entity)
    monkeypatch.setattr(safety, "live_mode", lambda: True)
    seen = []

    def handler(request):
        seen.append(request)
        assert any(
            a.result == "intent"
            and a.payload_json.get("meta_id") == request.url.path.rsplit("/", 1)[-1]
            for a in Repository(conn, Action).list()
        )
        return (
            httpx.Response(200, json={"success": True})
            if request.url.path.endswith("/123")
            else httpx.Response(503, text=TOKEN)
        )

    try:
        with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
            writer = PauseWriter(TOKEN, "v99.0", client)
            result = panic(conn, writer=writer)
            assert result["paused_local"] == 1 and result["paused_remote"] == 1
            assert result["errors"] == [entities[5].id]
            assert result["remote_pause_pending"] == [] and result["mode"] == "live"
            assert pause(conn, entities[1].id, reason="repetição", writer=writer) is None
        assert len(seen) == 2
        assert Repository(conn, Entity).get(entities[1].id).status == "paused"
        assert Repository(conn, Entity).get(entities[5].id).status == "active"
        actions = Repository(conn, Action).list()
        assert any(a.result == "uncertain" for a in actions)
        assert TOKEN not in "\n".join(a.model_dump_json() for a in actions)
    finally:
        conn.close()
