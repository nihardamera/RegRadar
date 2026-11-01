"""An LLM judge for answers, calibrated against human labels before it is trusted.

    uv run python -m regradar.judge calibrate --model M --split dev  # tune on dev labels
    uv run python -m regradar.judge calibrate --model M --split heldout --final  # once
    uv run python -m regradar.judge summary  # held-out results with 95% intervals

The judge sees what the human labeller saw (the claims, the full text each
cites, the reference answer) and gives the same two labels: faithful (every
claim supported by what it cites) and correct (it answers the question).
Agreement with the human labels is reported as Cohen's kappa, which corrects
for agreement by chance, over all labelled cases and separately over the
natural sample (real answers as they come) and the real failures. Planted
errors (`regradar/plant.py`) have no human label: the script knows what it
changed, so the judge is scored on the share it marks unfaithful. A planted
edit is not always a real error, so that share is a floor, not an exact rate. The held-out
labels are scored once: `--final` writes a lock, and the held-out split
cannot be run again without deleting it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from regradar.evaluate import BOOTSTRAP, SEED, bootstrap_ci
from regradar.golden import load
from regradar.label import EXTRA, LABELS, SAMPLE, _read, case_id, label_key
from regradar.llm import Claude

ROOT = Path(__file__).resolve().parent.parent
JUDGE_DIR = ROOT / "eval" / "judge"
LOCK = JUDGE_DIR / "heldout.lock"

# Prompt 2. Prompt 1 gave one faithful verdict for the whole answer; on dev it
# wrote "claim 2 is not supported" and still returned faithful, pooled chunks
# across claims, and passed dropped conditions and "shall" -> "may" (6 of 12
# planted errors missed; eval/judge/calibration_dev_prompt1.json). Now each
# claim gets its own verdict and code takes faithful = every claim supported.
SYSTEM = """You check answers to questions about Reserve Bank of India circulars.
You are given the question, the answer's claims with the full text of the chunks
each claim cites, and a reference answer written by a person.

1. For each claim, in order, decide whether it is supported by the chunks THAT
   CLAIM cites. Use only those chunks: text cited by another claim does not count,
   and neither does what you know or what the reference says. A claim is NOT
   supported if, compared with its cited text, it:
   - changes a number, amount, limit, date or period;
   - changes the force of a rule (shall / must / may / shall not), or drops a "not";
   - applies the rule to a different entity (banks vs non-banks, debit vs credit);
   - drops a condition, exception or qualifier the text attaches to the rule
     ("unless", "subject to", "provided", "except", "only if"), so it says more
     than the text does;
   - states something the cited text does not say at all.
   Wording may differ; meaning may not.
2. correct: true only if the claims, taken together, answer the question the way
   the reference answer does. Extra true detail is fine; a missing or different
   key fact (an amount, a period, a yes/no) makes it incorrect.

Reply with JSON only:
{"claims": [{"claim": 1, "supported": true|false, "why": "<short>"}, ...],
 "correct": true|false, "reason": "<one sentence>"}
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "integer"},
                    "supported": {"type": "boolean"},
                    "why": {"type": "string"},
                },
                "required": ["claim", "supported", "why"],
                "additionalProperties": False,
            },
        },
        "correct": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["claims", "correct", "reason"],
    "additionalProperties": False,
}


class ClaimVerdict(BaseModel):
    claim: int
    supported: bool
    why: str = ""


class Verdict(BaseModel):
    faithful: bool
    correct: bool
    reason: str = ""
    claims: list[ClaimVerdict] = []


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
    data = json.loads(text[start : end + 1])
    claims = [ClaimVerdict.model_validate(c) for c in data.get("claims", [])]
    # Faithful is decided here, not by the model: every claim needs a verdict,
    # and every verdict must be "supported".
    faithful = len(claims) == len(record["claims"]) and all(c.supported for c in claims)
    return Verdict(
        faithful=faithful, correct=data["correct"], reason=data.get("reason", ""), claims=claims
    )


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


def kappa_ci(
    human: Sequence[bool], model: Sequence[bool], resamples: int = BOOTSTRAP, seed: int = SEED
) -> tuple[float, float, float] | None:
    """Kappa and its 95% percentile-bootstrap interval, resampling cases.

    None when the human labels are all one value: kappa then has nothing to
    measure (any judge scores 0 or is undefined), so no number is reported.
    """
    if len(set(human)) < 2:
        return None
    h, m = np.asarray(human), np.asarray(model)
    rng = np.random.default_rng(seed)
    values = []
    for idx in rng.integers(0, len(h), size=(resamples, len(h))):
        if len(set(h[idx])) > 1:
            values.append(cohen_kappa(list(h[idx]), list(m[idx])))
    low, high = np.percentile(values, [2.5, 97.5])
    return (cohen_kappa(human, model), float(low), float(high))


def planted_score(cases: Sequence[dict[str, Any]], verdicts: Sequence[Verdict]) -> dict[str, Any]:
    """Share of planted errors the judge marks unfaithful, overall and by kind."""
    by_kind: dict[str, list[bool]] = {}
    for case, verdict in zip(cases, verdicts, strict=True):
        by_kind.setdefault(case["planted"]["kind"], []).append(not verdict.faithful)
    caught = [c for flags in by_kind.values() for c in flags]
    return {
        "n": len(caught),
        "caught": sum(caught),
        "catch_rate": round(sum(caught) / len(caught), 3),
        "by_kind": {kind: f"{sum(flags)}/{len(flags)}" for kind, flags in sorted(by_kind.items())},
        "missed": [
            case["case_id"]
            for case, verdict in zip(cases, verdicts, strict=True)
            if verdict.faithful
        ],
    }


