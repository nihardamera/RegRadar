"""Scoring answers against the gold spans, with a fake retriever and scripted
replies: no Qdrant, no model, no cost."""

from __future__ import annotations

import json
from datetime import date

from regradar.answer import ContextChunk
from regradar.evaluate import Retrieved
from regradar.evaluate_answers import run, summarise
from regradar.golden import Part, Question, Span
from regradar.llm import DryRun

RIGHT = Retrieved("rbi-n12715:section:0042", "rbi-n12715", 100, 300, 40)
WRONG = Retrieved("rbi-n12527:section:0003", "rbi-n12527", 0, 200, 40)
CHUNKS = {
    RIGHT.chunk_id: ContextChunk(
        RIGHT.chunk_id, "Cyber Resilience", "reported to RBI within 6 hours of detection"
    ),
    WRONG.chunk_id: ContextChunk(
        WRONG.chunk_id, "Penal Charges", "no capitalisation of penal charges"
    ),
}


def question(qid: str, answerable: bool = True) -> Question:
    gold = (
        [Part(spans=[Span(doc_id="rbi-n12715", start=150, end=200, quote="x" * 50)])]
        if answerable
        else []
    )
    return Question.model_validate(
        {
            "id": qid,
            "question": "Within how many hours must a PSO report a cyber attack?",
            "type": "number_or_date" if answerable else "unanswerable",
            "answer": "6 hours",
            "gold": gold,
            "split": "dev",
            "written": date(2026, 10, 31),
        }
    )


def retrieve(_q: Question) -> list[tuple[Retrieved, ContextChunk]]:
    return [(RIGHT, CHUNKS[RIGHT.chunk_id]), (WRONG, CHUNKS[WRONG.chunk_id])]


def replies(*texts: str):  # type: ignore[no-untyped-def]
    queue = list(texts)
    return lambda system, user: queue.pop(0)


def cite(chunk_id: str, text: str) -> str:
    return json.dumps({"not_found": False, "claims": [{"text": text, "citations": [chunk_id]}]})


NOT_FOUND = json.dumps({"not_found": True, "claims": []})


def test_a_correct_citation_scores_full_precision_and_recall() -> None:
    rows, _ = run(
        [question("q001")],
        retrieve,
        replies(cite(RIGHT.chunk_id, "Report to RBI within 6 hours of detection.")),
    )
    assert rows[0].status == "answered"
    assert rows[0].citation_precision == 1.0 and rows[0].citation_recall == 1.0


def test_citing_the_wrong_chunk_scores_zero_even_when_the_checks_pass() -> None:
    """The text check passes (the claim matches what it cites); the gold says it
    is the wrong document."""
    rows, _ = run(
        [question("q001")],
        retrieve,
        replies(cite(WRONG.chunk_id, "There is no capitalisation of penal charges.")),
    )
    assert rows[0].status == "answered"
    assert rows[0].citation_precision == 0.0 and rows[0].citation_recall == 0.0


def test_unanswerable_questions_score_on_declining() -> None:
    rows, _ = run(
        [question("q002", answerable=False), question("q003", answerable=False)],
        retrieve,
        replies(NOT_FOUND, cite(RIGHT.chunk_id, "Report to RBI within 6 hours of detection.")),
    )
    summary = summarise(rows)
    assert summary["correctly_declined"][0] == 0.5 and summary["unanswerable"] == 2


def test_a_dry_run_prices_every_question_and_sends_nothing() -> None:
    def priced(system: str, user: str) -> str:
        raise DryRun(0.001)

    rows, estimate = run([question("q001"), question("q004")], retrieve, priced)
    assert rows == [] and abs(estimate - 0.004) < 1e-9
