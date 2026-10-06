"""Fábrica determinística de candidatos; revisão humana continua obrigatória."""

import hashlib
import unicodedata

from arb.models import Angle, AngleLearning, Offer


def normalized(value: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(c)
        ).split()
    )


def generate_angles(offer: Offer, library: list[AngleLearning]) -> list[Angle]:
    if offer.language != "es" or not offer.allows_paid_traffic or offer.status == "killed":
        raise ValueError("oferta inelegível para candidatos em espanhol")
    # Hipóteses de comunicação, não alegações de conteúdo/resultado do produto.
    candidates = [
        (
            "Claridad",
            "Explorar el contenido antes de decidir",
            "Dudas sobre el contenido",
            f"Conoce la propuesta de {offer.name}",
        ),
        (
            "Organización",
            "Revisar una propuesta de aprendizaje",
            "Dudas sobre cómo empezar",
            f"¿Por dónde empezar con {offer.name}?",
        ),
        (
            "Información",
            "Consultar los detalles de la oferta",
            "Falta de información para comparar",
            f"Mira los detalles de {offer.name}",
        ),
        (
            "Autonomía",
            "Evaluar si la propuesta encaja",
            "Dudas antes de elegir un curso",
            f"Explora si {offer.name} encaja contigo",
        ),
        (
            "Comparación",
            "Conocer la página oficial",
            "Necesidad de evaluar alternativas",
            f"Revisa la información oficial de {offer.name}",
        ),
        (
            "Interés",
            "Descubrir una propuesta educativa",
            "Curiosidad por aprender algo nuevo",
            f"Descubre la propuesta de {offer.name}",
        ),
    ]
    relevant = [row for row in library if row.niche == offer.niche]
    killed = [row for row in relevant if row.verdict == "kill"]
    passed = [row for row in relevant if row.verdict == "pass"]
    # Evidência positiva prioriza famílias de promessa; mortes sempre prevalecem.
    candidates.sort(
        key=lambda row: not any(normalized(row[1]) == normalized(w.promise) for w in passed)
    )
    result = []
    for label, promise, pain, hook in candidates:
        if any(
            normalized(hook) == normalized(row.hook_line)
            or (normalized(promise), normalized(pain))
            == (normalized(row.promise), normalized(row.audience_pain))
            for row in killed
        ):
            continue
        identity = hashlib.sha256(f"{offer.id}:{promise}:{pain}:{hook}".encode()).hexdigest()[:20]
        result.append(
            Angle(
                id="candidate-" + identity,
                offer_id=offer.id,
                hypothesis=f"Hipótesis {label}: evaluar atención e intención con muestras",
                promise=promise,
                audience_pain=pain,
                hook_line=hook,
                status="candidate",
            )
        )
        if len(result) == 3:
            return result
    raise ValueError(
        "biblioteca excluiu famílias demais; revisão humana de novas hipóteses necessária"
    )
