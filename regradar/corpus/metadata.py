"""Reading a circular's header: its number, reference, date, department and addressees.

RBI circulars open the same way, in the PDF and on the web page:

    RBI/2025-26/79
    CO.DPSS.POLC.No. S 668/02-14-015/2025-2026
    September 25, 2025
    All Payment System Providers and Participants
    Madam / Dear Sir,

Directions often have no addressees or salutation, and FED circulars put
"A.P. (DIR Series) Circular No. 12" in place of a department reference.
"""

from __future__ import annotations

import re
from datetime import date, datetime

# `RBI/2025-26/79`, and since 2024 often `RBI/DPSS/2024-25/123`.
_CIRCULAR_NO = re.compile(r"\bRBI/\s?(?:([A-Z]{2,6})\s?/\s?)?(\d{4})\s?-\s?(\d{2,4})\s?/\s?(\d+)\b")
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b")
_FISCAL_YEAR = re.compile(r"\d{4}\s?-\s?\d{2,4}\s*$")
_SALUTATION = re.compile(r"^(Madam|Dear\s+Sir|Sir\s*/\s*Madam|Dear\s+Madam)", re.IGNORECASE)
_ADDRESSEE_START = re.compile(r"^(All\b|The\s+(Chairman|Chairperson|Chief|Managing|Principal))")

# Department codes as they appear in reference numbers, normalised.
DEPARTMENTS = {
    "CEPD": "CEPD",  # Consumer Education and Protection
    "DBR": "DBR",  # Banking Regulation (before 2019)
    "DCBR": "DCBR",  # Co-operative Bank Regulation (before 2019)
    "DCM": "DCM",  # Currency Management
    "DEPR": "DEPR",
    "DGBA": "DGBA",  # Government and Bank Accounts
    "DNBR": "DNBR",  # Non-Banking Regulation (before 2019)
    "DNBS": "DNBS",  # Non-Banking Supervision
    "DOR": "DoR",  # Regulation
    "DOS": "DoS",  # Supervision
    "DPSS": "DPSS",  # Payment and Settlement Systems
    "FED": "FED",  # Foreign Exchange
    "FIDD": "FIDD",  # Financial Inclusion and Development
    "FMRD": "FMRD",  # Financial Markets Regulation
    "IDMD": "IDMD",  # Internal Debt Management
}


def circular_number(text: str) -> str | None:
    """`RBI/2025-26/79` or `RBI/DPSS/2024-25/123`, without spaces, or None."""
    match = _CIRCULAR_NO.search(text)
    if not match:
        return None
    dept, start, end, serial = match.groups()
    return f"RBI/{dept + '/' if dept else ''}{start}-{end}/{serial}"


def first_date(text: str) -> date | None:
    """The first full date written as `Month D, YYYY`, or None."""
    for match in _DATE.finditer(text):
        month, day, year = match.groups()
        try:
            return datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()
        except ValueError:
            continue
    return None


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def reference_number(text: str) -> str | None:
    """The department reference on the line after the circular number.

    It ends in a financial year (`.../2025-26`) or names a FED circular
    (`A.P. (DIR Series) Circular No. 12`). In PDFs the date is often on the
    same line, right-aligned, so a date is cut off first.
    """
    lines = _lines(text)
    for i, line in enumerate(lines[:20]):
        if not _CIRCULAR_NO.search(line):
            continue
        rest = _CIRCULAR_NO.sub("", line).strip()
        for candidate in [rest, *lines[i + 1 : i + 3]]:
            candidate = _DATE.sub("", candidate).strip(" ,")
            if _FISCAL_YEAR.search(candidate) or "DIR Series" in candidate:
                return candidate
    return None


def department(reference: str | None) -> str | None:
    """The issuing department, from the codes in a reference or circular number."""
    if not reference:
        return None
    if "DIR Series" in reference:
        return "FED"
    for token in re.split(r"[.\s/()-]+", reference.upper()):
        if token in DEPARTMENTS:
            return DEPARTMENTS[token]
    return None


def addressees(text: str) -> list[str]:
    """The lines between the date and the salutation that name who it is for.

    Empty when the document has no salutation (most Directions), since the
    lines before an index or a first paragraph are not addressees.
    """
    lines = _lines(text)[:40]
    salutation = next((i for i, line in enumerate(lines) if _SALUTATION.match(line)), None)
    if salutation is None:
        return []
    dated = next((i for i, line in enumerate(lines[:salutation]) if _DATE.search(line)), -1)
    block = lines[dated + 1 : salutation]
    start = next((i for i, line in enumerate(block) if _ADDRESSEE_START.match(line)), None)
    return block[start:] if start is not None else []


def document_kind(title: str) -> str:
    """master_direction, directions, master_circular, draft or circular."""
    lowered = title.lower()
    if "draft" in lowered:
        return "draft"
    if "master direction" in lowered:
        return "master_direction"
    if "master circular" in lowered:
        return "master_circular"
    if re.search(r"\bdirections?\b", lowered):
        return "directions"
    return "circular"
