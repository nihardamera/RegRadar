"""The impact pipeline's code checks, with scripted model replies and no API."""

from __future__ import annotations

import json
from collections.abc import Iterator

from regradar.chunking import Chunk, CleanDocument
from regradar.company import PolicySection, policy_sections
from regradar.impact import (
    Action,
    Obligation,
    Rating,
    Report,
    extract,
    match,
    obligation_problems,
    plan,
    rating_problems,
    report_problems,
    verdict,
)

SECTION = (
    "22. Incident reporting (d) All cyber incidents shall be reported to RBI in the "
    "Incident Reporting Format within 6 hours of detection. (e) The PSO may engage CERT-In."
)
DOC = CleanDocument("rbi-n1", "Cyber Resilience Directions", "Effective April 1, 2026. " + SECTION)
CHUNK = Chunk("rbi-n1:section:0001", "rbi-n1", "section", SECTION, 25, 25 + len(SECTION), 1, "22")
POLICY = PolicySection(
    "FP-06",
    "3.2",
    "Reporting",
    "Incidents are reported to RBI within 24 hours of detection.",
    "Cyber Incident Response Procedure",
    "Chief Information Security Officer",
    "FlexiPay India Private Limited",
)
SHOWN = {POLICY.ref: POLICY}


def script(*replies: object) -> tuple[list[str], object]:
    """A fake model that returns the replies in order and records the prompts."""
    prompts: list[str] = []
    queue: Iterator[object] = iter(replies)

    def generate(_system: str, user: str) -> str:
        prompts.append(user)
        reply = next(queue)
        return reply if isinstance(reply, str) else json.dumps(reply)

    return prompts, generate


OBLIGATION = {
    "text": "Report cyber incidents to RBI within 6 hours of detection.",
    "applies_to": "non-bank PSOs",
    "deadline": None,
    "paragraph": "22(d)",
    "quote": "All cyber incidents shall be reported to RBI in the Incident Reporting Format",
}


def _obligation(**changes: object) -> Obligation:
    return Obligation(**{**OBLIGATION, **changes, "id": "o1", "chunk_id": CHUNK.chunk_id})


def _rating(**changes: object) -> Rating:
    base = {
        "obligation": "o1",
        "applies": True,
        "status": "gap",
        "policy_refs": ["FP-06 §3.2"],
        "policy_quote": "reported to RBI within 24 hours",
        "finding": "24 hours against 6.",
        "severity": "high",
        "action": "Report incidents within 6 hours.",
    }
    return Rating(**{**base, **changes})


# --- obligations


def test_an_obligation_must_quote_the_section_and_its_deadline_must_be_in_the_circular() -> None:
    assert obligation_problems(_obligation(), SECTION, DOC.text) == []
    assert obligation_problems(
        _obligation(quote="reported to RBI within 2 hours of detection"), SECTION, DOC.text
    ) == ["the quote is not in the section"]
    assert obligation_problems(_obligation(deadline="April 1, 2026"), SECTION, DOC.text) == []
    problems = obligation_problems(_obligation(deadline="April 1, 2027"), SECTION, DOC.text)
    assert problems == ["the deadline has numbers the circular does not: 2027"]


def test_a_bad_obligation_is_sent_back_once_then_dropped() -> None:
    wrong = {**OBLIGATION, "quote": "incidents shall be reported to RBI within two hours"}
    prompts, generate = script({"obligations": [wrong]}, {"obligations": [wrong]})
    result = extract(CHUNK, DOC, generate)
    assert result.obligations == [] and result.attempts == 2
    assert "failed checks" in prompts[1]
    assert result.dropped[0]["problems"] == ["the quote is not in the section"]


def test_obligations_that_pass_get_ids_from_their_section() -> None:
    _, generate = script({"obligations": [OBLIGATION]})
    result = extract(CHUNK, DOC, generate)
    assert [o.id for o in result.obligations] == ["rbi-n1:section:0001#1"]
    assert result.attempts == 1 and result.dropped == []


# --- ratings (v1's contradictions, and citations)


def test_a_good_gap_rating_passes() -> None:
    assert rating_problems(_rating(), SHOWN) == []


def test_v1s_contradiction_does_not_apply_but_rated_high_is_refused() -> None:
    problems = rating_problems(_rating(applies=False), SHOWN)
    assert "says the rule does not apply but rates it gap" in problems
    na = _rating(applies=False, status="not_applicable", policy_refs=[], action=None)
    assert "rates it not_applicable yet gives severity high" in rating_problems(na, SHOWN)


def test_met_with_an_action_and_gap_without_one_are_refused() -> None:
    met = _rating(status="met", severity="none")
    assert rating_problems(met, SHOWN) == ["rates it met yet gives an action"]
    assert "rates it gap but gives no action" in rating_problems(_rating(action=None), SHOWN)
    assert "rates it gap with severity none" in rating_problems(_rating(severity="none"), SHOWN)


def test_citations_must_be_shown_paragraphs_and_quotes_must_be_in_them() -> None:
    assert rating_problems(_rating(policy_refs=["FP-99 §1.1"]), SHOWN) == [
        "cites paragraphs it was not shown: FP-99 §1.1"
    ]
    assert rating_problems(_rating(policy_quote="reported within 6 hours always"), SHOWN) == [
        "the quote is not in FP-06 §3.2"
    ]
    assert "rates it gap without citing a policy paragraph" in rating_problems(
        _rating(policy_refs=[]), SHOWN
    )


