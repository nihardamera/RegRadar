"""Retrieval metrics on hand-made chunks, where the right answer is obvious."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from regradar.evaluate import (
    Config,
    Retrieved,
    bootstrap_ci,
    ndcg,
    paired_difference_ci,
    question_metrics,
    run,
)
from regradar.golden import Part, Question, Span


def span(doc: str, start: int, end: int) -> Span:
    return Span(doc_id=doc, start=start, end=end, quote="x" * (end - start))


def chunk(doc: str, start: int, end: int, name: str = "") -> Retrieved:
    return Retrieved(name or f"{doc}:{start}", doc, start, end, words=(end - start) // 5)


def question(parts: list[Part], qtype: str = "single_hop", qid: str = "q001") -> Question:
    return Question.model_validate(
        {
            "id": qid,
            "question": "A question long enough to be valid?",
            "type": qtype,
            "answer": "An answer.",
            "gold": parts,
            "split": "dev",
            "written": date(2026, 10, 31),
        }
    )


ANSWER = Part(spans=[span("a", 100, 200)])


class TestPerQuestion:
    def test_a_chunk_overlapping_the_answer_is_a_hit_at_its_rank(self) -> None:
        ranked = [chunk("b", 0, 500), chunk("a", 0, 120), chunk("a", 120, 300)]
        m = question_metrics(ranked, question([ANSWER]))
        assert m["hit@1"] == 0.0 and m["hit@5"] == 1.0
        assert m["mrr"] == pytest.approx(1 / 2)

    def test_span_recall_counts_an_answer_split_across_two_chunks(self) -> None:
        ranked = [chunk("a", 0, 150), chunk("a", 150, 400)]
        m = question_metrics(ranked, question([ANSWER]))
        assert m["span_recall@1"] == pytest.approx(0.5)
        assert m["span_recall@5"] == pytest.approx(1.0)

    def test_overlap_must_be_in_the_same_document(self) -> None:
        m = question_metrics([chunk("z", 100, 200)], question([ANSWER]))
        assert m["hit@10"] == 0.0 and m["mrr"] == 0.0 and m["span_recall@10"] == 0.0

    def test_any_alternative_satisfies_a_part(self) -> None:
        restated = Part(spans=[span("a", 100, 200), span("md", 10, 60)])
        m = question_metrics([chunk("md", 0, 80)], question([restated]))
        assert m["hit@1"] == 1.0 and m["span_recall@1"] == 1.0

    def test_multi_hop_needs_every_part(self) -> None:
        parts = [ANSWER, Part(spans=[span("c", 0, 50)])]
        q = question(parts, "multi_hop")
        one = question_metrics([chunk("a", 100, 200)], q)
        both = question_metrics([chunk("a", 100, 200), chunk("c", 0, 60)], q)
        assert one["hit@10"] == 0.0 and one["span_recall@10"] == pytest.approx(0.5)
        assert both["hit@10"] == 1.0

    def test_words_retrieved_are_reported(self) -> None:
        m = question_metrics([chunk("a", 0, 500), chunk("b", 0, 500)], question([ANSWER]))
        assert m["words@1"] == 100 and m["words@5"] == 200


class TestNdcg:
    def test_finding_every_part_first_is_perfect(self) -> None:
        parts = [ANSWER, Part(spans=[span("c", 0, 50)])]
        assert ndcg([chunk("a", 100, 200), chunk("c", 0, 50)], parts) == pytest.approx(1.0)

    def test_cutting_the_answer_into_more_pieces_earns_nothing_extra(self) -> None:
        """A second chunk of an already-found part adds no gain, so a strategy
        cannot score higher just by splitting answers finer."""
        whole = ndcg([chunk("a", 100, 200)], [ANSWER])
        pieces = ndcg([chunk("a", 100, 150), chunk("a", 150, 200)], [ANSWER])
        assert whole == pieces == pytest.approx(1.0)

    def test_a_later_hit_scores_less(self) -> None:
        assert ndcg([chunk("z", 0, 10), chunk("a", 100, 200)], [ANSWER]) == pytest.approx(
            1 / 1.5849625, rel=1e-6
        )


class TestIntervals:
    def test_the_interval_brackets_the_mean_and_is_reproducible(self) -> None:
        values = [1.0] * 70 + [0.0] * 30
        mean, low, high = bootstrap_ci(values)
        assert mean == pytest.approx(0.7) and low < 0.7 < high
        assert (low, high) == bootstrap_ci(values)[1:]
        assert low > 0.6 and high < 0.8

    def test_a_paired_difference_uses_the_same_questions(self) -> None:
        a = [0.0, 1.0, 0.0, 1.0] * 25
        b = [1.0, 1.0, 0.0, 1.0] * 25
        mean, low, _high = paired_difference_ci(a, b)
        assert mean == pytest.approx(0.25) and low > 0
        with pytest.raises(ValueError, match="same questions"):
            paired_difference_ci(a, b[:-1])


def test_run_scores_answerable_questions_and_caches_retrieval(tmp_path: Path) -> None:
    calls: list[str] = []

    def search(q: Question, config: Config) -> list[tuple[Retrieved, float]]:
        calls.append(q.id)
        return [(chunk("a", 100, 200), 0.9)]

    questions = [
        question([ANSWER]),
        question([], "unanswerable", qid="q002"),
    ]
    first = run(questions, Config("section", "hybrid"), search, tmp_path)
    assert first.questions == 1 and first.metrics["hit@1"][0] == 1.0
    assert first.unanswerable_top_scores == {"q002": 0.9}
    run(questions, Config("section", "hybrid"), search, tmp_path)
    assert calls == ["q001", "q002"]  # the second run read the cache
    assert Config("section", "hybrid", 20).name == "section/hybrid+rerank20"
