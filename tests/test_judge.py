"""The judge's agreement statistics, and its prompt and parsing, without a model."""

from __future__ import annotations

import json

import pytest

from regradar.judge import agreement, cohen_kappa, judge, prompt


def test_kappa_matches_a_hand_computed_case() -> None:
    # 10 items: both yes 4, both no 3, human yes / judge no 2, human no / judge yes 1.
    human = [True] * 6 + [False] * 4
    model = [True] * 4 + [False] * 2 + [True] + [False] * 3
    # observed 0.7; expected 0.6*0.5 + 0.4*0.5 = 0.5; kappa = 0.2 / 0.5 = 0.4
    assert cohen_kappa(human, model) == pytest.approx(0.4)


def test_kappa_is_one_for_perfect_and_zero_for_chance_agreement() -> None:
    labels = [True, False, True, True, False]
    assert cohen_kappa(labels, labels) == 1.0
    assert cohen_kappa([True, True, False, False], [True, False, True, False]) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        cohen_kappa([True], [True, False])


def test_agreement_reports_raw_agreement_and_base_rates() -> None:
    out = agreement([True, True, False, False], [True, True, True, False])
    assert out == {"n": 4, "agreement": 0.75, "kappa": 0.5, "human_yes": 0.5, "judge_yes": 0.75}


RECORD = {
    "claims": [{"text": "Report within 6 hours.", "citations": ["c1"]}],
    "context": {"c1": "Incidents shall be reported to RBI within 6 hours of detection."},
}


def test_the_judge_sees_the_cited_text_and_the_reference() -> None:
    text = prompt("How soon?", "Within 6 hours.", RECORD["claims"], RECORD["context"])
    assert "within 6 hours of detection" in text and "Reference answer: Within 6 hours." in text


def test_a_verdict_is_parsed_from_the_reply() -> None:
    reply = json.dumps({"faithful": True, "correct": False, "reason": "Misses the CERT-In part."})
    verdict = judge(RECORD, "Within 6 hours.", "How soon?", lambda s, u: f"```json\n{reply}\n```")
    assert verdict.faithful and not verdict.correct
