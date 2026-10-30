"""The golden set's machinery: quotes become exact ranges, the split cannot
move, and a change to the cleaner cannot silently shift an answer."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from regradar.chunking import clean
from regradar.golden import (
    Normalised,
    Part,
    Question,
    QuoteNotFound,
    Span,
    check,
    corpus,
    load,
    locate,
    next_id,
    overlap,
    restatements,
    span_holds,
    split_for,
)

DOC = clean(
    "rbi-n12527",
    "Fair Lending Practice - Penal Charges in Loan Accounts",
    [
        (
            1,
            "3. Penal charges shall not be levied in the form of penal interest.\n"
            "There shall be no capitalisation of penal charges i.e., no further\n"
            "interest computed on such charges.\n"
            "4. REs shall not introduce any additional component to the rate of interest.\n"
            "5. Penal charges shall be reasonable.",
        )
    ],
)


class TestLocate:
    def test_a_quote_across_a_line_break_resolves_to_the_exact_range(self) -> None:
        span = locate(DOC, "no capitalisation of penal charges i.e., no further interest computed")
        assert DOC.text[span.start : span.end] == span.quote
        assert " ".join(span.quote.split()).startswith("no capitalisation")
        assert "\n" in span.quote  # the stored quote is the document's own text

    def test_case_differences_are_allowed_when_nothing_matches_exactly(self) -> None:
        span = locate(DOC, "PENAL CHARGES SHALL BE REASONABLE")
        assert span.quote == "Penal charges shall be reasonable"

    def test_an_ambiguous_quote_must_say_which_occurrence(self) -> None:
        with pytest.raises(QuoteNotFound, match="2 matches"):
            locate(DOC, "Penal charges shall")
        second = locate(DOC, "Penal charges shall", occurrence=2)
        assert DOC.text[second.start :].startswith("Penal charges shall be reasonable")

    def test_every_occurrence_can_be_listed_to_choose_from(self) -> None:
        from regradar.golden import occurrences

        found = occurrences(DOC, "Penal charges shall")
        assert len(found) == 2 and found[0].start < found[1].start
        assert occurrences(DOC, "nothing like this anywhere") == []

    def test_a_missing_or_too_short_quote_is_refused(self) -> None:
        with pytest.raises(QuoteNotFound, match="not found"):
            locate(DOC, "penal charges may be capitalised quarterly")
        with pytest.raises(QuoteNotFound, match="three words"):
            locate(DOC, "penal")

    def test_normalising_keeps_every_kept_character_mapped(self) -> None:
        norm = Normalised.of("a  b\n\nc")
        assert norm.text == "a b c" and norm.origin == [0, 1, 3, 4, 6]


def question(**overrides: object) -> Question:
    fields: dict[str, object] = {
        "id": "q001",
        "question": "Can a lender add penal charges to the loan's interest rate?",
        "type": "single_hop",
        "answer": "No. Penal charges are not added to the rate or capitalised.",
        "gold": [Part(spans=[locate(DOC, "no capitalisation of penal charges")])],
        "split": split_for("q001"),
        "written": date(2026, 10, 31),
    }
    fields.update(overrides)
    return Question.model_validate(fields)


class TestQuestions:
    def test_the_type_decides_what_gold_is_needed(self) -> None:
        with pytest.raises(ValidationError, match="unanswerable question has no gold"):
            question(type="unanswerable")
        with pytest.raises(ValidationError, match="needs at least one gold span"):
            question(gold=[])
        with pytest.raises(ValidationError, match="at least two parts"):
            question(type="multi_hop")
        assert not question(type="unanswerable", gold=[]).answerable

    def test_ids_are_numbered(self) -> None:
        with pytest.raises(ValidationError):
            question(id="Q1")
        assert next_id([question(), question(id="q007", split=split_for("q007"))]) == "q008"
        assert next_id([]) == "q001"

    def test_the_split_is_fixed_by_the_id_and_about_a_third_is_dev(self) -> None:
        assert split_for("q042") == split_for("q042")
        dev = sum(split_for(f"q{i:03d}") == "dev" for i in range(1, 151))
        assert 35 <= dev <= 65


def test_the_same_rule_restated_elsewhere_is_offered_as_an_alternative() -> None:
    consolidated = clean(
        "rbi-md362",
        "NBFCs - Responsible Business Conduct Directions, 2025",
        [(1, "47. There shall be no capitalisation of penal charges, i.e., no further interest.")],
    )
    unrelated = clean("rbi-n1", "Something else", [(1, "Nothing about penal charges here at all.")])
    docs = {d.doc_id: d for d in (DOC, consolidated, unrelated)}
    span = locate(DOC, "no capitalisation of penal charges")
    assert [s.doc_id for s in restatements(docs, span)] == ["rbi-md362"]


class TestCheck:
    def test_a_good_question_has_no_problems(self) -> None:
        report = check([question()], {DOC.doc_id: DOC})
        assert report.problems == [] and report.by_type["single_hop"] == 1

    def test_a_moved_span_a_wrong_split_and_a_repeat_are_caught(self) -> None:
        moved = Span(doc_id=DOC.doc_id, start=3, end=20, quote="no capitalisation")
        flipped = "test" if split_for("q002") == "dev" else "dev"
        questions = [
            question(gold=[Part(spans=[moved])]),
            question(id="q002", split=flipped),
            question(id="q003", split=split_for("q003")),
        ]
        problems = check(questions, {DOC.doc_id: DOC}).problems
        assert any("no longer matches" in p for p in problems)
        assert any("q002: split is" in p for p in problems)
        assert any("same question as" in p for p in problems)

    def test_overlap_measures_how_much_the_question_borrows_the_circulars_words(self) -> None:
        quote = "There shall be no capitalisation of penal charges"
        assert overlap("Is there capitalisation of penal charges?", [quote]) == 1.0
        assert overlap("Can a lender add late fees to what the borrower owes?", [quote]) == 0.0


def test_every_committed_answer_still_points_at_its_quote() -> None:
    """If the cleaner or the corpus changes, the golden set must be re-checked,
    not silently scored against shifted text."""
    docs = corpus()
    broken = [(q.id, s.doc_id) for q in load() for s in q.spans if not span_holds(s, docs)]
    assert broken == []
