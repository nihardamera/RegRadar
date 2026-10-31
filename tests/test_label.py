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
