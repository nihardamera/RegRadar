"""Answer the golden questions end to end and score the answers, without a judge.

    uv run python -m regradar.evaluate_answers --model claude-haiku-5-5 --split dev  # price it
    uv run python -m regradar.evaluate_answers --model ... --split dev --spend      # run it

Retrieval uses one configuration; the answer step is regradar.answer, whose
code checks reject unsupported citations. Scored per question, from the gold
spans alone:

    answerable    answered | wrongly said not found | rejected by the checks;
                  citation precision (share of cited chunks that overlap a
                  gold span) and recall (share of the answer's parts that a
                  cited chunk covers)
    unanswerable  correctly declined (not found, or rejected) | answered anyway

Whether the claims are *faithful* to what they cite is the judge's job (later);
these numbers say whether the system answered, abstained and cited correctly.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from regradar.answer import Answer, ContextChunk, answer
from regradar.evaluate import RESULTS, Config, Retrieved, bootstrap_ci, overlaps, part_found
from regradar.golden import Question, load
from regradar.llm import ANSWER_SCHEMA, Claude, DryRun

Retrieve = Callable[[Question], list[tuple[Retrieved, ContextChunk]]]


@dataclass
class Scored:
    question_id: str
    answerable: bool
    status: str
    attempts: int
    cited: list[str]
    citation_precision: float | None  # None when nothing was cited
    citation_recall: float | None  # None for unanswerable questions
    problems: list[str]
    claims: list[dict[str, Any]]  # what the model said, for labelling and the judge
    context: dict[str, str]  # chunk ID -> text, for every chunk the model was given


def score(
    question: Question,
    result: Answer,
    retrieved: Sequence[Retrieved],
    context: Sequence[ContextChunk] = (),
) -> Scored:
    by_id = {r.chunk_id: r for r in retrieved}
    cited = [by_id[c] for c in result.cited if c in by_id]
    precision = (
        sum(any(overlaps(c, s) for s in question.spans) for c in cited) / len(cited)
        if cited
        else None
    )
    recall = (
        sum(part_found(cited, part) for part in question.gold) / len(question.gold)
        if question.answerable
        else None
    )
    return Scored(
        question.id,
        question.answerable,
        result.status,
        result.attempts,
        result.cited,
        precision,
        recall,
        result.problems,
        [claim.model_dump() for claim in result.claims],
        {c.chunk_id: c.text for c in context},
    )


def summarise(rows: Sequence[Scored]) -> dict[str, Any]:
    answerable = [r for r in rows if r.answerable]
    unanswerable = [r for r in rows if not r.answerable]

    def rate(group: Sequence[Scored], test: Callable[[Scored], bool]) -> tuple[float, float, float]:
        return bootstrap_ci([1.0 if test(r) else 0.0 for r in group])

    cited = [r.citation_precision for r in answerable if r.citation_precision is not None]
    return {
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "answered": rate(answerable, lambda r: r.status == "answered"),
        "wrongly_not_found": rate(answerable, lambda r: r.status == "not_found"),
        "rejected": rate(answerable, lambda r: r.status == "rejected"),
        "citation_precision": bootstrap_ci(cited),
        "citation_recall": bootstrap_ci([r.citation_recall or 0.0 for r in answerable]),
        "correctly_declined": rate(unanswerable, lambda r: r.status != "answered"),
        "needed_a_retry": rate(rows, lambda r: r.attempts > 1),
    }


def qdrant_retrieve(config: Config, k: int) -> Retrieve:
    """The real retriever, built once (it loads the query encoders)."""
    from regradar.index import Retriever, connect

    retriever = Retriever(connect(), config.strategy)

    def retrieve(question: Question) -> list[tuple[Retrieved, ContextChunk]]:
        hits = retriever.search(
            question.question,
            config.mode,
            k=k,
            rerank=bool(config.rerank),
            candidates=config.rerank or 50,
        )
        return [
            (
                Retrieved(h.chunk_id, h.doc_id, h.start, h.end, len(h.payload["text"].split())),
                ContextChunk(h.chunk_id, h.payload["title"], h.payload["text"]),
            )
            for h in hits
        ]

    return retrieve


def run(
    questions: Sequence[Question],
    retrieve: Retrieve,
    generate: Callable[[str, str], str],
) -> tuple[list[Scored], float]:
    """Score every question; with a dry-run model, return the priced estimate."""
    rows: list[Scored] = []
    estimate = 0.0
    for question in questions:
        pairs = retrieve(question)
        retrieved = [r for r, _ in pairs]
        try:
            result = answer(question.question, [c for _, c in pairs], generate)
        except DryRun as dry:
            # Priced as if one retry were needed for every question: a ceiling.
            estimate += 2 * dry.estimate_usd
            continue
        rows.append(score(question, result, retrieved, [c for _, c in pairs]))
    return rows, estimate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", required=True, help="the answer model; there is no default")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--strategy", default="section")
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--rerank", type=int, default=0)
    parser.add_argument("-k", type=int, default=5, help="chunks given to the model")
    parser.add_argument("--effort", default="low")
    parser.add_argument(
        "--spend", action="store_true", help="send requests (otherwise only price them)"
    )
    args = parser.parse_args(argv)
    questions = [q for q in load() if args.split == "all" or q.split == args.split]
    config = Config(args.strategy, args.mode, args.rerank)
    llm = Claude(args.model, "answer", spend=args.spend, schema=ANSWER_SCHEMA, effort=args.effort)
    rows, estimate = run(questions, qdrant_retrieve(config, args.k), llm)
    if not args.spend:
        print(
            f"dry run: {len(questions)} questions with {args.model} would cost at most "
            f"${estimate:.2f} (with a retry for every one); spent so far ${llm.ledger.spent():.4f}"
        )
        return 0
    summary = summarise(rows)
    out = {
        "model": args.model,
        "effort": args.effort,
        "retrieval": config.name,
        "k": args.k,
        "split": args.split,
        "summary": summary,
        "questions": [asdict(r) for r in rows],
        "spent_usd_total": round(llm.ledger.spent(), 4),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    name = f"answers_{args.split}_{args.model}_{config.name.replace('/', '_')}"
    (RESULTS / f"{name}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
