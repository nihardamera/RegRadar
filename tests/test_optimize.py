"""The DSPy program, its metric and the engine, with scripted models (no API)."""

from __future__ import annotations

from types import SimpleNamespace

import dspy
import pytest
from dspy.utils.dummies import DummyLM

from regradar.answer import ContextChunk
from regradar.evaluate import Retrieved
from regradar.golden import load
from regradar.optimize import CitedAnswerer, ClaudeEngine, score

QUESTIONS = {q.id: q for q in load()}


def _answerable():
    q = next(q for q in QUESTIONS.values() if q.answerable and len(q.gold) == 1)
    span = q.gold[0].spans[0]
    holding = Retrieved("c-gold", span.doc_id, span.start, span.end, 50)
    other = Retrieved("c-other", "rbi-x", 0, 10, 50)
    return q, [holding, other]


def pred(status: str, cited: list[str] = (), problems: list[str] = ()):  # type: ignore[assignment]
    claims = [{"text": "x", "citations": [c]} for c in cited]
    return SimpleNamespace(status=status, claims=claims, problems=list(problems))


def test_a_fully_cited_answer_scores_one_and_a_stray_citation_halves_precision() -> None:
    q, retrieved = _answerable()
    assert score(q, retrieved, pred("answered", ["c-gold"]))[0] == 1.0
    value, feedback = score(q, retrieved, pred("answered", ["c-gold", "c-other"]))
    assert value == pytest.approx(0.75) and "c-other" in feedback


def test_declining_an_answerable_question_scores_zero_and_says_where_the_answer_was() -> None:
    q, retrieved = _answerable()
    value, feedback = score(q, retrieved, pred("not_found"))
    assert value == 0.0 and "c-gold" in feedback
    value, feedback = score(q, retrieved, pred("rejected", problems=["claim 1 cites nothing"]))
    assert value == 0.0 and "claim 1 cites nothing" in feedback


def test_unanswerable_questions_score_for_declining() -> None:
    q = next(q for q in QUESTIONS.values() if not q.answerable)
    assert score(q, [], pred("not_found"))[0] == 1.0
    assert score(q, [], pred("rejected"))[0] == 1.0
    value, feedback = score(q, [], pred("answered", ["c1"]))
    assert value == 0.0 and "not_found" in feedback


CHUNKS = [ContextChunk("c1", "Cyber Directions", "Incidents shall be reported within 6 hours.")]


def test_the_program_keeps_an_answer_that_passes_the_checks() -> None:
    claims = [{"text": "Incidents are reported within 6 hours.", "citations": ["c1"]}]
    with dspy.context(
        lm=DummyLM([{"not_found": "False", "claims": str(claims).replace("'", '"')}])
    ):
        out = CitedAnswerer()(question="How soon are incidents reported?", chunks=CHUNKS)
    assert out.status == "answered" and out.attempts == 1


def test_the_program_retries_once_then_rejects_an_unsupported_number() -> None:
    bad = '[{"text": "Incidents are reported within 2 hours.", "citations": ["c1"]}]'
    lm = DummyLM([{"not_found": "False", "claims": bad}, {"not_found": "False", "claims": bad}])
    with dspy.context(lm=lm):
        out = CitedAnswerer()(question="How soon are incidents reported?", chunks=CHUNKS)
    assert out.status == "rejected" and out.attempts == 2
    assert "numbers its citations do not" in out.problems[0]


def test_the_engine_passes_system_and_turns_to_our_client() -> None:
    seen = {}

    class FakeClaude:
        model = "claude-haiku-5-5"

        def chat(self, system: str, messages: list[dict[str, str]]) -> str:
            seen["system"], seen["messages"] = system, messages
            return "[[ ## answer ## ]]\nsix hours\n\n[[ ## completed ## ]]"

    lm = dspy.LM("anthropic/claude-haiku-5-5", engine=ClaudeEngine(FakeClaude()), cache=False)  # type: ignore[arg-type]
    with dspy.context(lm=lm, adapter=dspy.ChatAdapter()):
        out = dspy.Predict("question -> answer")(question="How soon?")
    assert out.answer == "six hours"
    assert seen["messages"][-1]["role"] == "user" and "How soon?" in seen["messages"][-1]["content"]
    assert "question" in seen["system"]


def test_when_retrieval_missed_the_answer_declining_is_right() -> None:
    q, retrieved = _answerable()
    missed = [r for r in retrieved if r.chunk_id == "c-other"]
    assert score(q, missed, pred("not_found"))[0] == 1.0
    assert score(q, missed, pred("answered", ["c-other"]))[0] == 0.0