def cmd_calibrate(args: argparse.Namespace) -> int:
    if args.split == "heldout":
        if LOCK.exists():
            print(f"the held-out labels were already scored ({LOCK}); this is not re-run")
            return 1
        if not args.final:
            print("the held-out split is scored once: pass --final when the prompt is settled")
            return 1
    cases = {case_id(r): r for r in _read(SAMPLE) + _read(EXTRA)}
    labels = [lab for lab in _read(LABELS) if cases[label_key(lab)]["judge_split"] == args.split]
    planted = [
        r for r in cases.values() if r.get("source") == "planted" and r["judge_split"] == args.split
    ]
    if not labels:
        print(f"no human labels in the {args.split} split yet")
        return 1
    questions = {q.id: q for q in load()}
    llm = Claude(
        args.model, f"judge-{args.split}", spend=args.spend, schema=SCHEMA, effort=args.effort
    )

    def run(record: dict[str, Any]) -> Verdict:
        q = questions[record["question_id"]]
        return judge(record, q.answer, q.question, llm)

    verdicts = [run(cases[label_key(label)]) for label in labels]
    planted_verdicts = [run(record) for record in planted]
    groups: dict[str, Callable[[dict[str, Any]], bool]] = {
        "all": lambda r: True,
        "natural": lambda r: "source" not in r,
        "failures": lambda r: "source" in r,
    }
    out: dict[str, Any] = {"model": args.model, "effort": args.effort, "split": args.split}
    for group, member in groups.items():
        pairs = [
            (lab, v)
            for lab, v in zip(labels, verdicts, strict=True)
            if member(cases[label_key(lab)])
        ]
        if pairs:
            out[group] = {
                key: agreement([lab[key] for lab, _ in pairs], [getattr(v, key) for _, v in pairs])
                for key in ("faithful", "correct")
            }
    if planted:
        out["planted"] = planted_score(planted, planted_verdicts)
    out["disagreements"] = [
        {
            "case_id": label_key(lab),
            "source": cases[label_key(lab)].get("source", "natural"),
            "human": {"faithful": lab["faithful"], "correct": lab["correct"]},
            "judge": v.model_dump(),
        }
        for lab, v in zip(labels, verdicts, strict=True)
        if (lab["faithful"], lab["correct"]) != (v.faithful, v.correct)
    ]
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    (JUDGE_DIR / f"calibration_{args.split}.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8"
    )
    if args.split == "heldout":
        LOCK.write_text(
            json.dumps({"model": args.model, "effort": args.effort}) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: out[k] for k in [*groups, "planted"] if k in out}, indent=1))
    return 0


def heldout_pairs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Each held-out human label with the judge's verdict, rebuilt from the
    calibration file (which lists the disagreements; the rest agreed)."""
    result = json.loads((JUDGE_DIR / "calibration_heldout.json").read_text(encoding="utf-8"))
    cases = {case_id(r): r for r in _read(SAMPLE) + _read(EXTRA)}
    differ = {d["case_id"]: d["judge"] for d in result["disagreements"]}
    pairs = []
    for lab in _read(LABELS):
        key = label_key(lab)
        if cases[key]["judge_split"] != "heldout":
            continue
        judged = differ.get(key, {"faithful": lab["faithful"], "correct": lab["correct"]})
        pairs.append(
            {"case": cases[key], "human": lab, "judge": judged, "source": cases[key].get("source")}
        )
    return pairs, result


def _fmt(ci: tuple[float, float, float] | None) -> str:
    if ci is None:
        return "not defined (no human 'no' labels)"
    return f"{ci[0]:.2f} [{ci[1]:.2f}, {ci[2]:.2f}]"


def cmd_summary(_args: argparse.Namespace) -> int:
    pairs, result = heldout_pairs()
    lines = [
        "# Judge calibration: held-out results",
        "",
        f"Judge: `{result['model']}`, effort {result['effort']}, prompt 2 (`regradar/judge.py`).",
        "Scored once (`eval/judge/heldout.lock`). Written by `python -m regradar.judge summary`",
        "from `calibration_heldout.json` and `eval/human/judge_labels.jsonl`.",
        "",
        "| Cases | n | Label | Agreement | Cohen's kappa [95% CI] | Human yes | Judge yes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    groups: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("all labelled", lambda p: True),
        ("natural sample", lambda p: p["source"] is None),
    ]
    for group, member in groups:
        chosen = [p for p in pairs if member(p)]
        for key in ("correct", "faithful"):
            h = [bool(p["human"][key]) for p in chosen]
            m = [bool(p["judge"][key]) for p in chosen]
            agree = bootstrap_ci([float(x == y) for x, y in zip(h, m, strict=True)])
            lines.append(
                f"| {group} | {len(chosen)} | {key} | {100 * agree[0]:.1f} "
                f"[{100 * agree[1]:.1f}, {100 * agree[2]:.1f}] | {_fmt(kappa_ci(h, m))} "
                f"| {100 * sum(h) / len(h):.0f}% | {100 * sum(m) / len(m):.0f}% |"
            )
    planted = result.get("planted")
    if planted:
        flags = [1.0] * planted["caught"] + [0.0] * (planted["n"] - planted["caught"])
        rate = bootstrap_ci(flags)
        lines += [
            "",
            f"Planted errors marked unfaithful: {planted['caught']}/{planted['n']} = "
            f"{100 * rate[0]:.1f}% [{100 * rate[1]:.1f}, {100 * rate[2]:.1f}]; by kind "
            + ", ".join(f"{k} {v}" for k, v in planted["by_kind"].items())
            + f". Missed: {', '.join(planted['missed'])}.",
        ]
    (JUDGE_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
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
    steps.add_parser("summary", help="held-out results with intervals").set_defaults(
        run=cmd_summary
    )
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
