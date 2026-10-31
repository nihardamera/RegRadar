"""The CI gate: retrieval quality on a fixed 30-question subset must not drop.

    uv run python -m regradar.gate refresh    # re-query Qdrant, rewrite eval/ci/ (local)
    uv run python -m regradar.gate check      # recompute and compare (CI; no Qdrant)

CI has no Qdrant and no models, so the gate works from committed retrieval
results: `refresh` runs the default configuration over the subset and writes
what came back; `check` recomputes the metrics from that file with the current
metric code and golden set, and fails when one falls more than its tolerance
below the recorded baseline. A change to retrieval is expected to come with a
refreshed file, so a regression shows up in the same pull request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from regradar.evaluate import Config, Retrieved, question_metrics
from regradar.golden import Question, load

ROOT = Path(__file__).resolve().parent.parent
GATE_DIR = ROOT / "eval" / "ci"
RETRIEVAL = GATE_DIR / "retrieval.json"
BASELINE = GATE_DIR / "baseline.json"
DEFAULT = Config("section", "hybrid")  # the default chosen in eval/results/ABLATION.md
SUBSET_SIZE = 30
# Points a metric may fall below its baseline before the gate fails. With 30
# questions one question is 3.3 points, so this allows one miss, not two.
TOLERANCE = {"hit@10": 4.0, "mrr": 5.0}


def subset(questions: list[Question]) -> list[Question]:
    """30 answerable dev questions, chosen by a hash of their IDs (fixed, not cherry-picked)."""
    dev = [q for q in questions if q.split == "dev" and q.answerable]
    dev.sort(key=lambda q: hashlib.sha256(f"gate:{q.id}".encode()).hexdigest())
    return sorted(dev[:SUBSET_SIZE], key=lambda q: q.id)


def scores(retrieval: dict[str, Any], questions: list[Question]) -> dict[str, float]:
    """Mean metrics (in points) over the subset, from the stored retrieval."""
    per = []
    for q in questions:
        ranked = [Retrieved(**chunk) for chunk in retrieval["questions"][q.id]]
        per.append(question_metrics(ranked, q))
    return {name: round(100 * sum(m[name] for m in per) / len(per), 2) for name in TOLERANCE}


def problems(current: dict[str, float], baseline: dict[str, float]) -> list[str]:
    found = []
    for name, slack in TOLERANCE.items():
        if current[name] < baseline[name] - slack:
            found.append(
                f"{name} fell to {current[name]:.1f} from a baseline of {baseline[name]:.1f}"
                f" (tolerance {slack:.1f} points)"
            )
    return found


def cmd_refresh(_args: argparse.Namespace) -> int:
    from regradar.evaluate import qdrant_search

    questions = subset(load())
    search = qdrant_search()
    out = {
        "config": DEFAULT.name,
        "questions": {q.id: [asdict(r) for r, _ in search(q, DEFAULT)] for q in questions},
    }
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    RETRIEVAL.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    current = scores(out, questions)
    if not BASELINE.exists():
        BASELINE.write_text(json.dumps(current, indent=1) + "\n", encoding="utf-8")
        print(f"baseline recorded: {current}")
    else:
        print(f"refreshed: {current}; baseline {json.loads(BASELINE.read_text())}")
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    questions = subset(load())
    retrieval = json.loads(RETRIEVAL.read_text(encoding="utf-8"))
    current = scores(retrieval, questions)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    found = problems(current, baseline)
    print(f"{retrieval['config']}, {len(questions)} questions: {current} (baseline {baseline})")
    for p in found:
        print(f"GATE FAILED: {p}")
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("refresh").set_defaults(run=cmd_refresh)
    steps.add_parser("check").set_defaults(run=cmd_check)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
