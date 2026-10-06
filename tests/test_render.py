import json
import subprocess
from pathlib import Path

import pytest
from test_plan import launch_fixture

from arb.creative import generate_angles
from arb.creative.copy import generate_copies
from arb.creative.render import capabilities, image, png_size, render_creative


@pytest.fixture(scope="module", autouse=True)
def require_render_tools():
    try:
        capabilities()
    except ValueError as exc:
        pytest.skip(str(exc))


def test_three_angles_three_creatives_real_render(tmp_path):
    offer, _, _ = launch_fixture()
    offer.name = "Curso de hojas de cálculo"
    renders = []
    for angle in generate_angles(offer, []):
        for creative in generate_copies(offer, angle, region="CO"):
            output = render_creative(creative, tmp_path)
            renders.append(output)
            assert [png_size(Path(p)) for p in output["images"]] == [
                (1080, 1350),
                (1080, 1920),
            ]
            if output["video"]:
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_streams",
                        "-show_format",
                        "-of",
                        "json",
                        output["video"],
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                data = json.loads(probe.stdout)
                stream = next(s for s in data["streams"] if s["codec_type"] == "video")
                assert (stream["width"], stream["height"], stream["codec_name"]) == (
                    1080,
                    1920,
                    "h264",
                )
                assert any(
                    s["codec_type"] == "audio" and s["codec_name"] == "aac" for s in data["streams"]
                )
                assert 11.9 <= float(data["format"]["duration"]) <= 12.1
                rights = Path(output["video"]).with_suffix(".rights.json")
                assert json.loads(rights.read_text())["third_party_recordings"] is False
    assert len(renders) == 9
    assert sum(r["video"] is not None for r in renders) == 3


def test_overflow_and_unlinted_copy_refused(tmp_path):
    offer, _, _ = launch_fixture()
    offer.name = "Curso"
    creative = generate_copies(offer, generate_angles(offer, [])[0])[0]
    creative.headline = "Palabra " * 200
    with pytest.raises(ValueError, match="zona segura"):
        image(creative, tmp_path)
    creative.policy_lint = "failed"
    with pytest.raises(ValueError, match="lint"):
        image(creative, tmp_path)
