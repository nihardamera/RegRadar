"""Reading the archive index, the notification page and the circular's header.

The headers are copied from real RBI circulars, in the layouts the parser has
to handle: a Direction with no salutation, a circular with addressees, and a
FED circular whose reference is an A.P. (DIR Series) number.
"""

from __future__ import annotations

from datetime import date

import pytest

from regradar.corpus.metadata import (
    addressees,
    circular_number,
    department,
    document_kind,
    first_date,
    reference_number,
)
from regradar.corpus.rbi_html import NotACircularPage, parse_notification_page
from regradar.corpus.wayback import Capture, notification_id, page_id, parse_cdx

DIRECTION = """RBI/2025-26/79
CO.DPSS.POLC.No. S 668/02-14-015/2025-2026
September 25, 2025
Reserve Bank of India (Authentication mechanisms for digital payment transactions) Directions, 2025
Index
1. Introduction"""

CIRCULAR = """RBI/2024-25/105
DoR.AML.REC.65/14.01.001/2024-25
January 9, 2025
All Regulated Entities
of the Reserve Bank
Madam / Dear Sir,
Amendment to Master Direction (MD) on KYC"""

FED_CIRCULAR = """RBI/2024-25/31
A.P. (DIR Series) Circular No. 06
May 24, 2024
To
All Category - I Authorised Dealer Banks
Madam / Sir,"""


class TestTheHeader:
    def test_the_circular_number(self) -> None:
        assert circular_number(DIRECTION) == "RBI/2025-26/79"
        assert circular_number("RBI/ 2025-26 /79 dated") == "RBI/2025-26/79"
        assert circular_number("no number here") is None

    def test_the_date(self) -> None:
        assert first_date(DIRECTION) == date(2025, 9, 25)
        assert first_date("dated January 9 2025") == date(2025, 1, 9)
        assert first_date("February 30, 2025 then March 1, 2025") == date(2025, 3, 1)

    def test_the_reference_and_its_department(self) -> None:
        assert reference_number(DIRECTION) == "CO.DPSS.POLC.No. S 668/02-14-015/2025-2026"
        assert department(reference_number(DIRECTION)) == "DPSS"
        assert department(reference_number(CIRCULAR)) == "DoR"
        assert reference_number(FED_CIRCULAR) == "A.P. (DIR Series) Circular No. 06"
        assert department(reference_number(FED_CIRCULAR)) == "FED"
        assert department(None) is None

    def test_addressees_sit_between_the_date_and_the_salutation(self) -> None:
        assert addressees(CIRCULAR) == ["All Regulated Entities", "of the Reserve Bank"]
        assert addressees(FED_CIRCULAR) == ["All Category - I Authorised Dealer Banks"]

    def test_a_direction_without_a_salutation_has_no_addressees(self) -> None:
        """The index lines are not addressees."""
        assert addressees(DIRECTION) == []

    @pytest.mark.parametrize(
        ("title", "kind"),
        [
            ("Master Direction – Know Your Customer (KYC) Direction, 2016", "master_direction"),  # noqa: RUF001
            ("Draft Reserve Bank of India (Digital Lending) Directions, 2025", "draft"),
            ("Reserve Bank of India (Authentication ...) Directions, 2025", "directions"),
            ("Master Circular – Customer Service in Banks", "master_circular"),  # noqa: RUF001
            ("Levy of Penal Charges on Loan Accounts", "circular"),
        ],
    )
    def test_the_kind_of_document(self, title: str, kind: str) -> None:
        assert document_kind(title) == kind


