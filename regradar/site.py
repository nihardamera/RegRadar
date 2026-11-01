"""The static demo: a page of committed results, for a free static Space.

    uv run python -m regradar.site build --out site/

Hugging Face hosts static Spaces for free but charges for Gradio ones, so the
public demo is a static page built from the evaluation's committed files: the
150 golden questions with the cited answers Haiku 5.5 gave (and the golden
reference beside each), the 12 impact reports, and the result write-ups. It
makes no model calls and runs no search; `regradar.demo` is the live version.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from regradar.demo import stored_answers
from regradar.golden import load
from regradar.index import metadata

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/nihardamera/RegRadar/blob/main"
_RELATIVE_LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)\s]+)\)")
WRITE_UPS = {
    "Retrieval ablation": ROOT / "eval" / "results" / "ABLATION.md",
    "Judge calibration": ROOT / "eval" / "judge" / "SUMMARY.md",
    "Impact vs gap key": ROOT / "eval" / "results" / "IMPACT.md",
    "DSPy": ROOT / "eval" / "results" / "DSPY.md",
    "v1 vs v2": ROOT / "examples" / "v1_vs_v2.md",
}


def answers_data() -> list[dict[str, Any]]:
    golden = {q.id: q for q in load()}
    meta = metadata()
    rows = []
    for qid, row in sorted(stored_answers().items()):
        q = golden[qid]

        def source(cid: str) -> dict[str, Any]:
            m = meta.get(cid.split(":")[0], {})
            return {"id": cid, "title": m.get("title") or cid, "url": m.get("page_url")}

        rows.append(
            {
                "id": qid,
                "question": q.question,
                "type": q.type,
                "split": q.split,
                "answerable": q.answerable,
                "reference": q.answer,
                "status": row["status"],
                "problems": row["problems"],
                "claims": [
                    {"text": c["text"], "sources": [source(cid) for cid in c["citations"]]}
                    for c in row["claims"]
                ],
            }
        )
    return rows


def absolute_links(text: str, source: Path) -> str:
    """Links relative to a file in the repository, pointed at the file on GitHub."""

    def fix(m: re.Match[str]) -> str:
        target = os.path.normpath(source.parent.relative_to(ROOT) / m.group(1))
        return f"]({REPO_URL}/{target})"

    return _RELATIVE_LINK.sub(fix, text)


def _copy(source: Path, target: Path) -> None:
    target.write_text(absolute_links(source.read_text(encoding="utf-8"), source), encoding="utf-8")


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "data" / "impact").mkdir(parents=True)
    (out / "data" / "answers.json").write_text(json.dumps(answers_data()), encoding="utf-8")
    reports = []
    for path in sorted((ROOT / "eval" / "impact").glob("*.md")):
        _copy(path, out / "data" / "impact" / path.name)
        title = (
            path.read_text(encoding="utf-8")
            .splitlines()[0]
            .removeprefix("# RegRadar impact report: ")
        )
        reports.append({"file": f"data/impact/{path.name}", "title": title})
    write_ups = []
    for n, (name, path) in enumerate(WRITE_UPS.items()):
        target = out / "data" / f"writeup{n}.md"
        _copy(path, target)
        write_ups.append({"file": f"data/{target.name}", "title": name})
    index = {"reports": reports, "writeups": write_ups}
    (out / "data" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    shutil.copy(Path(__file__).parent / "site_index.html", out / "index.html")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    b = steps.add_parser("build")
    b.add_argument("--out", type=Path, default=ROOT / "site")
    args = parser.parse_args(argv)
    build(args.out)
    print(f"static demo -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
