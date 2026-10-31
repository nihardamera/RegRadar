"""An LLM judge for answers, calibrated against human labels before it is trusted.

    uv run python -m regradar.judge calibrate --model M --split dev  # tune on dev labels
    uv run python -m regradar.judge calibrate --model M --split heldout --final  # once

The judge sees what the human labeller saw (the claims, the full text each
cites, the reference answer) and gives the same two labels: faithful (every
claim supported by what it cites) and correct (it answers the question).
Agreement with the human labels is reported as Cohen's kappa, which corrects
for agreement by chance. The held-out labels are scored once: `--final`
writes a lock, and the held-out split cannot be run again without deleting it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from regradar.golden import load
from regradar.label import LABELS, SAMPLE, _read
from regradar.llm import Claude

ROOT = Path(__file__).resolve().parent.parent
JUDGE_DIR = ROOT / "eval" / "judge"
LOCK = JUDGE_DIR / "heldout.lock"

SYSTEM = """You check answers to questions about Reserve Bank of India circulars.
You are given the question, the answer's claims with the full text of the chunks
each claim cites, and a reference answer written by a person.

Judge two things:
- faithful: true only if every claim is supported by the text of the chunks it
  cites. Numbers, limits, dates and the entity a rule applies to must match.
  Ignore whether the claim is also true elsewhere; only the cited text counts.
- correct: true only if the claims, taken together, answer the question the way
  the reference answer does. Extra true detail is fine; a missing or different
  key fact (an amount, a period, a yes/no) makes it incorrect.

Reply with JSON only: {"faithful": true|false, "correct": true|false, "reason": "<one sentence>"}
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "faithful": {"type": "boolean"},
        "correct": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["faithful", "correct", "reason"],
    "additionalProperties": False,
}


class Verdict(BaseModel):
    faithful: bool
    correct: bool
    reason: str = ""


def prompt(
    question: str, reference: str, claims: Sequence[dict[str, Any]], context: dict[str, str]
) -> str:
    parts = [f"Question: {question}", ""]
    for i, claim in enumerate(claims, 1):
        parts.append(f"Claim {i}: {claim['text']}")
        for cid in claim["citations"]:
            parts.append(
                f"  Cited chunk {cid}:\n  {' '.join(context.get(cid, '(missing)').split())}"
            )
        parts.append("")
    parts.append(f"Reference answer: {reference}")
    return "\n".join(parts)


def judge(
    record: dict[str, Any], reference: str, question: str, generate: Callable[[str, str], str]
) -> Verdict:
    text = generate(SYSTEM, prompt(question, reference, record["claims"], record["context"]))
    start, end = text.find("{"), text.rfind("}")
    return Verdict.model_validate(json.loads(text[start : end + 1]))


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Agreement between two binary raters, corrected for chance (1 = perfect, 0 = chance)."""
    if len(a) != len(b) or not a:
        raise ValueError("need two equal, non-empty label lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def agreement(human: Sequence[bool], model: Sequence[bool]) -> dict[str, float]:
    n = len(human)
    return {
        "n": n,
        "agreement": round(sum(h == m for h, m in zip(human, model, strict=True)) / n, 3),
        "kappa": round(cohen_kappa(human, model), 3),
        "human_yes": round(sum(human) / n, 3),
        "judge_yes": round(sum(model) / n, 3),
    }


def cmd_calibrate(args: argparse.Namespace) -> int:
    if args.split == "heldout":
        if LOCK.exists():
            print(f"the held-out labels were already scored ({LOCK}); this is not re-run")
            return 1
        if not args.final:
            print("the held-out split is scored once: pass --final when the prompt is settled")
            return 1
    sample = {r["question_id"]: r for r in _read(SAMPLE)}
    labels = [
        lab for lab in _read(LABELS) if sample[lab["question_id"]]["judge_split"] == args.split
    ]
    if not labels:
        print(f"no human labels in the {args.split} split yet")
        return 1
    questions = {q.id: q for q in load()}
    llm = Claude(
        args.model, f"judge-{args.split}", spend=args.spend, schema=SCHEMA, effort=args.effort
    )
    verdicts = []
    for label in labels:
        q = questions[label["question_id"]]
        verdicts.append(judge(sample[q.id], q.answer, q.question, llm))
    out = {
        "model": args.model,
        "effort": args.effort,
        "split": args.split,
        "faithful": agreement([lab["faithful"] for lab in labels], [v.faithful for v in verdicts]),
        "correct": agreement([lab["correct"] for lab in labels], [v.correct for v in verdicts]),
        "disagreements": [
            {
                "question_id": lab["question_id"],
                "human": {"faithful": lab["faithful"], "correct": lab["correct"]},
                "judge": v.model_dump(),
            }
            for lab, v in zip(labels, verdicts, strict=True)
            if (lab["faithful"], lab["correct"]) != (v.faithful, v.correct)
        ],
    }
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    (JUDGE_DIR / f"calibration_{args.split}.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8"
    )
    if args.split == "heldout":
        LOCK.write_text(
            json.dumps({"model": args.model, "effort": args.effort}) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: out[k] for k in ("faithful", "correct")}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    cal = steps.add_parser("calibrate", help="agreement with the human labels")
    cal.add_argument("--model", required=True, help="the judge model; there is no default")
    cal.add_argument("--split", choices=["dev", "heldout"], default="dev")
    cal.add_argument("--final", action="store_true")
    cal.add_argument("--effort", default="low")
    cal.add_argument("--spend", action="store_true")
    cal.set_defaults(run=cmd_calibrate)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
