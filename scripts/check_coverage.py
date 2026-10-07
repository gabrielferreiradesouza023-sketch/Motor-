"""Barreira de cobertura combinada de linhas + branches, sem arredondar para passar."""

import argparse
import json
from pathlib import Path

MONEY_MODULES = (
    "rules",
    "metrics",
    "launcher",
    "safety",
    "meta.pause",
    "ledger",
    "reconcile",
    "quarantine",
    "db.checkpoint",
    "scout.approve",
    "creative.approve",
    "launcher.scale",
    "remote",
    "remote.journal",
    "remote.launch",
    "drill",
    "tracker.ids",
    "permissions",
    "accept",
    "accept_pause",
    "accept_tracking",
    "readiness",
)


def percentage(summaries):
    covered = sum(s["covered_lines"] + s["covered_branches"] for s in summaries)
    possible = sum(s["num_statements"] + s["num_branches"] for s in summaries)
    return 100 * covered / possible if possible else 0.0


def assess(report):
    result = {"arb": {"percent": percentage([report["totals"]]), "minimum": 80}}
    for module in MONEY_MODULES:
        prefix = "src/arb/" + module.replace(".", "/")
        matched = [
            value["summary"]
            for name, value in report["files"].items()
            if name == prefix + ".py" or name.startswith(prefix + "/")
        ]
        result["arb." + module] = {"percent": percentage(matched), "minimum": 95}
    failures = [name for name, value in result.items() if value["percent"] < value["minimum"]]
    return result, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result, failures = assess(json.loads(args.report.read_text()))
    evidence = {
        "basis": "(covered_lines + covered_branches) / (statements + branches)",
        "modules": result,
        "failures": failures,
    }
    serialized = json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
    print(serialized, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
