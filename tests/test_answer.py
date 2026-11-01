"""Citation enforcement with scripted model replies: code decides whether an
answer stands, whatever the model claims."""

from __future__ import annotations

import json

from regradar.answer import NOT_FOUND, Answer, ContextChunk, answer, parse

CHUNKS = [
    ContextChunk(
        "rbi-n12715:section:0042",
        "Master Directions on Cyber Resilience for non-bank PSOs",
        "(d) Unusual incidents like cyber-attacks shall be reported to RBI in the Incident "
        "Reporting Format within 6 hours of detection.",
    ),
    ContextChunk(
        "rbi-n12527:section:0003",
        "Penal Charges in Loan Accounts",
        "There shall be no capitalisation of penal charges i.e., no further interest computed.",
    ),
]
QUESTION = "Within how many hours must a PSO report a cyber attack to RBI?"


def reply(*claims: tuple[str, list[str]], not_found: bool = False) -> str:
    return json.dumps(
        {"not_found": not_found, "claims": [{"text": t, "citations": c} for t, c in claims]}
    )


GOOD = reply(
    (
        "Cyber-attacks must be reported to RBI within 6 hours of detection.",
        ["rbi-n12715:section:0042"],
    )
)


class Scripted:
    """Replays replies in order and records the prompts it was given."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, system: str, user: str) -> str:
        self.prompts.append(user)
        return self.replies.pop(0)


def test_a_cited_and_supported_answer_stands_first_time() -> None:
    result = answer(QUESTION, CHUNKS, Scripted(GOOD))
    assert result.status == "answered" and result.attempts == 1
    assert result.cited == ["rbi-n12715:section:0042"]
    assert result.text.endswith("[rbi-n12715:section:0042]")


def test_an_invented_citation_is_sent_back_and_the_fix_accepted() -> None:
    invented = reply(("Report within 6 hours of detection.", ["rbi-n99999:section:0001"]))
    model = Scripted(invented, GOOD)
    result = answer(QUESTION, CHUNKS, model)
    assert result.status == "answered" and result.attempts == 2
    assert "cites chunks it was not given: rbi-n99999:section:0001" in model.prompts[1]


def test_a_number_the_citation_does_not_contain_is_rejected_after_the_retry() -> None:
    """The failure that matters most here: the right source, the wrong limit."""
    wrong = reply(
        (
            "Cyber-attacks must be reported to RBI within 24 hours of detection.",
            ["rbi-n12715:section:0042"],
        )
    )
    result = answer(QUESTION, CHUNKS, Scripted(wrong, wrong))
    assert result.status == "rejected" and result.attempts == 2
    assert result.problems == ["claim 1 states numbers its citations do not: 24"]
    assert result.text == NOT_FOUND


def test_a_claim_its_citation_does_not_support_is_caught() -> None:
    unsupported = reply(
        (
            "Lenders may capitalise penal charges quarterly after notice.",
            ["rbi-n12715:section:0042"],
        )
    )
    result = answer(QUESTION, CHUNKS, Scripted(unsupported, unsupported))
    assert result.status == "rejected"
    assert "shares only" in result.problems[0]


def test_a_claim_without_citations_is_caught() -> None:
    bare = reply(("Within 6 hours of detection.", []))
    result = answer(QUESTION, CHUNKS, Scripted(bare, GOOD))
    assert result.attempts == 2 and result.status == "answered"


def test_not_found_is_an_answer_when_it_is_clean() -> None:
    result = answer("What is SEBI's intraday margin?", CHUNKS, Scripted(reply(not_found=True)))
    assert result.status == "not_found" and result.text == NOT_FOUND


def test_not_found_with_claims_contradicts_itself() -> None:
    both = reply(("Within 6 hours of detection.", ["rbi-n12715:section:0042"]), not_found=True)
    result = answer(QUESTION, CHUNKS, Scripted(both, both))
    assert result.status == "rejected"
    assert result.problems == ["says not found but also makes claims"]


def test_a_reply_that_is_not_json_is_retried_then_rejected() -> None:
    result = answer(QUESTION, CHUNKS, Scripted("Six hours, I believe.", "Still prose."))
    assert result.status == "rejected" and "not the required JSON" in result.problems[0]
    assert isinstance(result, Answer) and len(result.raw) == 2


def test_a_fenced_reply_is_unwrapped() -> None:
    parsed = parse(f"Here you go:\n```json\n{GOOD}\n```")
    assert parsed.claims[0].citations == ["rbi-n12715:section:0042"]


def test_a_number_the_question_gives_is_not_held_against_the_claim() -> None:
    """The model restating "a 30-day loan" is not a claim the source must back."""
    restated = reply(
        (
            "For a 30-day loan, cyber-attacks must be reported to RBI within 6 hours of detection.",
            ["rbi-n12715:section:0042"],
        )
    )
    result = answer(
        "For a 30-day loan, how soon must a cyber attack be reported?", CHUNKS, Scripted(restated)
    )
    assert result.status == "answered"


def test_an_identifier_matches_whatever_its_separators_became() -> None:
    chunks = [
        ContextChunk(
            "c1", "Repeal list", "1. DPSS.CO.PD.No.447/02.14.003/2019- 20 dated August 21, 2019"
        )
    ]
    cited = reply(("It repeals DPSS.CO.PD.No.447/02.14.003/2019-20 of August 21, 2019.", ["c1"]))
    assert answer("Which circulars are repealed?", chunks, Scripted(cited)).status == "answered"


def test_a_wrong_short_number_is_still_caught_when_the_question_has_others() -> None:
    wrong = reply(
        (
            "For a 30-day loan, cyber-attacks must be reported within 24 hours of detection.",
            ["rbi-n12715:section:0042"],
        )
    )
    result = answer("For a 30-day loan, how soon?", CHUNKS, Scripted(wrong, wrong))
    assert result.problems == ["claim 1 states numbers its citations do not: 24"]
