from pathlib import Path

import pytest

from arb.scout import import_adlibrary, import_offers

ROOT = Path(__file__).resolve().parents[1]


def test_example_csv_and_round_trip():
    offers = import_offers(ROOT / "examples/scout/offers.csv")
    ads = import_adlibrary(ROOT / "examples/scout/adlibrary.csv")
    assert len(offers) == 4 and len(ads) == 3
    for model in offers + ads:
        assert type(model).model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("kind", ["header", "duplicate", "boolean", "money", "extra"])
def test_invalid_offers_refused(tmp_path, kind):
    text = (ROOT / "examples/scout/offers.csv").read_text()
    if kind == "header":
        text = text.replace("commission_brl_cents", "commission")
    elif kind == "duplicate":
        text += text.splitlines()[1] + "\n"
    elif kind == "boolean":
        text = text.replace(",true,", ",yes,", 1)
    elif kind == "money":
        text = text.replace(",6000,", ",60.00,", 1)
    elif kind == "extra":
        text = text.replace(",0.1\n", ",0.1,extra\n", 1)
    path = tmp_path / "offers.csv"
    path.write_text(text)
    with pytest.raises(ValueError):
        import_offers(path)
