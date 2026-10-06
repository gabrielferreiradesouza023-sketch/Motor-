from datetime import date

import httpx
import pytest

from arb.meta.read import MetaReadError, Reader


def make(respond, pauses=None):
    client = httpx.Client(transport=httpx.MockTransport(respond))
    return Reader("synthetic", "123", "v99.0", client=client, sleep=(pauses or []).append)


def test_pagination_ignores_next_url_and_is_only_get():
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET" and request.url.host == "graph.facebook.com"
        assert "access_token" not in request.url.params
        if "after" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "data": [{"ad_id": "a"}],
                    "paging": {
                        "next": "https://evil.example/?access_token=do-not-follow",
                        "cursors": {"after": "cursor"},
                    },
                },
            )
        return httpx.Response(200, json={"data": [{"ad_id": "b"}]})

    reader = make(respond)
    assert reader.insights(date(2026, 10, 1), date(2026, 10, 2)) == [{"ad_id": "a"}, {"ad_id": "b"}]
    assert len(requests) == 2


def test_retry_rate_limit_and_account():
    pauses = []
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    reader = Reader(
        "synthetic",
        "123",
        "v99.0",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
        sleep=pauses.append,
    )
    assert reader.account()["currency"] == "BRL"
    assert pauses == [2]


def test_expired_token_no_retry_and_sanitized():
    reader = make(
        lambda r: httpx.Response(
            400, json={"error": {"code": 190, "message": "synthetic-secret-must-not-leak"}}
        )
    )
    with pytest.raises(MetaReadError, match="190") as caught:
        reader.ads()
    assert "synthetic-secret-must-not-leak" not in str(caught.value)


def test_bad_account_and_cursor_refused():
    reader = make(lambda r: httpx.Response(200, json={"currency": "USD", "timezone_name": "UTC"}))
    with pytest.raises(MetaReadError, match="BRL"):
        reader.account()
    reader = make(
        lambda r: httpx.Response(
            200, json={"data": [], "paging": {"next": "bad", "cursors": {"after": "same"}}}
        )
    )
    with pytest.raises(MetaReadError, match="cursor"):
        reader.ads()


def test_missing_configuration_and_transport_failure():
    with pytest.raises(ValueError):
        Reader("", "123", "v99.0")
    with pytest.raises(ValueError):
        Reader("synthetic", "123", "")

    def failed(request):
        raise httpx.ConnectError("hidden", request=request)

    reader = make(failed)
    with pytest.raises(MetaReadError, match="transporte"):
        reader.account()
