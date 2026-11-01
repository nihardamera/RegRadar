"""Score the impact pipeline against the gap key (company/GAP_KEY.md).

    uv run python -m regradar.evaluate_impact run --model M [--spend]   # all key circulars
    uv run python -m regradar.evaluate_impact score --model M           # from saved reports

The key lists 12 gaps planted in the synthetic policies (G1-G12) and 3 traps
that look like gaps but are not (N1-N3: not applicable, superseded,
permissive). For each circular in the key, the pipeline's gap and partial
ratings are compared with the key's rows for that circular:

    found     a gap or partial cites the key's policy, in the same section
              (same heading number: "FC-16 §2.2" matches a key of §2.1-2.2)
    trapped   a trap row's policy section is rated gap or partial

Flags that match no key row are counted and listed, not scored: the key
lists what was planted, not every way the policies could fall short, so an
unkeyed flag may be a real gap or a false one, and needs a person to say.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from regradar.evaluate import bootstrap_ci
from regradar.impact import NEEDS_ACTION, REPORTS, analyse, markdown, to_json

ROOT = Path(__file__).resolve().parent.parent
GAP_KEY = ROOT / "company" / "GAP_KEY.md"
RESULTS = ROOT / "eval" / "results"


@dataclass(frozen=True)
class KeyRow:
    id: str
    refs: tuple[tuple[str, str], ...]  # (policy doc, heading number)
    doc_id: str

    @property
    def trap(self) -> bool:
        return self.id.startswith("N")


_ID = re.compile(r"^[GN]\d+$")
_REF = re.compile(r"(F[PC]-\d+) §(\d+)")
_DOC = re.compile(r"`(rbi-[a-z0-9]+)`")
CIRCULAR_COLUMN = 4  # ID | Policy | ... | ... | Circular | Status, in both tables


def gap_key(path: Path = GAP_KEY) -> list[KeyRow]:
    """The key's G and N rows. The circular is read from its own column: other
    columns can name other circulars (N1's explanation cites rbi-n12715)."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) > CIRCULAR_COLUMN and _ID.match(cells[0]):
            doc = _DOC.search(cells[CIRCULAR_COLUMN])
            if doc:
                refs = tuple(_REF.findall(cells[1]))
                rows.append(KeyRow(cells[0], refs, doc.group(1)))
    return rows


def _heading(ref: str) -> tuple[str, str] | None:
    m = re.match(r"(F[PC]-\d+) §(\d+)", ref)
    return (m.group(1), m.group(2)) if m else None


# The strict match: the flag must also state the planted rule's key fact. Each
# pattern is taken from the "The rule" column of GAP_KEY.md (and, for traps,
# from what the trap is about), fixed before scoring.
KEY_FACT = {
    "G1": r"\b6 hours|six hours",
    "G2": r"penal interest|rate of interest|capitali",
    "G3": r"cooling",
    "G4": r"five per ?cent|\b5 ?%|\b5 per ?cent|\b8 ?%",
    "G5": r"fortnight",
    "G6": r"21 days|show cause|reasonable time",
    "G7": r"automatic",
    "G8": r"\bKFS\b|key facts",
    "G9": r"25 crore",
    "G10": r"core portion|interest",
    "G11": r"7(:00)? ?p\.?m|7 pm|8(:00)? ?a\.?m",
    "G12": r"\bIndia\b|Singapore|located",
    "N1": r"IT Strategy Committee|ITSC|quarterly|meet",
    "N2": r"T\+3|settle",
    "N3": r"risk-based|step-up|behavioural|contextual",
}


def flags(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in report["ratings"] if r["status"] in NEEDS_ACTION]


def matches(rating: dict[str, Any], row: KeyRow, strict: bool = False) -> bool:
    cited = {_heading(ref) for ref in rating["policy_refs"]}
    if not any(ref in cited for ref in row.refs):
        return False
    if not strict:
        return True
    said = f"{rating.get('finding', '')} {rating.get('action') or ''}"
    return re.search(KEY_FACT[row.id], said, re.IGNORECASE) is not None


def score(reports: dict[str, dict[str, Any]], rows: list[KeyRow]) -> dict[str, Any]:
    per_row, strict_row = {}, {}
    for row in rows:
        report = reports.get(row.doc_id)
        candidates = flags(report) if report is not None else []
        per_row[row.id] = any(matches(r, row) for r in candidates)
        strict_row[row.id] = any(matches(r, row, strict=True) for r in candidates)
    gaps = [row for row in rows if not row.trap]
    traps = [row for row in rows if row.trap]
    unkeyed = []
    for doc_id, report in sorted(reports.items()):
        keyed = [row for row in rows if row.doc_id == doc_id]
        for r in flags(report):
            if not any(matches(r, row) for row in keyed):
                unkeyed.append({"doc_id": doc_id, **r})
    found = [1.0 if per_row[row.id] else 0.0 for row in gaps]
    return {
        "gaps_found": f"{int(sum(found))}/{len(gaps)}",
        "gaps_found_strict": f"{sum(strict_row[row.id] for row in gaps)}/{len(gaps)}",
        "gap_recall": bootstrap_ci(found),
        "traps_flagged": f"{sum(per_row[row.id] for row in traps)}/{len(traps)}",
        "traps_flagged_strict": f"{sum(strict_row[row.id] for row in traps)}/{len(traps)}",
        "per_row": per_row,
        "per_row_strict": strict_row,
        "flags": sum(len(flags(r)) for r in reports.values()),
        "unkeyed_flags": len(unkeyed),
        "check_problems": {d: r["problems"] for d, r in reports.items() if r["problems"]},
        "counts": {d: r["counts"] for d, r in sorted(reports.items())},
        "unkeyed": unkeyed,
    }


def _load(model: str) -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(REPORTS.glob(f"*_{model}.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["doc_id"]] = data
    return out


def cmd_run(args: argparse.Namespace) -> int:
    from regradar.index import QueryEncoders, connect

    client, encoders = connect(), QueryEncoders()
    REPORTS.mkdir(parents=True, exist_ok=True)
    for doc_id in sorted({row.doc_id for row in gap_key()}):
        report = analyse(doc_id, args.model, args.spend, client, encoders)
        stem = REPORTS / f"{doc_id}_{args.model}"
        stem.with_suffix(".json").write_text(
            json.dumps(to_json(report), indent=1) + "\n", encoding="utf-8"
        )
        stem.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
        print(f"{doc_id}: {report.verdict}, {to_json(report)['counts']}", file=sys.stderr)
    return cmd_score(args)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k of n: unlike the bootstrap, it does not collapse
    to [100, 100] when every one of a few items is found."""
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def write_up(result: dict[str, Any], model: str, cost: float | None) -> str:
    """eval/results/IMPACT.md, generated from the scored result."""
    n = len([k for k in result["per_row"] if k.startswith("G")])
    k = sum(v for key, v in result["per_row"].items() if key.startswith("G"))
    ks = sum(v for key, v in result["per_row_strict"].items() if key.startswith("G"))
    low, high = wilson(k, n)
    slow, shigh = wilson(ks, n)
    applicable = sum(
        c["obligations"] - c.get("not_applicable", 0) for c in result["counts"].values()
    )
    totals: dict[str, int] = {}
    for c in result["counts"].values():
        for key, value in c.items():
            totals[key] = totals.get(key, 0) + value
    lines = [
        "# Impact pipeline against the gap key",
        "",
        f"Model `{model}`; {len(result['counts'])} circulars, every one named in "
        "[`company/GAP_KEY.md`](../../company/GAP_KEY.md). Generated by "
        "`python -m regradar.evaluate_impact score` from `eval/impact/*.json`."
        + (f" API cost of the run: ${cost:.2f}." if cost is not None else ""),
        "",
        "| Measure | Result |",
        "| --- | --- |",
        f"| Planted gaps found, strict: the flag states the rule's key fact | "
        f"**{result['gaps_found_strict']}** = {100 * ks / n:.0f}% "
        f"[{100 * slow:.0f}, {100 * shigh:.0f}] (Wilson 95%) |",
        f"| Planted gaps found, lenient: a flag cites the right policy section | "
        f"{result['gaps_found']} = {100 * k / n:.0f}% [{100 * low:.0f}, {100 * high:.0f}] |",
        f"| Traps flagged as gaps (N1-N3; lower is better), strict / lenient | "
        f"**{result['traps_flagged_strict']}** / {result['traps_flagged']} |",
        f"| Gap or partial flags in all (share of applicable obligations) | {result['flags']} "
        f"({100 * result['flags'] / max(1, applicable):.0f}%) |",
        f"| Flags matching no key row (need a person) | {result['unkeyed_flags']} |",
        "| Obligations extracted / rated not applicable / not covered | "
        f"{totals.get('obligations', 0)} / {totals.get('not_applicable', 0)} / "
        f"{totals.get('not_covered', 0)} |",
        f"| Items in the review queue | {totals.get('review', 0)} |",
        f"| Reports failing a code check | {len(result['check_problems'])} |",
        "",
        "Per key row (Y = found or, for N rows, flagged):",
        "",
        "| Match | " + " | ".join(result["per_row"]) + " |",
        "| --- | " + " | ".join("---" for _ in result["per_row"]) + " |",
        "| strict | "
        + " | ".join("Y" if v else "-" for v in result["per_row_strict"].values())
        + " |",
        "| lenient | " + " | ".join("Y" if v else "-" for v in result["per_row"].values()) + " |",
        "",
        "Matching: a gap or partial rating from the key's circular that cites the key's "
        "policy in the same section (heading number); strict also requires the finding or "
        "action to state the rule's key fact (`KEY_FACT` in `regradar/evaluate_impact.py`, "
        "taken from the key's rule text). **Recall is not the whole story:** the "
        "pipeline flags many obligations, and precision is not measured. The key lists "
        "what was planted, not every shortfall, so unkeyed flags are neither right nor "
        "wrong until a person reviews them; they are listed in `impact_<model>.json`.",
    ]
    return "\n".join(lines) + "\n"


def cmd_score(args: argparse.Namespace) -> int:
    from regradar.llm import Ledger

    result = score(_load(args.model), gap_key())
    ledger = Ledger(ROOT / "data" / "llm_cache" / "ledger.jsonl")
    cost = sum(float(e["usd"]) for e in ledger.entries() if e["purpose"].startswith("impact"))
    (RESULTS / "IMPACT.md").write_text(write_up(result, args.model, cost or None), encoding="utf-8")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"impact_{args.model}.json"
    out.write_text(json.dumps({"model": args.model, **result}, indent=1) + "\n", encoding="utf-8")
    shown = {k: result[k] for k in ("gaps_found", "gap_recall", "traps_flagged", "flags")}
    print(json.dumps({**shown, "unkeyed_flags": result["unkeyed_flags"]}, indent=1))
    print("per row:", " ".join(f"{k}:{'Y' if v else '-'}" for k, v in result["per_row"].items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    run = steps.add_parser("run")
    run.add_argument("--model", required=True)
    run.add_argument("--spend", action="store_true")
    run.set_defaults(run=cmd_run)
    sc = steps.add_parser("score")
    sc.add_argument("--model", required=True)
    sc.set_defaults(run=cmd_score)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
