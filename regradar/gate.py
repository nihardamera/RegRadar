"""The CI gate: retrieval and answer quality on a fixed 30-question subset must not drop.

    uv run python -m regradar.gate refresh    # re-query Qdrant, rewrite eval/ci/ (local)
    uv run python -m regradar.gate answers    # copy the subset's stored answers (no API)
    uv run python -m regradar.gate check      # recompute and compare (CI; no Qdrant)

CI has no Qdrant and no models, so the gate works from committed retrieval
results: `refresh` runs the default configuration over the subset and writes
what came back; `check` recomputes the metrics from that file with the current
metric code and golden set, and fails when one falls more than its tolerance
below the recorded baseline. A change to retrieval is expected to come with a
refreshed file, so a regression shows up in the same pull request.

Answers work the same way, from the committed dev answers (no model in CI):
citation precision is recomputed from what each answer cited, and the
citation checks in `regradar/answer.py` are re-run on the stored claims, so a
change that makes them reject answers they used to accept fails the gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from regradar.answer import ContextChunk, Reply
from regradar.answer import problems as citation_problems
from regradar.evaluate import Config, Retrieved, overlaps, question_metrics
from regradar.golden import Question, load

ROOT = Path(__file__).resolve().parent.parent
GATE_DIR = ROOT / "eval" / "ci"
RETRIEVAL = GATE_DIR / "retrieval.json"
BASELINE = GATE_DIR / "baseline.json"
ANSWERS = GATE_DIR / "answers.json"
ANSWER_SOURCE = ROOT / "eval" / "results" / "answers_dev_claude-haiku-5-5_section_hybrid.json"
DEFAULT = Config("section", "hybrid")  # the default chosen in eval/results/ABLATION.md
SUBSET_SIZE = 30
# Points a metric may fall below its baseline before the gate fails. With 30
# questions one question is 3.3 points, so this allows one miss, not two.
# About 25 subset answers are answered, so one answer is about 4 points.
TOLERANCE = {"hit@10": 4.0, "mrr": 5.0, "citation_precision": 8.0, "still_accepted": 4.0}
RETRIEVAL_METRICS = ("hit@10", "mrr")


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
    return {
        name: round(100 * sum(m[name] for m in per) / len(per), 2) for name in RETRIEVAL_METRICS
    }


def answer_scores(answers: dict[str, Any], questions: list[Question]) -> dict[str, float]:
    """Citation precision and the share still accepted, over the subset's answered questions."""
    precision, accepted = [], []
    for q in questions:
        row = answers["questions"].get(q.id)
        if row is None or row["status"] != "answered":
            continue
        cited = [Retrieved(**c) for c in row["cited"]]
        if cited:
            precision.append(sum(any(overlaps(c, s) for s in q.spans) for c in cited) / len(cited))
        reply = Reply(not_found=False, claims=row["claims"])
        chunks = [ContextChunk(cid, "", text) for cid, text in row["context"].items()]
        accepted.append(not citation_problems(reply, chunks, q.question))
    return {
        "citation_precision": round(100 * sum(precision) / len(precision), 2),
        "still_accepted": round(100 * sum(accepted) / len(accepted), 2),
    }


def problems(current: dict[str, float], baseline: dict[str, float]) -> list[str]:
    found = []
    for name, slack in TOLERANCE.items():
        if name in baseline and current.get(name, 0.0) < baseline[name] - slack:
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


def cmd_answers(_args: argparse.Namespace) -> int:
    """Copy the subset's answers, with the offsets of what they cited, into eval/ci/."""
    from regradar.chunking import STRATEGIES, load_corpus

    questions = subset(load())
    source = json.loads(ANSWER_SOURCE.read_text(encoding="utf-8"))
    rows = {row["question_id"]: row for row in source["questions"]}
    chunks = {c.chunk_id: c for doc in load_corpus() for c in STRATEGIES[DEFAULT.strategy](doc)}
    out: dict[str, Any] = {"source": ANSWER_SOURCE.name, "model": source["model"], "questions": {}}
    for q in questions:
        row = rows[q.id]
        cited = [chunks[cid] for cid in row["cited"] if cid in chunks]
        out["questions"][q.id] = {
            "status": row["status"],
            "claims": row["claims"],
            "context": row["context"],
            "cited": [
                asdict(Retrieved(c.chunk_id, c.doc_id, c.start, c.end, c.words)) for c in cited
            ],
        }
    ANSWERS.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    current = answer_scores(out, questions)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    for name, value in current.items():
        baseline.setdefault(name, value)
    BASELINE.write_text(json.dumps(baseline, indent=1) + "\n", encoding="utf-8")
    print(f"answers: {current}; baseline {baseline}")
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    questions = subset(load())
    retrieval = json.loads(RETRIEVAL.read_text(encoding="utf-8"))
    current = scores(retrieval, questions)
    current |= answer_scores(json.loads(ANSWERS.read_text(encoding="utf-8")), questions)
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
    steps.add_parser("answers").set_defaults(run=cmd_answers)
    steps.add_parser("check").set_defaults(run=cmd_check)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
