import json
import os
from datetime import UTC, datetime

import pytest
from test_scheduler import seeded

from arb.analyst.decisions import question, queue
from arb.analyst.report import generate_report

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def proposal(directory, record, name, exposure, age, **changes):
    directory.mkdir(exist_ok=True)
    approval = record.model_copy(update={"id": name, "max_exposure_cents": exposure, **changes})
    path = directory / (name + ".json")
    path.write_text(approval.model_dump_json())
    os.utime(path, (NOW.timestamp() - age, NOW.timestamp() - age))
    return path


@pytest.mark.parametrize("count", [0, 1, 3])
def test_queue_risk_order_question_and_command(tmp_path, records, count):
    directory = tmp_path / "pending"
    for name, amount, age in [("low", 10, 100000), ("recent", 100, 50), ("old", 100, 100)][:count]:
        proposal(directory, records[7], name, amount, age)
    result = queue(directory, now=NOW)
    assert [row["id"] for row in result["items"]] == {
        0: [],
        1: ["low"],
        3: ["old", "recent", "low"],
    }[count]
    assert queue(directory, now=NOW) == result
    if count:
        first = result["items"][0]
        assert first["command"] == "arb approve sign " + str(directory / (first["id"] + ".json"))
        assert first["plan_hash_short"] == "a" * 12
        assert first["id"] in question(result)
    else:
        assert question(result) == "Manter a simulação até a próxima revisão?"


def test_age_tie_id_and_old_suggestion(tmp_path, records):
    for name in ("z", "a"):
        proposal(tmp_path, records[7], name, 100, 100000)
    result = queue(tmp_path, now=NOW)
    assert [row["id"] for row in result["items"]] == ["a", "z"]
    assert "não expira" in result["items"][0]["expiry_suggestion"]


@pytest.mark.parametrize("count", [0, 1, 3])
def test_html_redaction_escape_no_controls(tmp_path, records, count):
    conn = seeded(tmp_path, records)
    directory = tmp_path / "pending"
    for number in range(count):
        proposal(
            directory,
            records[7],
            "one-" + str(number),
            100,
            100,
            summary="<script>bad</script> token=synthetic-secret",
        )
    report = generate_report(
        conn, tmp_path / "reports", approval_dir=directory, now=NOW
    ).read_text()
    assert "synthetic-secret" not in report
    assert "<script>" not in report
    if count:
        assert "&lt;script&gt;" in report and "arb approve sign" in report
        assert "launch: " + str(count) in report
    else:
        assert "Nenhuma proposta válida pendente." in report
    assert "<button" not in report and "<form" not in report
    assert report.count('class="decision-question"') == 1
    conn.close()


def test_bad_files_and_symlinks_never_read(tmp_path, records):
    (tmp_path / "broken.json").write_text("invalid")
    (tmp_path / "wrong.json").write_text(
        records[7].model_copy(update={"id": "../unsafe"}).model_dump_json()
    )
    path = proposal(tmp_path, records[7], "rejected", 0, 0, status="rejected")
    (tmp_path / "alias.json").symlink_to(path)
    result = queue(tmp_path, now=NOW)
    assert result == {"items": [], "invalid": 3}
    assert queue(tmp_path / "alias.json", now=NOW)["invalid"] == 1
    with pytest.raises(ValueError, match="fuso"):
        queue(tmp_path, now=datetime(2026, 10, 7))


def test_envelope_payload_not_exposed(tmp_path, records):
    approval = records[7].model_copy(update={"id": "envelope", "kind": "new_offer"})
    from arb.launcher.actions import intent_hash

    plan = {"kind": "new_offer", "token": "synthetic-hidden"}
    approval = approval.model_copy(update={"plan_hash": intent_hash(plan)})
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps({"approval": approval.model_dump(mode="json"), "plan": plan}))
    result = queue(tmp_path, now=NOW)
    assert len(result["items"]) == 1
    assert "synthetic-hidden" not in json.dumps(result)


@pytest.mark.parametrize(
    "summary",
    [
        "Authorization: Bearer synthetic-hidden",
        "token=synthetic-hidden",
        "PRIVATE KEY synthetic-hidden",
    ],
)
def test_sensitive_summary_redacted(tmp_path, records, summary):
    proposal(tmp_path, records[7], "one", 100, 100, summary=summary)
    result = queue(tmp_path, now=NOW)
    assert "synthetic-hidden" not in json.dumps(result)
    assert result["items"][0]["summary"] == "[redigido]"
