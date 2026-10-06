"""Páginas estáticas em espanhol; conteúdo e parâmetros fornecidos pelo operador."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, select_autoescape

from arb.models import Offer

TEMPLATE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ offer.name }}</title>
<style>body{font:18px/1.6 system-ui;color:#192532;background:#f7f8fa;margin:0}
main{max-width:680px;margin:auto;padding:24px}h1{line-height:1.2}
button{font:inherit;background:#14543e;color:white;border:0;border-radius:8px;padding:16px;
width:100%;cursor:pointer}footer{font-size:14px;color:#4a5360;margin-top:24px}</style></head>
<body><main><h1>{{ offer.name }}</h1>{% for paragraph in paragraphs %}
<p>{{ paragraph }}</p>{% endfor %}
<button id="checkout" type="button">Conocer el curso</button>
<footer>Enlace de afiliado: podemos recibir una comisión sin costo adicional para ti.
Esta página mide visitas y clics para mejorar su contenido. No promete resultados.</footer>
</main><script>
const config={{ config|tojson }};
const params=new URLSearchParams(location.search);
const ad=params.get('ad')||''; const geo=params.get('geo')||'CO';
const validAd=/^[A-Za-z0-9_-]{1,128}$/.test(ad);
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}
(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init',config.pixel);fbq('track','PageView');fbq('track','ViewContent');
function event(kind){if(!validAd)return;
const body={id:crypto.randomUUID(),kind,ad_id:ad,geo,ts:new Date().toISOString()};
fetch(config.worker+'/event',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify(body),keepalive:true}).catch(()=>{});}
event('view');
document.getElementById('checkout').addEventListener('click',()=>{
fbq('track','InitiateCheckout');event('checkout_click');
const target=new URL(config.affiliate);if(validAd)target.searchParams.set(config.tracking,ad);
location.assign(target.toString());});
</script></body></html>"""


def build(
    offer: Offer,
    content: str,
    slug: str,
    *,
    worker_url: str,
    pixel_id: str,
    tracking_key: str,
    output: Path = Path("bridges_out"),
) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("slug inválido")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", tracking_key):
        raise ValueError("parâmetro de rastreio inválido; confirmar V-02")
    worker = urlsplit(worker_url)
    if worker.scheme != "https" and not (
        worker.scheme == "http" and worker.hostname in ("localhost", "127.0.0.1")
    ):
        raise ValueError("Worker precisa de HTTPS ou localhost de teste")
    if worker.username or worker.password or worker.query or worker.fragment:
        raise ValueError("URL de Worker inválida")
    if str(offer.affiliate_link).startswith("http://") or not pixel_id.isdigit():
        raise ValueError("link de afiliado precisa de HTTPS e pixel de id numérico")
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if offer.language != "es" or len(content.split()) < 40 or len(paragraphs) < 2:
        raise ValueError(
            "Forneça conteúdo educativo em espanhol, pelo menos 40 palavras/2 parágrafos"
        )
    env = Environment(autoescape=select_autoescape(default_for_string=True))
    rendered = env.from_string(TEMPLATE).render(
        offer=offer,
        paragraphs=paragraphs,
        config={
            "pixel": pixel_id,
            "worker": worker_url.rstrip("/"),
            "affiliate": str(offer.affiliate_link),
            "tracking": tracking_key,
        },
    )
    if len(rendered.encode()) >= 100000:
        raise ValueError("Página excede 100 KB")
    path = output / slug / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered)
    return path
