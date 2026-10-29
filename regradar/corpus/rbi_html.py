"""Reading an RBI notification page (`Scripts/NotificationUser.aspx?Id=N`).

The page has a header table with the PDF link and the title, then a body
row (`tr.tablecontent2`) with the circular as HTML. From 2026 the body is
often empty and only the PDF carries the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

_BLOCKED_MARKERS = ("Unauthorised Access", "You are not authorized to view this page")
_PARAGRAPH_TAGS = ["p", "li", "tr", "h1", "h2", "h3", "h4", "div"]


class NotACircularPage(ValueError):
    """The bytes are not an RBI notification page (a block page, an error, a redirect)."""


@dataclass(frozen=True)
class NotificationPage:
    title: str
    pdf_url: str | None
    body_text: str  # "" when the page carries only the PDF link


def _text_with_breaks(element: Tag) -> str:
    """Text with a line per paragraph or table row, so numbering stays at line starts."""
    for br in element.find_all("br"):
        br.replace_with("\n")
    for block in element.find_all(_PARAGRAPH_TAGS):
        block.insert_before("\n")
        block.insert_after("\n")
    text = element.get_text(" ")
    lines = (re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def parse_notification_page(html: bytes) -> NotificationPage:
    soup = BeautifulSoup(html, "lxml")
    head = soup.title.get_text(strip=True) if soup.title else ""
    if any(marker in head or marker in soup.get_text()[:2000] for marker in _BLOCKED_MARKERS):
        raise NotACircularPage("the capture is RBI's 'Unauthorised Access' block page")
    table = soup.select_one("table.tablebg")
    if table is None:
        raise NotACircularPage("no table.tablebg: not a notification page")
    title_tag = table.select_one("td.tableheader b")
    title = re.sub(r"\s+", " ", title_tag.get_text(" ")).strip() if title_tag else ""
    if not title:
        raise NotACircularPage("the notification page has no title")
    pdf = None
    for link in table.select("td.tableheader a[href]"):
        href = str(link["href"])
        if href.lower().endswith(".pdf"):
            pdf = href
            break
    body = table.select_one("tr.tablecontent2")
    body_text = _text_with_breaks(body) if body else ""
    return NotificationPage(title=title, pdf_url=pdf, body_text=body_text)
