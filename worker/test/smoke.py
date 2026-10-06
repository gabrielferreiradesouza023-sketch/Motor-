"""Smoke local: requer wrangler dev e tokens sintéticos definidos no README."""

import json
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8787"
ORIGIN = "http://127.0.0.1:8000"


def request(path, data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    req = Request(
        BASE + path, data=body, headers={"Content-Type": "application/json", **(headers or {})}
    )
    try:
        with urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main():
    assert request("/health")[1] == {"status": "ok"}
    event = {
        "id": str(uuid.uuid4()),
        "kind": "view",
        "ad_id": "example-ad",
        "geo": "CO",
        "ts": "2026-10-05T12:00:00Z",
    }
    assert request("/event", event, {"Origin": "https://evil.example"})[0] == 403
    assert request("/event", event, {"Origin": ORIGIN})[0] == 202
    assert request("/event", event, {"Origin": ORIGIN})[0] == 202
    invalid = event | {"id": str(uuid.uuid4()), "geo": "invalid"}
    assert request("/event", invalid, {"Origin": ORIGIN})[0] == 400
    sale = {
        "id": str(uuid.uuid4()),
        "hotmart_tx_id": "smoke-" + str(uuid.uuid4()),
        "ts": event["ts"],
        "commission_cents": 5000,
        "status": "approved",
        "tracking_param": "example-ad",
    }
    assert request("/sale", sale)[0] == 401
    assert request("/sale", sale, {"X-Hotmart-Hottok": "local-sale-fixture-only"})[0] == 202
    assert request("/export")[0] == 401
    exported = request(
        "/export?limit=500", headers={"Authorization": "Bearer local-sync-fixture-only"}
    )[1]
    assert sum(e["id"] == event["id"] for e in exported["events"]) == 1
    assert any(s["hotmart_tx_id"] == sale["hotmart_tx_id"] for s in exported["sales"])
    statuses = []
    for _ in range(61):
        statuses.append(request("/event", event | {"id": str(uuid.uuid4())}, {"Origin": ORIGIN})[0])
    assert 429 in statuses
    print("Worker smoke OK: D1, origem, autenticação, idempotência e rate limit")


if __name__ == "__main__":
    main()
