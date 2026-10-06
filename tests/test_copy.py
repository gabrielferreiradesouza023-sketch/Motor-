import pytest
from test_plan import launch_fixture

from arb.creative import generate_angles
from arb.creative.copy import generate_copies, lint_copy


@pytest.mark.parametrize(
    "region,country", [("neutral", ""), ("CO", "Colombia"), ("PE", "Perú"), ("MX", "México")]
)
def test_spanish_regional_candidates(region, country):
    offer, _, _ = launch_fixture()
    offer.name = "Curso de hojas de cálculo"
    angle = generate_angles(offer, [])[0]
    copies = generate_copies(offer, angle, region=region)
    assert len(copies) == len({c.id for c in copies}) == 3
    assert all(c.status == "candidate" and c.policy_lint == "passed" for c in copies)
    assert all(country in c.copy_primary for c in copies)
    assert copies == generate_copies(offer, angle, region=region)


@pytest.mark.parametrize(
    "text",
    [
        "Resultado garantizado",
        "Ingresos GARANTIZADOS",
        "Resultado garan\u200btizado",
        "Sin esfuerzo",
        "Aprende en 7 días",
        "Tres pasos para empezar",
        "100% seguro",
    ],
)
def test_bad_claims_rejected(text):
    assert lint_copy(text)


def test_explicit_number_source_is_required_but_not_guarantee_permission():
    assert not lint_copy("Contenido: 7 lecciones", sources={"7": "https://example.test/contenido"})
    assert lint_copy("Contenido: 7 lecciones", sources={"7": "http://example.test"})
    assert lint_copy("Resultado garantizado en 7 días", sources={"7": "https://example.test"})
    offer, _, _ = launch_fixture()
    offer.name = "Curso de hojas de cálculo"
    angle = generate_angles(offer, [])[0]
    angle.promise = "Resultado garantizado"
    with pytest.raises(ValueError, match="recusada"):
        generate_copies(offer, angle)
    angle.promise = "Explorar el contenido"
    with pytest.raises(ValueError, match="região"):
        generate_copies(offer, angle, region="BR")
