import copy
import json
import runpy
import subprocess
import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/check_coverage.py"
ASSESS = runpy.run_path(str(MODULE))["assess"]


def synthetic_report():
    summary = {
        "covered_lines": 100,
        "covered_branches": 100,
        "num_statements": 100,
        "num_branches": 100,
    }
    return {
        "totals": summary,
        "files": {
            name: {"summary": copy.copy(summary)}
            for name in [
                "src/arb/rules/__init__.py",
                "src/arb/metrics/__init__.py",
                "src/arb/launcher/execute.py",
                "src/arb/safety.py",
                "src/arb/meta/pause.py",
                "src/arb/ledger.py",
                "src/arb/reconcile.py",
                "src/arb/quarantine.py",
                "src/arb/db/checkpoint.py",
                "src/arb/scout/approve.py",
                "src/arb/creative/approve.py",
                "src/arb/launcher/scale.py",
                "src/arb/remote/__init__.py",
                "src/arb/remote/journal.py",
                "src/arb/remote/launch.py",
                "src/arb/drill.py",
            ]
        },
    }


def test_missing_module_or_uncovered_branches_fail():
    report = synthetic_report()
    assert ASSESS(report)[1] == []
    report["files"]["src/arb/safety.py"]["summary"]["covered_branches"] = 89
    assert ASSESS(report)[1] == ["arb.safety"]  # 94.5%, não arredonda para 95.
    report = synthetic_report()
    del report["files"]["src/arb/meta/pause.py"]
    assert ASSESS(report)[1] == ["arb.meta.pause"]
    report["totals"]["covered_lines"] = 59
    assert "arb" in ASSESS(report)[1]


def test_actual_ci_command_fails_below_minimum(tmp_path):
    report = synthetic_report()
    source = tmp_path / "coverage.json"
    source.write_text(json.dumps(report))
    output = tmp_path / "evidence.json"
    result = subprocess.run(
        [sys.executable, str(MODULE), str(source), "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and json.loads(output.read_text())["failures"] == []
    report["files"]["src/arb/launcher/execute.py"]["summary"]["covered_lines"] = 0
    source.write_text(json.dumps(report))
    result = subprocess.run(
        [sys.executable, str(MODULE), str(source)], capture_output=True, text=True
    )
    assert result.returncode == 1 and '"arb.launcher"' in result.stdout
