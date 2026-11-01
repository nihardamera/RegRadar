"""The judge-calibration sample is fixed, answered-only, and split up front."""

from __future__ import annotations

import json
from pathlib import Path

from regradar.label import answered_records, draw


def test_only_answered_questions_with_claims_are_sampled(tmp_path: Path) -> None:
    rows = [
        {
            "question_id": "q001",
            "status": "answered",
            "claims": [{"text": "x", "citations": ["c"]}],
        },
        {"question_id": "q002", "status": "not_found", "claims": []},
        {"question_id": "q003", "status": "rejected", "claims": []},
    ]
    path = tmp_path / "answers_dev_claude-haiku-5-5_section_hybrid.json"
    path.write_text(json.dumps({"model": "m", "retrieval": "r", "questions": rows}))
    assert [r["question_id"] for r in answered_records(tmp_path)] == ["q001"]


def test_the_draw_is_reproducible_and_fixes_a_40_60_split() -> None:
    records = [{"question_id": f"q{i:03d}"} for i in range(1, 131)]
    first, second = draw(records), draw(list(reversed(records)))
    assert len(first) == 100
    assert [r["question_id"] for r in first] == [
        r["question_id"] for r in sorted(second, key=lambda r: r["question_id"])
    ]
    assert sum(r["judge_split"] == "dev" for r in first) == 40


def test_hard_cases_get_their_own_ids_and_a_fixed_split() -> None:
    from regradar.label import case_id, extra_cases, label_key, queue

    answered = [
        {
            "question_id": f"q{n:03d}",
            "claims": [
                {"text": f"Non-bank PAs shall not store data for {n} days.", "citations": ["c"]}
            ],
            "context": {
                "c": f"Non-bank PAs shall not store data for {n} days.",
                "d": "Other text.",
            },
        }
        for n in range(1, 41)
    ]
    failed = [{**answered[0], "status": "rejected", "source": "rejected"}]
    cases = extra_cases(answered, failed, sampled=set())
    assert cases == extra_cases(answered, failed, sampled=set())
    assert "q001~rejected" in {case_id(c) for c in cases}
    assert len({case_id(c) for c in cases}) == len(cases)
    assert sum(c["judge_split"] == "dev" for c in cases) == round(0.4 * len(cases))
    # Old labels carry only a question ID; new ones carry the case ID.
    assert label_key({"question_id": "q001"}) == "q001"
    assert label_key({"case_id": "q001~rejected", "question_id": "q001"}) == "q001~rejected"
    todo = queue([{"question_id": "q001"}, *cases], done={"q001"})
    assert len(todo) == len(cases) and todo == queue(list(reversed(cases)), done={"q001"})
