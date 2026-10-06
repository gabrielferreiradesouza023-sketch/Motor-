from pathlib import Path

import pytest

from arb.bridge import build

CONTENT = (Path(__file__).resolve().parents[1] / "examples/bridge/content.txt").read_text()


def test_page_mobile_content_events_tracking_and_escaping(tmp_path, records):
    offer = records[0].model_copy(update={"name": "<script>fake</script>"})
    page = build(
        offer,
        CONTENT,
        "excel",
        worker_url="http://127.0.0.1:8787",
        pixel_id="123456",
        tracking_key="sck",
        output=tmp_path,
    )
    text = page.read_text()
    assert len(page.read_bytes()) < 100000
    assert '<html lang="es">' in text and 'name="viewport"' in text
    assert text.count("<button ") == 1
    assert "<script>fake</script>" not in text and "&lt;script&gt;fake" in text
    for event in ["PageView", "ViewContent", "InitiateCheckout", "checkout_click", "view"]:
        assert event in text
    assert "target.searchParams.set(config.tracking,ad)" in text


@pytest.mark.parametrize(
    "slug,url", [("../outside", "https://example.com"), ("excel", "http://example.com")]
)
def test_unsafe_path_or_url_refused(tmp_path, records, slug, url):
    with pytest.raises(ValueError):
        build(
            records[0],
            CONTENT,
            slug,
            worker_url=url,
            pixel_id="123",
            tracking_key="sck",
            output=tmp_path,
        )
