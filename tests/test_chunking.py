"""Cleaning and chunking. The text is shaped like the real corpus: a Hindi
letterhead, page footers, an index, numbered paragraphs and an annex."""

from __future__ import annotations

import re

import pytest

from regradar.chunking import (
    STRATEGIES,
    clean,
    fixed_chunks,
    headings,
    numbering_report,
    recursive_chunks,
    section_chunks,
)

LETTERHEAD = "भारतीय रिज़र्व बैंक\nRESERVE BANK OF INDIA\nwww.rbi.org.in"
FOOTER = (
    "Department of Payment and Settlement Systems, Central Office Building, Shaheed Bhagat Singh"
    " Marg, Mumbai\nTel No: 22601000 Fax No: 022-2270 5670"
)
BODY = (
    "RBI/2025-26/79\nCO.DPSS.POLC.No. S 668/02-14-015/2025-2026\nSeptember 25, 2025\n"
    "Index\n1. Introduction\n2. Applicability\n3. Incident reporting\n"
    "1. Introduction\n"
    + "All digital payment transactions shall meet two factors of authentication. " * 6
    + "\n2. Applicability\n"
    + "These directions apply to all payment system providers and participants. " * 6
    + "\n3. Incident reporting\n"
    + "(a) Incidents shall be reported to RBI within 6 hours of detection. " * 25
    + "\n(b) Any cyber security incident shall also be reported to CERT-In. " * 25
    + "\nAnnex 1\n1. Format of the report\n"
    + "The report gives the time, systems and customers affected. " * 6
)


def document():
    pages = [
        (1, f"{LETTERHEAD}\n{BODY[: len(BODY) // 2]}\nPage 1 of 2\n{FOOTER}"),
        (2, f"{LETTERHEAD}\n{BODY[len(BODY) // 2 :]}\nPage 2 of 2\n{FOOTER}"),
    ]
    return clean("rbi-n1", "Authentication Directions", pages)


class TestCleaning:
    def test_letterhead_footer_and_page_numbers_go(self) -> None:
        text = document().text
        assert "भारतीय" not in text and "RESERVE BANK OF INDIA" not in text
        assert "Tel No" not in text and "Shaheed Bhagat Singh" not in text
        assert "Page 1 of 2" not in text
        assert text.startswith("RBI/2025-26/79")

    def test_dot_leader_index_lines_go(self) -> None:
        doc = clean("d", "t", [(1, "1. Introduction ........ 3\n1. Introduction\nThe text.")])
        assert doc.text == "1. Introduction\nThe text."

    def test_a_line_on_most_pages_is_a_running_header(self) -> None:
        pages = [
            (n, f"Master Direction on PPIs (Updated)\nPage {n} body text") for n in range(1, 5)
        ]
        doc = clean("d", "t", pages)
        assert "Updated" not in doc.text and doc.text.count("body text") == 4

    def test_offsets_map_back_to_pages(self) -> None:
        doc = clean("d", "t", [(1, "First page text."), (2, "Second page text.")])
        assert doc.text == "First page text.\n\nSecond page text."
        assert doc.page_at(0) == 1 and doc.page_at(doc.text.index("Second")) == 2


@pytest.mark.parametrize("strategy", sorted(STRATEGIES))
def test_every_word_is_in_some_chunk_and_offsets_are_exact(strategy: str) -> None:
    """Chunking must not drop text any more than parsing may."""
    doc = document()
    chunks = STRATEGIES[strategy](doc)
    assert all(c.text == doc.text[c.start : c.end] for c in chunks)
    covered = [False] * len(doc.text)
    for c in chunks:
        covered[c.start : c.end] = [True] * (c.end - c.start)
    lost = [m.group() for m in re.finditer(r"\S+", doc.text) if not covered[m.start()]]
    assert lost == []
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert chunks == STRATEGIES[strategy](document())  # deterministic


def test_fixed_windows_overlap_and_respect_the_size() -> None:
    chunks = fixed_chunks(document(), size=50, overlap=10)
    assert all(c.words <= 50 for c in chunks)
    assert chunks[0].text.split()[-10:] == chunks[1].text.split()[:10]


def test_recursive_chunks_stay_under_the_size() -> None:
    assert all(c.words <= 60 for c in recursive_chunks(document(), size=60))


class TestSections:
    def test_an_index_ending_in_annexes_is_skipped_but_the_first_heading_kept(self) -> None:
        """The layout of the authentication Directions' web page."""
        text = (
            "Index\n1. Introduction\n2. Short title\nAnnexure-1\nAnnexure-2\n"
            "1. Introduction\nAll digital payment transactions shall meet two factors.\n"
            "2. Short title\nThese are the Authentication Directions, 2025.\n"
        )
        found = [(h.kind, h.label) for h in headings(clean("d", "t", [(1, text)]).text)]
        assert found == [("top", "1"), ("top", "2")]

    def test_the_index_is_not_mistaken_for_sections(self) -> None:
        tops = [h.label for h in headings(document().text) if h.kind == "top"]
        assert tops == ["1", "2", "3", "1"]  # the body's 1-3, then the annex's 1

    def test_sections_follow_the_numbering_and_keep_their_path(self) -> None:
        chunks = section_chunks(document())

        def section_of(phrase: str) -> str | None:
            return next(c.section for c in chunks if phrase in c.text)

        assert section_of("apply to all payment system providers") == "2"
        assert section_of("Format of the report") == "Annex 1 > 1"

    def test_a_long_section_is_split_at_its_sub_items(self) -> None:
        reporting = [c for c in section_chunks(document(), max_words=350) if c.section == "3"]
        assert len(reporting) >= 2
        assert all(c.words <= 350 for c in reporting)
        assert any(c.text.startswith("(b)") for c in reporting)

    def test_a_bare_heading_joins_the_text_after_it(self) -> None:
        chunks = section_chunks(document())
        assert not any(c.text.strip() == "3. Incident reporting" for c in chunks)


class TestNumberingAnchors:
    def test_continuous_numbering_has_no_problems_and_an_annex_restarts(self) -> None:
        report = numbering_report(document())
        assert report.top_numbers == 4 and report.problems == []

    def test_a_gap_is_reported(self) -> None:
        text = "1. Introduction\n" + "Text here. " * 30 + "\n3. Reporting\n" + "More text. " * 30
        report = numbering_report(clean("d", "t", [(1, text)]))
        assert report.problems == ["body: 1 then 3"]
