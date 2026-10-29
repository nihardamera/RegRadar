"""Reading PDFs: tables, scanned pages, and the cross-check that catches dropped
text. The PDFs are generated here, so each case is known exactly."""

from __future__ import annotations

import pymupdf
import pytest

from regradar.corpus.pdf import (
    UnreadablePdf,
    parse_pdf,
    table_markdown,
    word_recall,
)


def pdf_bytes(*pages: list[tuple[str, tuple[float, float]]]) -> bytes:
    document = pymupdf.open()
    for lines in pages:
        page = document.new_page()
        for text, (x, y) in lines:
            page.insert_text((x, y), text)
    data: bytes = document.tobytes()
    return data


def table_pdf() -> bytes:
    """A paragraph, a ruled 3 x 2 table, then a paragraph after it."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "1. Limits for prepaid instruments are as below.")
    cells = [["Instrument", "Limit"], ["Small PPI", "10,000"], ["Full-KYC PPI", "2,00,000"]]
    top, row_height, columns = 100.0, 24.0, (72.0, 252.0, 432.0)
    for r, row in enumerate(cells):
        y = top + r * row_height
        for c, value in enumerate(row):
            page.insert_text((columns[c] + 4, y + 16), value)
    for r in range(len(cells) + 1):
        y = top + r * row_height
        page.draw_line((columns[0], y), (columns[-1], y))
    for x in columns:
        page.draw_line((x, top), (x, top + len(cells) * row_height))
    page.insert_text((72, 200), "2. These limits apply from April 1, 2026.")
    data: bytes = document.tobytes()
    return data


def scanned_pdf() -> bytes:
    """One page that is only a picture of text, as a scanner would make it."""
    source = pymupdf.open()
    source.new_page().insert_text((72, 72), "Scanned circular text", fontsize=20)
    picture = source[0].get_pixmap(dpi=72).tobytes("png")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=picture)
    data: bytes = document.tobytes()
    return data


class TestReading:
    def test_text_is_read_in_order_and_cross_checked(self) -> None:
        data = pdf_bytes([("1. Introduction", (72, 72)), ("2. Applicability to PAs", (72, 100))])
        parsed = parse_pdf(data)
        assert parsed.text.splitlines() == ["1. Introduction", "2. Applicability to PAs"]
        assert parsed.pages[0].reference_recall == 1.0
        assert parsed.low_recall_pages == [] and parsed.scanned_pages == []

    def test_a_table_becomes_markdown_once_in_reading_order(self) -> None:
        parsed = parse_pdf(table_pdf())
        text = parsed.text
        assert parsed.table_count == 1
        assert "| Instrument | Limit |" in text
        assert "| Full-KYC PPI | 2,00,000 |" in text
        assert text.count("Small PPI") == 1  # not also repeated as loose text
        assert text.index("1. Limits") < text.index("| Instrument") < text.index("2. These limits")
        assert parsed.pages[0].reference_recall == 1.0

    def test_a_scanned_page_is_detected_not_silently_empty(self) -> None:
        parsed = parse_pdf(scanned_pdf())
        assert parsed.scanned_pages == [1]
        assert parsed.is_scanned
        assert parsed.pages[0].image_share > 0.9

    def test_a_page_that_is_mostly_text_is_not_called_scanned(self) -> None:
        parsed = parse_pdf(
            pdf_bytes([("A letterhead and a long paragraph of real text " * 3, (20, 72))])
        )
        assert parsed.scanned_pages == []

    def test_garbage_is_refused(self) -> None:
        with pytest.raises(UnreadablePdf):
            parse_pdf(b"<html>a challenge page, not a PDF</html>")


class TestTheCrossCheck:
    def test_recall_counts_repeated_words(self) -> None:
        assert word_recall("the bank the bank", "the bank the bank") == 1.0
        assert word_recall("the bank", "the bank the bank") == 0.5

    def test_a_dropped_paragraph_shows_up_as_low_recall(self) -> None:
        reference = (
            "1. Payment aggregators shall settle within T+1. 2. Escrow balances are reported daily."
        )
        found = "1. Payment aggregators shall settle within T+1."
        assert word_recall(found, reference) < 0.6

    def test_an_empty_reference_is_not_a_failure(self) -> None:
        assert word_recall("anything", "") == 1.0


def test_table_cells_with_pipes_and_ragged_rows_stay_one_table() -> None:
    markdown = table_markdown([["A", "B|C"], ["1"], [None, None]])
    assert markdown.splitlines() == ["| A | B\\|C |", "| --- | --- |", "| 1 |  |"]
