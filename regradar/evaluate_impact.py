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


_ROW = re.compile(r"^\| ([GN]\d+) \| ([^|]+) \|.*?`(rbi-[a-z0-9]+)`")
_REF = re.compile(r"(F[PC]-\d+) §(\d+)")


def gap_key(path: Path = GAP_KEY) -> list[KeyRow]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m:
            refs = tuple((doc, major) for doc, major in _REF.findall(m.group(2)))
            rows.append(KeyRow(m.group(1), refs, m.group(3)))
    return rows


def _heading(ref: str) -> tuple[str, str] | None:
    m = re.match(r"(F[PC]-\d+) §(\d+)", ref)
    return (m.group(1), m.group(2)) if m else None


def flags(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in report["ratings"] if r["status"] in NEEDS_ACTION]


def matches(rating: dict[str, Any], row: KeyRow) -> bool:
    cited = {_heading(ref) for ref in rating["policy_refs"]}
    return any(ref in cited for ref in row.refs)


def score(reports: dict[str, dict[str, Any]], rows: list[KeyRow]) -> dict[str, Any]:
    per_row = {}
    for row in rows:
        report = reports.get(row.doc_id)
        hit = report is not None and any(matches(r, row) for r in flags(report))
        per_row[row.id] = hit
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
        "gap_recall": bootstrap_ci(found),
        "traps_flagged": f"{sum(per_row[row.id] for row in traps)}/{len(traps)}",
        "per_row": per_row,
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


def cmd_score(args: argparse.Namespace) -> int:
    result = score(_load(args.model), gap_key())
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
