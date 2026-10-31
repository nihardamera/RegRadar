"""Human labels for calibrating the judge: is each answer faithful, and correct?

    uv run python -m regradar.label sample     # fix the 100 answers and their split (once)
    uv run python -m regradar.label            # label, resuming where you stopped

For each sampled answer you see the question, every claim with the full text
of the chunks it cites, and the golden set's reference answer. No judge output
is shown (the judge is calibrated against these labels, so it must not
anchor them). Two labels, both yes / no:

    faithful   every claim is supported by the text it cites
    correct    the answer answers the question (compare with the reference)

The 100 answers are a fixed random sample of the answered questions; about 40
are dev (for tuning the judge's prompt) and 60 held out (scored once, at the
end). Both are fixed before any judge runs.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from regradar.golden import load

ROOT = Path(__file__).resolve().parent.parent
HUMAN = ROOT / "eval" / "human"
SAMPLE = HUMAN / "judge_sample.jsonl"
LABELS = HUMAN / "judge_labels.jsonl"
RESULTS = ROOT / "eval" / "results"
SAMPLE_SIZE = 100
DEV_SHARE = 0.4
SEED = 20261101


def answered_records(results_dir: Path = RESULTS) -> list[dict[str, Any]]:
    """Every answered question, with what the model said and the chunks it cited."""
    records = []
    for path in sorted(results_dir.glob("answers_*_claude-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["questions"]:
            if row["status"] == "answered" and "claims" in row:
                records.append({"model": data["model"], "retrieval": data["retrieval"], **row})
    return records


def draw(
    records: list[dict[str, Any]], size: int = SAMPLE_SIZE, seed: int = SEED
) -> list[dict[str, Any]]:
    """A fixed random sample, with a judge split fixed at the same time."""
    rng = random.Random(seed)
    # Sorted first, so the draw does not depend on the order files were read in.
    pool = sorted(records, key=lambda r: (r["question_id"], r.get("retrieval", "")))
    chosen = sorted(rng.sample(pool, min(size, len(pool))), key=lambda r: r["question_id"])
    dev = set(rng.sample(range(len(chosen)), round(DEV_SHARE * len(chosen))))
    return [{**r, "judge_split": "dev" if i in dev else "heldout"} for i, r in enumerate(chosen)]


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _ask(prompt: str, allowed: tuple[str, ...]) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if answer in allowed:
            return answer
        print(f"  one of: {', '.join(allowed)}")


def cmd_sample(_args: argparse.Namespace) -> int:
    if SAMPLE.exists():
        print(f"{SAMPLE} exists; the sample is fixed and is not redrawn")
        return 1
    chosen = draw(answered_records())
    HUMAN.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text("".join(json.dumps(r) + "\n" for r in chosen), encoding="utf-8")
    dev = sum(r["judge_split"] == "dev" for r in chosen)
    print(f"{len(chosen)} answers sampled ({dev} dev, {len(chosen) - dev} held out) -> {SAMPLE}")
    return 0


def cmd_label(_args: argparse.Namespace) -> int:
    sample = _read(SAMPLE)
    if not sample:
        print("no sample yet: run `python -m regradar.label sample` first")
        return 1
    done = {r["question_id"] for r in _read(LABELS)}
    questions = {q.id: q for q in load()}
    todo = [r for r in sample if r["question_id"] not in done]
    print(f"{len(done)} labelled, {len(todo)} to go. Answer y / n; q quits (your labels are kept).")
    for n, record in enumerate(todo, 1):
        q = questions[record["question_id"]]
        print(f"\n[{len(done) + n}/{len(sample)}] {q.id}: {q.question}")
        for i, claim in enumerate(record["claims"], 1):
            print(f"\n  Claim {i}: {claim['text']}")
            for cid in claim["citations"]:
                chunk = record["context"].get(cid, "(chunk text not recorded)")
                print(f"    cites {cid}:\n      {' '.join(chunk.split())[:1500]}")
        print(f"\n  Reference answer: {q.answer}")
        faithful = _ask(
            "  Faithful (every claim supported by what it cites)? y/n/q ", ("y", "n", "q")
        )
        if faithful == "q":
            break
        correct = _ask(
            "  Correct (answers the question, per the reference)? y/n/q ", ("y", "n", "q")
        )
        if correct == "q":
            break
        note = input("  Note (optional): ").strip()
        label = {
            "question_id": q.id,
            "faithful": faithful == "y",
            "correct": correct == "y",
            "note": note,
            "labeller": "Nihar Damera",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        HUMAN.mkdir(parents=True, exist_ok=True)
        with LABELS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(label) + "\n")
    print(f"\n{len(_read(LABELS))} of {len(sample)} labelled -> {LABELS}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step")
    steps.add_parser("sample").set_defaults(run=cmd_sample)
    args = parser.parse_args(argv)
    try:
        result: int = (args.run if args.step else cmd_label)(args)
    except (EOFError, KeyboardInterrupt):
        print("\nstopped; labels so far are saved")
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
