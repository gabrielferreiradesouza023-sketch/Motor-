"""HTML local → PNG via Chromium; slides → H.264/AAC via ffmpeg. Sem downloads."""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from jinja2 import Environment
from playwright.sync_api import sync_playwright

from arb.creative.copy import lint_copy
from arb.models import Creative

SIZES = ((1080, 1350), (1080, 1920))
TEMPLATE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';
style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<style>
*{box-sizing:border-box}
html,body{margin:0;width:{{ width }}px;height:{{ height }}px;overflow:hidden}
body{background:#101e30;color:#f4f7fb;font-family:Arial,sans-serif}
main{position:absolute;left:120px;right:120px;top:200px;bottom:260px;
display:flex;flex-direction:column;justify-content:center;gap:40px}
h1{font-size:54px;line-height:1.15;margin:0;max-height:250px;overflow:hidden;overflow-wrap:anywhere}
p{font-size:34px;line-height:1.4;margin:0;max-height:440px;overflow:hidden;overflow-wrap:anywhere}
.cta{background:#a6efd9;color:#10292b;padding:22px;border-radius:18px;font-size:32px}
</style></head><body><main><h1 data-copy>{{ headline }}</h1><p data-copy>{{ primary }}</p>
<div class="cta" data-copy>Consultar información</div></main>
<script>
const box=document.querySelector('main').getBoundingClientRect();
const fits=[...document.querySelectorAll('[data-copy]')].every(e=>{
 const r=e.getBoundingClientRect();return e.scrollHeight<=e.clientHeight &&
 e.scrollWidth<=e.clientWidth && r.top>=200 && r.bottom<= {{ height }}-260 &&
 r.left>=120 && r.right<= {{ width }}-120;});
document.documentElement.dataset.layout=fits && box.top>=200?'ok':'overflow';
</script></body></html>"""


def capabilities() -> dict[str, str]:
    result = {}
    for name in ("chromium", "ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if path is None:
            raise ValueError(f"ferramenta local necessária: {name}")
        result[name] = path
    return result


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("imagem não é PNG")
    return struct.unpack(">II", header[16:24])


def image(creative: Creative, directory: Path, *, size: tuple[int, int] = (1080, 1350)) -> Path:
    if size not in SIZES:
        raise ValueError("dimensões não aprovadas")
    if creative.policy_lint != "passed" or lint_copy(
        creative.headline + "\n" + creative.copy_primary
    ):
        raise ValueError("copy precisa passar no lint antes de renderizar")
    width, height = size
    tools = capabilities()
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(creative.model_dump_json().encode()).hexdigest()[:20]
    target = directory / f"{identity}-{width}x{height}.png"
    html = (
        Environment(autoescape=True)
        .from_string(TEMPLATE)
        .render(
            width=width, height=height, headline=creative.headline, primary=creative.copy_primary
        )
    )
    with TemporaryDirectory(prefix="arb-render-") as temporary:
        env = os.environ | {
            "XDG_CONFIG_HOME": str(Path(temporary) / "config"),
            "XDG_CACHE_HOME": str(Path(temporary) / "cache"),
        }
        with sync_playwright() as driver:
            browser = driver.chromium.launch(
                executable_path=tools["chromium"],
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--host-resolver-rules=MAP * ~NOTFOUND",
                ],
                env=env,
                timeout=30000,
            )
            try:
                context = browser.new_context(
                    viewport={"width": width, "height": height}, device_scale_factor=1
                )
                context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                page.set_content(html, wait_until="load", timeout=15000)
                page.evaluate("document.fonts.ready")
                if page.locator("html").get_attribute("data-layout") != "ok":
                    raise ValueError("layout excede zona segura")
                page.screenshot(path=str(target), timeout=15000)
            finally:
                browser.close()
    if png_size(target) != size:
        target.unlink(missing_ok=True)
        raise ValueError("dimensões renderizadas divergentes")
    target.with_suffix(".html").write_text(html)
    return target


def video(creative: Creative, directory: Path) -> Path:
    tools = capabilities()
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(creative.model_dump_json().encode()).hexdigest()[:20]
    target = directory / f"{identity}-1080x1920.mp4"
    with TemporaryDirectory(prefix="arb-video-") as temporary:
        temporary = Path(temporary)
        slides = [
            creative,
            creative.model_copy(update={"headline": "Explora la propuesta"}),
            creative.model_copy(update={"headline": "Consulta la información"}),
        ]
        concat = []
        for index, slide in enumerate(slides):
            rendered = image(slide, temporary / "images", size=(1080, 1920))
            shutil.copyfile(rendered, temporary / f"slide-{index}.png")
            concat.extend([f"file 'slide-{index}.png'", "duration 4"])
        concat.append("file 'slide-2.png'")
        manifest = temporary / "slides.txt"
        manifest.write_text("\n".join(concat) + "\n")
        # Trilha original sintetizada pelo projeto; nenhum fonograma de terceiros.
        audio = "aevalsrc=0.012*(sin(2*PI*220*t)+sin(2*PI*277.18*t)+sin(2*PI*329.63*t)):s=48000"
        result = subprocess.run(
            [
                tools["ffmpeg"],
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(manifest),
                "-f",
                "lavfi",
                "-i",
                audio,
                "-vf",
                "fps=24,format=yuv420p",
                "-af",
                "afade=t=in:d=0.5,afade=t=out:st=11:d=1",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-threads",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-t",
                "12",
                "-movflags",
                "+faststart",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
    if result.returncode:
        target.unlink(missing_ok=True)
        raise ValueError("ffmpeg falhou ao renderizar vídeo")
    target.with_suffix(".rights.json").write_text(
        json.dumps(
            {
                "audio": "synthesized-original-triad",
                "license": "CC0-1.0",
                "author": "arb-engine project",
                "third_party_recordings": False,
                "safe_zone": {"left": 120, "right": 120, "top": 200, "bottom": 260},
            },
            indent=2,
        )
    )
    return target


def render_creative(creative: Creative, directory: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", creative.id):
        raise ValueError("id inválido")
    images = [image(creative, directory, size=size) for size in SIZES]
    clip = video(creative, directory) if creative.format == "video" else None
    return {
        "creative_id": creative.id,
        "images": [str(p) for p in images],
        "video": str(clip) if clip else None,
        "status": "candidate",
        "safe_zone": {"left": 120, "right": 120, "top": 200, "bottom": 260},
    }
