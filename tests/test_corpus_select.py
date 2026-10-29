"""Choosing the circulars, and assembling each one into a corpus document.
Titles are real RBI titles."""

from __future__ import annotations

from typing import Any

import pytest

from regradar.corpus.document import describe, near_duplicates
from regradar.corpus.pdf import PageText, ParsedPdf
from regradar.corpus.select import relevant, select


@pytest.mark.parametrize(
    "title",
    [
        "Guidelines on Default Loss Guarantee (DLG) in Digital Lending",
        "Fair Lending Practice - Penal Charges in Loan Accounts",
        "Master Direction on Information Technology Governance, Risk, Controls and Assurance"
        " Practices",
        "Regulation of Payment Aggregator – Cross Border (PA - Cross Border)",
        "Amendment to Master Direction on Prepaid Payment Instruments",
        "Master Directions on Fraud Risk Management in Non-Banking Financial Companies (NBFCs)"
        " (including Housing Finance Companies)",
        "Frequency of reporting of credit information by Credit Institutions to Credit"
        " Information Companies",
        "Reserve Bank of India (Non-Banking Financial Companies – Know Your Customer)"
        " Directions, 2025",
    ],
)
def test_flexipays_subjects_are_kept(title: str) -> None:
    assert relevant(title)


@pytest.mark.parametrize(
    "title",
    [
        "₹2000 Denomination Banknotes – Withdrawal from Circulation",
        "Sovereign Gold Bond (SGB) Scheme 2023-24",
        "Levy of charges on forex prepaid cards/store value cards/travel cards, etc.",
        "Customer complaints relating to ATM transactions",
        "Master Circular - Management of Advances - UCBs",
        "Reserve Bank of India (Commercial Banks – Know Your Customer) Directions, 2025",
        "Reserve Bank of India (Small Finance Banks – Credit Facilities) Amendment"
        " Directions, 2026",
        "Capital Adequacy Guidelines – Review of Trading Book",
    ],
)
def test_other_entities_and_markets_are_left_out(title: str) -> None:
    assert not relevant(title)


def test_the_newest_relevant_pages_with_a_pdf_are_chosen() -> None:
    pages = [
        {"id": 1, "ok": True, "pdf_url": "a.pdf", "title": "Digital Lending Directions"},
        {"id": 3, "ok": True, "pdf_url": "c.pdf", "title": "Penal Charges in Loan Accounts"},
        {"id": 4, "ok": True, "pdf_url": None, "title": "KYC amendment"},
        {"id": 5, "ok": False, "title": "Payment Aggregators"},
        {"id": 6, "ok": True, "pdf_url": "f.pdf", "title": "Sovereign Gold Bond"},
        {"id": 2, "ok": True, "pdf_url": "b.pdf", "title": "Cyber Resilience for PSOs"},
    ]
    assert [p["id"] for p in select(pages, limit=2)] == [3, 2]


PAGE: dict[str, Any] = {
    "id": 12898,
    "title": "Reserve Bank of India (Authentication mechanisms) Directions, 2025",
    "page_url": "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12898&Mode=0",
    "capture_url": "https://web.archive.org/web/1id_/x",
    "pdf_url": "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT79.PDF",
}
BODY = (
    "RBI/2025-26/79\nCO.DPSS.POLC.No. S 668/02-14-015/2025-2026\nSeptember 25, 2025\n"
    + "1. Introduction\nAll digital payment transactions shall meet two factors. " * 12
)


def parsed(text: str, scanned: bool = False) -> ParsedPdf:
    page = PageText(1, text, 0, scanned, 1.0 if scanned else 0.0, 1.0)
    return ParsedPdf([page])


