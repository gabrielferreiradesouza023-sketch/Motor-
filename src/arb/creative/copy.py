"""Copy editorial conservadora e lint determinístico; não substitui revisão de política."""

import hashlib
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from arb.config import Policy
from arb.creative import normalized
from arb.models import Angle, Creative, Offer

REGIONS = {
    "neutral": "Consulta la información antes de decidir.",
    "CO": "Si estás en Colombia, revisa los detalles antes de decidir.",
    "PE": "Si estás en Perú, consulta los detalles antes de elegir.",
    "MX": "Si estás en México, revisa la propuesta antes de elegir.",
}
RESULT_PROMISE = re.compile(
    r"\b(?:garantiz\w*|garantid\w*|asegurad\w*|sin esfuerzo|sin riesgo|"
    r"cura\w*|milagro\w*|enriquece\w*|ingresos pasivos|gana dinero|"
    r"pierde peso|resultados? seguros?|resultados? en \d+)\b"
)
NUMBERS = re.compile(
    r"\d+(?:[.,]\d+)?\s*%?|\b(?:dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|"
    r"cien|mil|primer[oa]|segund[oa])\b"
)


def policy_text(value: str) -> str:
    value = "".join(c for c in value if unicodedata.category(c) != "Cf")
    return normalized(value)


def lint_copy(
    text: str,
    *,
    sources: dict[str, str] | None = None,
    policy_path: Path = Path("config/policy.yaml"),
) -> list[str]:
    policy = Policy.model_validate(yaml.safe_load(policy_path.read_text()))
    normalized_text = policy_text(text)
    issues = []
    if any(policy_text(term) in normalized_text for term in policy.banned_terms):
        issues.append("termo banido")
    if RESULT_PROMISE.search(normalized_text):
        issues.append("promessa de resultado ou prática proibida")
    sources = sources or {}
    for number in sorted({match.group().strip() for match in NUMBERS.finditer(normalized_text)}):
        source = urlsplit(sources.get(number, ""))
        if source.scheme != "https" or not source.hostname or source.username or source.password:
            issues.append(f"número sem fonte HTTPS declarada: {number}")
    if not text.strip():
        issues.append("copy vazia")
    return issues


def generate_copies(
    offer: Offer,
    angle: Angle,
    *,
    region: str = "neutral",
    sources: dict[str, str] | None = None,
    policy_path: Path = Path("config/policy.yaml"),
) -> list[Creative]:
    policy = Policy.model_validate(yaml.safe_load(policy_path.read_text()))
    if (
        offer.language != "es"
        or not offer.allows_paid_traffic
        or offer.status == "killed"
        or offer.niche not in policy.allowed_niches
        or angle.offer_id != offer.id
        or angle.status == "killed"
    ):
        raise ValueError("oferta/ângulo inelegível")
    if region not in REGIONS:
        raise ValueError("região precisa ser neutral/CO/PE/MX")
    variants = [
        (angle.hook_line, f"{angle.promise}. {REGIONS[region]} Conoce la página oficial."),
        (
            f"Explora {offer.name}",
            f"{angle.hook_line}. {REGIONS[region]} Consulta el contenido y las condiciones.",
        ),
        (
            "Conoce la propuesta",
            f"{angle.promise}. Explora la información de {offer.name}. {REGIONS[region]}",
        ),
    ]
    result = []
    for index, (headline, primary) in enumerate(variants):
        issues = lint_copy(headline + "\n" + primary, sources=sources, policy_path=policy_path)
        if issues:
            raise ValueError("copy recusada: " + "; ".join(issues))
        identity = hashlib.sha256(
            f"{angle.id}:{region}:{index}:{headline}:{primary}".encode()
        ).hexdigest()[:20]
        result.append(
            Creative(
                id="copy-" + identity,
                angle_id=angle.id,
                format="video" if index == 2 else "image",
                copy_primary=primary,
                headline=headline,
                asset_path=f"pending/{identity}",
                policy_lint="passed",
                status="candidate",
            )
        )
    return result