def test_matching_retries_the_failing_ratings_and_leaves_what_still_fails_unrated() -> None:
    first, second = _obligation(), _obligation(id="o2", text="Keep logs for 180 days.")
    second.id = "o2"
    good = _rating().model_dump()
    bad = _rating(obligation="o2", status="met", severity="none").model_dump()  # has an action
    prompts, generate = script({"ratings": [good, bad]}, {"ratings": [bad]})
    result = match([first, second], lambda q, k: [POLICY], generate, "profile")
    assert [r.obligation for r in result.ratings] == ["o1"]
    assert result.unrated == [
        {"obligation": "o2", "problems": ["rates it met yet gives an action"]}
    ]
    assert "o2" in prompts[1] and result.attempts == 2


def test_an_obligation_the_model_leaves_out_is_unrated() -> None:
    _, generate = script({"ratings": []}, {"ratings": []})
    result = match([_obligation()], lambda q, k: [POLICY], generate, "profile")
    assert result.ratings == [] and result.unrated[0]["problems"] == ["not rated"]


# --- plan and report


def test_the_plan_is_built_by_code_from_gaps_with_the_policy_owner() -> None:
    ratings = [_rating(), _rating(obligation="o2", status="met", severity="none", action=None)]
    obligations = [_obligation(deadline="April 1, 2026"), _obligation(id="o2")]
    obligations[1].id = "o2"
    actions = plan(obligations, ratings, SHOWN)
    assert actions == [
        Action(
            "o1",
            "Report incidents within 6 hours.",
            "Chief Information Security Officer",
            "P1",
            "April 1, 2026",
            ["FP-06 §3.2"],
        )
    ]


def _report(**changes: object) -> Report:
    base = Report("rbi-n1", "t", [_obligation()], [_rating()], [], [], [], "")
    for key, value in changes.items():
        setattr(base, key, value)
    return base


def test_report_checks_catch_v1s_no_changes_needed_alongside_actions() -> None:
    action = plan([_obligation()], [_rating()], SHOWN)
    report = _report(actions=action, verdict="no action needed")
    assert "says no action is needed but lists actions or items for review" in report_problems(
        report
    )
    assert report_problems(_report(actions=action, verdict=verdict(action, []))) == []


def test_report_checks_catch_a_gap_without_an_action_and_an_unrated_obligation() -> None:
    problems = report_problems(_report(verdict="action needed"))
    assert "gap o1 has no action" in problems
    unrated = _report(ratings=[], verdict="needs review")
    assert report_problems(unrated) == ["obligation o1 is not rated"]
    in_review = _report(ratings=[], review=[{"obligation": "o1"}], verdict="needs review")
    assert report_problems(in_review) == []


def test_the_verdict_is_never_no_action_while_items_wait_for_review() -> None:
    assert verdict([], []) == "no action needed"
    assert verdict([], [{"kind": "unrated obligation"}]) == "needs review"


def test_policies_split_into_citable_paragraphs_with_owners() -> None:
    sections = {s.ref: s for s in policy_sections()}
    assert sections["FP-06 §3.2"].owner and "24 hours" in sections["FP-06 §3.2"].text
    assert sections["FC-13 §4.1"].entity.startswith("FlexiCredit")


def test_the_gap_key_parses_and_scoring_matches_on_policy_and_heading() -> None:
    from regradar.evaluate_impact import gap_key, score

    rows = gap_key()
    assert [r.id for r in rows] == [f"G{i}" for i in range(1, 13)] + ["N1", "N2", "N3"]
    g6 = next(r for r in rows if r.id == "G6")
    assert g6.refs == (("FC-16", "2"),) and g6.doc_id == "rbi-n12704"
    assert next(r for r in rows if r.id == "G9").refs == (("FP-00", "3"), ("FP-12", "6"))
    # N1's explanation names rbi-n12715; its circular column is rbi-n12562.
    assert next(r for r in rows if r.id == "N1").doc_id == "rbi-n12562"
    assert len({r.doc_id for r in rows}) == 12

    def report(*ratings: dict) -> dict:
        return {"ratings": list(ratings), "problems": [], "counts": {}}

    flag = {"status": "gap", "policy_refs": ["FC-16 §2.2"]}
    met = {"status": "met", "policy_refs": ["FP-06 §3.2"]}
    trap = {"status": "gap", "policy_refs": ["FP-20 §3.1"]}
    other = {"status": "partial", "policy_refs": ["FP-04 §1.1"]}
    result = score(
        {"rbi-n12704": report(flag, other), "rbi-n12715": report(met), "rbi-n12898": report(trap)},
        rows,
    )
    assert result["per_row"]["G6"] and not result["per_row"]["G1"]
    assert result["traps_flagged"] == "1/3" and result["gaps_found"] == "1/12"
    assert result["unkeyed_flags"] == 1  # the stray partial; the trap counts as trapped


def test_the_wilson_interval_does_not_collapse_at_twelve_of_twelve() -> None:
    from regradar.evaluate_impact import wilson

    low, high = wilson(12, 12)
    assert high == 1.0 and 0.75 < low < 0.76
