"""Planted errors: one claim changed by a fixed rule, without giving itself away."""

from __future__ import annotations

import random

from regradar.plant import KINDS, plant, planted_cases


def _record(text: str, chunk: str, qid: str = "q001") -> dict:
    return {
        "question_id": qid,
        "claims": [{"text": text, "citations": ["c1"]}],
        "context": {"c1": chunk, "c2": "Unrelated rules on the storage of card data by gateways."},
    }


def _after(record: dict, kind: str) -> str | None:
    case = plant(record, kind, random.Random(0))
    return None if case is None else case["planted"]["after"]


def test_a_changed_number_is_one_the_cited_text_does_not_contain() -> None:
    record = _record(
        "Report within 6 hours.", "Incidents shall be reported within 6 hours or 12 hours."
    )
    after = _after(record, "number")
    assert after is not None and after != "Report within 6 hours."
    assert "12" not in after and "6 " not in after


def test_number_changes_keep_indian_grouping_and_leave_dates_alone() -> None:
    chunk = "The limit is ₹1,00,000 from March 31, 2025."
    assert _after(_record("The limit is ₹1,00,000.", chunk), "number") == "The limit is ₹2,00,000."
    assert _after(_record("It applies from March 31, 2025.", chunk), "number") in (
        "It applies from March 31, 2024.",
        "It applies from March 31, 2026.",
    )


def test_negation_flips_and_the_month_may_is_not_a_modal() -> None:
    chunk = "The NBFC shall not disclose it."
    assert _after(_record("The NBFC shall not disclose it.", chunk), "negation") == (
        "The NBFC shall disclose it."
    )
    assert _after(_record("The circular of May 5, 2021 was extended.", chunk), "negation") is None


def test_entity_swaps_skip_proper_names_and_giveaway_phrases() -> None:
    chunk = "Non-bank PAs must apply."
    assert _after(_record("Non-bank PAs must apply.", chunk), "entity") == "Bank PAs must apply."
    assert _after(_record("The Reserve Bank of India decided it.", chunk), "entity") is None
    assert _after(_record("A bank or non-bank issuer may apply.", chunk), "entity") is None
    assert _after(_record("Credit it to the bank account only.", chunk), "entity") is None


def test_a_condition_is_dropped_but_a_verb_is_not() -> None:
    chunk = "Banks shall close the accounts unless the PA-CB has applied."
    after = _after(
        _record("Banks shall close the accounts unless the PA-CB applied.", chunk), "condition"
    )
    assert after == "Banks shall close the accounts."
    assert (
        _after(_record("Payments use the app provided by the PPI issuer.", chunk), "condition")
        is None
    )


def test_a_wrong_chunk_citation_points_at_a_retrieved_chunk_not_cited() -> None:
    case = plant(
        _record("Report within 6 hours.", "Report within 6 hours."), "wrong_chunk", random.Random(0)
    )
    assert case is not None and case["claims"][0]["citations"] == ["c2"]


def test_planted_cases_are_reproducible_and_use_each_answer_once() -> None:
    records = [
        _record(
            f"Non-bank PAs shall not store card data for {n} days, unless the RBI permits it.",
            f"Non-bank PAs shall not store card data for {n} days, unless the RBI permits it.",
            qid=f"q{n:03d}",
        )
        for n in range(1, 21)
    ]
    first = planted_cases(records, sampled={"q001"}, seed=7, per_kind=2)
    assert first == planted_cases(list(reversed(records)), sampled={"q001"}, seed=7, per_kind=2)
    assert sorted(c["planted"]["kind"] for c in first) == sorted(KINDS * 2)
    assert len({c["question_id"] for c in first}) == len(first)
    assert "q001" not in {c["question_id"] for c in first}  # answers outside the sample go first
