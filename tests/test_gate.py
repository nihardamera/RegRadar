"""The CI gate fails on a real drop, tolerates noise, and uses a fixed subset."""

from __future__ import annotations

from regradar.gate import TOLERANCE, problems, subset
from regradar.golden import load


def test_a_drop_beyond_the_tolerance_fails_and_noise_does_not() -> None:
    baseline = {"hit@10": 90.0, "mrr": 75.0}
    assert problems({"hit@10": 90.0 - TOLERANCE["hit@10"], "mrr": 75.0}, baseline) == []
    failed = problems({"hit@10": 83.3, "mrr": 75.0}, baseline)
    assert len(failed) == 1 and failed[0].startswith("hit@10 fell to 83.3")


def test_the_subset_is_fixed_answerable_dev_questions() -> None:
    questions = load()
    first, second = subset(questions), subset(list(reversed(questions)))
    assert [q.id for q in first] == [q.id for q in second]
    assert len(first) == 30 and all(q.split == "dev" and q.answerable for q in first)


def test_answer_metrics_catch_a_stricter_checker_and_worse_citations(monkeypatch) -> None:
    import json

    import regradar.answer
    from regradar.gate import ANSWERS, answer_scores

    questions = subset(load())
    answers = json.loads(ANSWERS.read_text(encoding="utf-8"))
    base = answer_scores(answers, questions)
    assert base["still_accepted"] == 100.0
    # A checker that demands near-verbatim claims rejects answers it used to accept.
    monkeypatch.setattr(regradar.answer, "SUPPORT_FLOOR", 0.95)
    stricter = answer_scores(answers, questions)
    assert problems(stricter, base) and stricter["still_accepted"] < base["still_accepted"]
    monkeypatch.undo()
    # Citations that point at nothing relevant lower citation precision.
    for row in answers["questions"].values():
        for c in row["cited"]:
            c["start"], c["end"] = 10**9, 10**9 + 1
    worse = answer_scores(answers, questions)
    assert worse["citation_precision"] == 0.0 and problems(worse, base)
