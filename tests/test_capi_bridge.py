"""Synthetic browser/network fixtures; no Facebook or affiliate requests."""

import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from test_bridge import CONTENT

from arb.bridge import build
from arb.creative.render import capabilities
from arb.tracker.sync import decode_event


def test_pixel_and_server_share_the_actual_click_nonce(tmp_path, records):
    page_file = build(
        records[0],
        CONTENT,
        "capi",
        worker_url="https://worker.example",
        pixel_id="123",
        tracking_key="sck",
        output=tmp_path,
        capi_enabled=True,
    )
    captured = []
    with sync_playwright() as browser:
        instance = browser.chromium.launch(
            executable_path=capabilities()["chromium"], args=["--no-sandbox"]
        )
        page = instance.new_page()
        page.add_init_script("window.calls=[];window.fbq=(...args)=>window.calls.push(args);")

        def route(request):
            if request.request.url.startswith("https://worker.example/event"):
                if request.request.method == "POST":
                    captured.append(json.loads(request.request.post_data))
                request.fulfill(
                    status=202 if request.request.method == "POST" else 204,
                    headers={
                        "Access-Control-Allow-Origin": "http://localhost",
                        "Access-Control-Allow-Headers": "Content-Type",
                    },
                    body="",
                )
            elif request.request.url.startswith("http://localhost/"):
                request.fulfill(
                    body=page_file.read_text().replace("location.assign(target.toString());", ""),
                    content_type="text/html",
                )
            else:
                request.fulfill(body="", content_type="text/html")

        page.route("**/*", route)
        page.goto("http://localhost/?ad=ad1&geo=CO")
        with page.expect_request(
            lambda r: (
                r.url == "https://worker.example/event"
                and r.method == "POST"
                and "checkout_click" in (r.post_data or "")
            )
        ):
            page.click("#checkout")
        page.wait_for_timeout(100)
        pixel = page.evaluate("window.calls.filter(c=>c[1]==='InitiateCheckout')")
        instance.close()
    checkout = [event for event in captured if event["kind"] == "checkout_click"]
    assert len(checkout) == 1
    assert pixel[0][3]["eventID"] == checkout[0]["event_id"] == checkout[0]["id"]
    assert decode_event(checkout[0])[0].id == checkout[0]["event_id"]


@pytest.mark.parametrize("patch", [{"event_id": "wrong"}, {"kind": "view"}])
def test_tracker_refuses_inconsistent_dedup_nonce(patch):
    event = dict(
        id="nonce",
        event_id="nonce",
        kind="checkout_click",
        ad_id="ad1",
        geo="CO",
        ts="2026-10-05T12:00:00Z",
    )
    with pytest.raises(ValueError, match="event_id"):
        decode_event(event | patch)


def test_disabled_capi_keeps_versioned_html(tmp_path, records):
    file = build(
        records[0],
        CONTENT,
        "old",
        worker_url="https://worker.example",
        pixel_id="123",
        tracking_key="sck",
        output=tmp_path,
    )
    assert file.read_bytes() == Path("tests/fixtures/bridge-default-t61.html").read_bytes()
