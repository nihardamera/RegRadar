"""The public demo: cited answers, saved impact reports, and the evaluation.

    uv run python -m regradar.demo build-index          # a local Qdrant file from cached vectors
    REGRADAR_MODEL=claude-haiku-5-5 REGRADAR_SPEND=1 uv run python -m regradar.demo serve

Built for a free CPU Space: retrieval runs on an embedded Qdrant file (no
server) with the same models and fusion as the evaluation. Only /ask-style
questions call the model, and they are fenced in three ways:

    - a spend cap (`DEMO_BUDGET_USD`, default $1) on a ledger of its own;
    - a rate limit per visitor (5 questions in 10 minutes) and per day (200);
    - questions answered before are served from the cache at no cost.

Impact reports are not generated live (one costs cents and takes minutes):
the tab shows the reports the evaluation produced. The company in them is
synthetic.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from regradar.answer import ContextChunk, answer

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = Path(os.environ.get("DEMO_INDEX", ROOT / "demo_index"))
CACHE = ROOT / "data" / "demo_cache"
PER_VISITOR = (5, 600)  # questions, seconds
PER_DAY = 200
EXAMPLES = [
    "Within how many hours must a non-bank payment system operator report a cyber incident to RBI?",
    "Can a lender capitalise penal charges on a loan account?",
    "What is the maximum default loss guarantee cover on a digital lending portfolio?",
    "How often must credit institutions report credit information to credit bureaus?",
]


class RateLimit:
    def __init__(self, per_visitor: tuple[int, int] = PER_VISITOR, per_day: int = PER_DAY) -> None:
        self.limit, self.window = per_visitor
        self.per_day = per_day
        self.visits: dict[str, deque[float]] = defaultdict(deque)
        self.day: tuple[str, int] = ("", 0)
        self.lock = threading.Lock()

    def allow(self, visitor: str, now: float | None = None) -> str | None:
        """None if the question may go ahead; otherwise why not."""
        now = time.time() if now is None else now
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self.lock:
            seen = self.visits[visitor]
            while seen and now - seen[0] > self.window:
                seen.popleft()
            if len(seen) >= self.limit:
                return f"limit reached: {self.limit} questions per {self.window // 60} minutes"
            day, count = self.day if self.day[0] == today else (today, 0)
            if count >= self.per_day:
                return "the demo's daily question limit is reached; try again tomorrow"
            seen.append(now)
            self.day = (day, count + 1)
        return None


def build_index(path: Path = INDEX_PATH) -> int:
    from qdrant_client import QdrantClient

    from regradar.index import build

    client = QdrantClient(path=str(path))
    count = build(client, "section")
    client.close()
    return count


def render_answer(result: Any, hits: list[Any]) -> str:
    sources = {h.chunk_id: h.payload for h in hits}
    if result.status == "not_found":
        return "**Not found in the corpus.** None of the retrieved circulars answers this."
    if result.status == "rejected":
        return (
            "**No answer.** The model's answer cited text that does not support it, twice, "
            "so it was withheld:\n\n" + "\n".join(f"- {p}" for p in result.problems)
        )
    lines = []
    for claim in result.claims:
        refs = []
        for cid in claim.citations:
            p = sources[cid]
            label = f"{p['title']}" + (f", {p['section']}" if p.get("section") else "")
            refs.append(f"[{label}]({p['page_url']})" if p.get("page_url") else label)
        lines.append(f"- {claim.text}  \n  <sub>Source: {'; '.join(refs)}</sub>")
    return "\n".join(lines)


def app() -> Any:
    import gradio as gr
    from qdrant_client import QdrantClient

    from regradar.index import QueryEncoders, Retriever
    from regradar.llm import ANSWER_SCHEMA, BudgetExceeded, Claude, DryRun

    model = os.environ.get("REGRADAR_MODEL", "claude-haiku-5-5")
    budget = float(os.environ.get("DEMO_BUDGET_USD", "1.00"))
    claude = Claude(
        model,
        "demo",
        spend=os.environ.get("REGRADAR_SPEND") == "1",
        schema=ANSWER_SCHEMA,
        budget_usd=budget,
        cache_dir=CACHE,
    )
    client = (
        QdrantClient(url=os.environ["QDRANT_URL"])
        if os.environ.get("QDRANT_URL")
        else QdrantClient(path=str(INDEX_PATH))
    )
    retriever = Retriever(client, "section", encoders=QueryEncoders(("granite",)))
    limits = RateLimit()

    def ask(question: str, request: gr.Request) -> str:
        question = (question or "").strip()
        if not 5 <= len(question) <= 300:
            return "Ask a question of 5 to 300 characters."
        why = limits.allow(getattr(request.client, "host", "anon") if request else "anon")
        if why:
            return f"**Please wait.** {why}."
        hits = retriever.search(question, mode="hybrid", k=5)
        chunks = [ContextChunk(h.chunk_id, h.payload["title"], h.payload["text"]) for h in hits]
        try:
            result = answer(question, chunks, claude)
        except (BudgetExceeded, DryRun):
            return (
                "**The demo's spending cap is reached**, so only questions asked before "
                "are answered."
            )
        return render_answer(result, hits)

    reports = sorted((ROOT / "eval" / "impact").glob("*.md"))
    names = [p.stem for p in reports]

    def show(name: str) -> str:
        path = ROOT / "eval" / "impact" / f"{name}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    evaluation = "\n\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "eval" / "results" / "ABLATION.md", ROOT / "eval" / "judge" / "SUMMARY.md")
        if p.exists()
    )
    with gr.Blocks(title="RegRadar") as blocks:
        gr.Markdown(
            "# RegRadar\nCited answers over ~290 RBI circulars and Master Directions. Every claim "
            "cites the circular text it rests on, and code checks the citations before an answer "
            "is shown. A research demo, not legal advice."
        )
        with gr.Tab("Ask"):
            box = gr.Textbox(label="Question", placeholder=EXAMPLES[0])
            out = gr.Markdown()
            gr.Examples(EXAMPLES, inputs=box)
            box.submit(ask, inputs=box, outputs=out)
            gr.Button("Ask").click(ask, inputs=box, outputs=out)
        with gr.Tab("Impact reports"):
            gr.Markdown(
                "Obligations from a circular, matched against the policies of **FlexiPay India, "
                "a synthetic company** with planted gaps. Generated offline by the evaluation."
            )
            pick = gr.Dropdown(names, value=names[0] if names else None, label="Report")
            report = gr.Markdown(show(names[0]) if names else "")
            pick.change(show, inputs=pick, outputs=report)
        with gr.Tab("Evaluation"):
            gr.Markdown(evaluation)
    return blocks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("build-index")
    serve = steps.add_parser("serve")
    serve.add_argument("--port", type=int, default=7860)
    args = parser.parse_args(argv)
    if args.step == "build-index":
        print(f"{build_index()} chunks -> {INDEX_PATH}")
        return 0
    app().launch(server_name="0.0.0.0", server_port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