class TestTheArchiveIndex:
    def test_cdx_rows_are_parsed_and_junk_lines_skipped(self) -> None:
        text = (
            "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12898&Mode=0"
            " 20250926070158 text/html 200 -5916345683\n"
            "<html>Temporarily Offline</html>\n"
            "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=13350&Mode=0"
            " 20260330230630 text/html 200 17769\n"
        )
        rows = parse_cdx(text)
        assert [r.timestamp for r in rows] == ["20250926070158", "20260330230630"]
        assert rows[0].length == -5916345683  # kept as found; sorted last when choosing

    def test_the_raw_capture_url_has_no_archive_toolbar(self) -> None:
        capture = Capture("https://www.rbi.org.in/a?Id=1&Mode=0", "20250101000000", "text/html", 1)
        assert (
            capture.raw_url
            == "https://web.archive.org/web/20250101000000id_/https://www.rbi.org.in/a?Id=1&Mode=0"
        )

    @pytest.mark.parametrize(
        ("url", "number"),
        [
            ("https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12898&Mode=0", 12898),
            ("https://rbi.org.in/scripts/notificationuser.aspx?id=12898&mode=0", 12898),
            (
                "https://rbi.org.in/scripts/notificationuser.aspx/www.mastercirculars.rbi.org.in"
                "/Scripts/NotificationUser.aspx?Id=12898&Mode=0",
                None,
            ),
            ("https://www.rbi.org.in/scripts/NotificationUser.aspx-", None),
            ("https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12898&Mode=1", None),
            ("https://evil.example/Scripts/NotificationUser.aspx?Id=1&Mode=0", None),
        ],
    )
    def test_only_canonical_notification_urls_count(self, url: str, number: int | None) -> None:
        assert notification_id(url) == number

    def test_master_direction_pages_use_did(self) -> None:
        url = "https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx?did=405"
        assert page_id(url, "BS_ViewMasterDirections.aspx", key="did") == 405


PAGE = b"""<html><head><title>Notifications - Reserve Bank of India</title></head><body>
<table class="tablebg"><tr><td class="tableheader">
<a href="https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT79.PDF">
<img alt="PDF"/></a> (302 kb)</td></tr>
<tr><td class="tableheader">
<b>Reserve Bank of India (Authentication)  Directions, 2025</b></td></tr>
<tr class="tablecontent2"><td><p>RBI/2025-26/79<br/>CO.DPSS.POLC.No. S 668/02-14-015/2025-2026</p>
<p align="right">September 25, 2025</p><p class="head">1. Introduction</p>
<p>All digital payment transactions shall meet two factors of authentication.</p></td></tr>
</table></body></html>"""

BLOCK_PAGE = b"""<html><head><title>Unauthorised Access </title></head><body><center>
You are not authorized to view this page. Please contact concerned Support Team.
</center></body></html>"""


class TestTheNotificationPage:
    def test_title_pdf_and_body_are_read(self) -> None:
        page = parse_notification_page(PAGE)
        assert page.title == "Reserve Bank of India (Authentication) Directions, 2025"
        assert page.pdf_url == "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT79.PDF"
        lines = page.body_text.splitlines()
        assert lines[:3] == [
            "RBI/2025-26/79",
            "CO.DPSS.POLC.No. S 668/02-14-015/2025-2026",
            "September 25, 2025",
        ]
        assert "1. Introduction" in lines  # paragraph numbers stay at line starts
        assert circular_number(page.body_text) == "RBI/2025-26/79"

    def test_a_page_with_only_the_pdf_link_has_an_empty_body(self) -> None:
        empty = (
            PAGE.split(b'<tr class="tablecontent2">')[0]
            + b'<tr class="tablecontent2"><td></td></tr></table>'
        )
        page = parse_notification_page(empty)
        assert page.body_text == "" and page.pdf_url

    def test_a_captured_block_page_is_refused(self) -> None:
        with pytest.raises(NotACircularPage, match="block page"):
            parse_notification_page(BLOCK_PAGE)

    def test_a_captured_captcha_is_refused_with_that_reason(self) -> None:
        captcha = (
            b"<html><body>Please enable JavaScript to view the page content."
            b"<p>This question is for testing whether you are a human visitor and to prevent"
            b" automated spam submission.</p><p>What code is in the image?</p></body></html>"
        )
        with pytest.raises(NotACircularPage, match="CAPTCHA"):
            parse_notification_page(captcha)

    def test_a_page_of_another_kind_is_refused(self) -> None:
        with pytest.raises(NotACircularPage, match="not a notification page"):
            parse_notification_page(b"<html><body><p>Home</p></body></html>")