class TestDescribe:
    def test_the_pdf_is_the_text_of_record_and_the_html_checks_it(self) -> None:
        row = describe(PAGE, BODY, parsed(BODY))
        assert (row["text_source"], row["status"]) == ("pdf", "ok")
        assert row["circular_number"] == "RBI/2025-26/79"
        assert row["department"] == "DPSS" and row["date"] == "2025-09-25"
        assert row["kind"] == "directions" and row["doc_id"] == "rbi-n12898"
        assert row["html_in_pdf_recall"] == 1.0

    def test_text_the_pdf_parse_dropped_shows_in_the_html_comparison(self) -> None:
        row = describe(
            PAGE, BODY + "\n2. Annex: a long table of repealed circulars " * 40, parsed(BODY)
        )
        assert row["html_in_pdf_recall"] < 0.9

    def test_a_scanned_pdf_falls_back_to_the_html(self) -> None:
        row = describe(PAGE, BODY, parsed("", scanned=True))
        assert (row["text_source"], row["status"]) == ("html", "ok")
        assert row["scanned_pages"] == [1]

    def test_a_scanned_pdf_without_html_is_listed_not_used(self) -> None:
        row = describe(PAGE, "", parsed("", scanned=True))
        assert (row["text_source"], row["status"]) == (None, "scanned")

    def test_metadata_comes_from_the_pdf_when_the_page_has_no_text(self) -> None:
        row = describe(PAGE, "", parsed(BODY))
        assert row["circular_number"] == "RBI/2025-26/79" and row["text_source"] == "pdf"
        assert "html_in_pdf_recall" not in row

    def test_no_pdf_and_no_html_means_no_text(self) -> None:
        row = describe(PAGE, "", None, "no capture of the PDF in the archive")
        assert row["status"] == "no_text" and row["pdf_problem"].startswith("no capture")


def test_near_copies_keep_the_first_listed() -> None:
    kyc = "All regulated entities shall carry out customer due diligence before opening " * 20
    texts = [
        ("rbi-n3", kyc + "This applies to NBFCs."),
        ("rbi-n2", kyc + "This applies to commercial banks."),
        (
            "rbi-n1",
            "Penal charges shall not be capitalised and no further interest computed. " * 20,
        ),
    ]
    assert near_duplicates(texts) == {"rbi-n2": "rbi-n3"}


def test_the_audit_is_computed_from_the_manifest_and_names_every_left_out_document() -> None:
    from regradar.corpus.audit import render, summary

    base = {"title": "T", "kind": "circular", "department": "DPSS", "text_source": "pdf"}
    rows = [
        base
        | {
            "doc_id": "rbi-n3",
            "status": "ok",
            "in_corpus": True,
            "date": "2025-09-25",
            "circular_number": "RBI/2025-26/79",
            "pages": 9,
            "tables": 2,
            "html_in_pdf_recall": 0.99,
            "low_recall_pages": [],
        },
        base
        | {
            "doc_id": "rbi-n2",
            "status": "ok",
            "in_corpus": True,
            "date": "2024-07-30",
            "pages": 4,
            "tables": 0,
            "html_in_pdf_recall": 0.62,
            "low_recall_pages": [3],
        },
        base
        | {
            "doc_id": "rbi-n1",
            "status": "near_duplicate",
            "duplicate_of": "rbi-n3",
            "in_corpus": False,
            "text_source": "pdf",
        },
        base
        | {
            "doc_id": "rbi-n0",
            "status": "scanned",
            "in_corpus": False,
            "text_source": None,
            "scanned_pages": [1, 2],
        },
    ]
    s = summary(rows)
    assert s["in_corpus"] == 2 and s["with_circular_number"] == 1
    assert s["html_below_floor"] == ["rbi-n2"] and s["low_recall_pages"] == {"rbi-n2": [3]}
    assert s["scanned_pages"] == {"rbi-n0": [1, 2]}
    assert s["date_range"] == ["2024-07-30", "2025-09-25"]
    text = render(rows)
    assert "near_duplicate of `rbi-n3`" in text and "`rbi-n0` T: scanned" in text
