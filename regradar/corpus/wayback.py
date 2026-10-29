"""Finding and reading Internet Archive captures of rbi.org.in."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from regradar.fetch import PoliteClient

CDX_URL = "https://web.archive.org/cdx/search/cdx"


@dataclass(frozen=True)
class Capture:
    original: str
    timestamp: str
    mimetype: str
    length: int  # compressed size in the archive; the CDX index sometimes has nonsense here

    @property
    def raw_url(self) -> str:
        """The capture's original bytes, without the archive's toolbar or rewritten links."""
        return f"https://web.archive.org/web/{self.timestamp}id_/{self.original}"


def parse_cdx(text: str) -> list[Capture]:
    """Parse CDX lines of `original timestamp mimetype statuscode length`."""
    captures = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 5 or not fields[1].isdigit():
            continue
        original, timestamp, mimetype, _status, length = fields
        size = int(length) if length.lstrip("-").isdigit() else 0
        captures.append(Capture(original, timestamp, mimetype, size))
    return captures


def cdx_query_url(url_prefix: str, since_year: int, mimetype: str | None = None) -> str:
    params = [
        f"url={quote(url_prefix, safe='/:')}",
        "matchType=prefix",
        "fl=original,timestamp,mimetype,statuscode,length",
        "filter=statuscode:200",
        "collapse=urlkey",
        f"from={since_year}",
    ]
    if mimetype:
        params.append(f"filter=mimetype:{mimetype}")
    return f"{CDX_URL}?{'&'.join(params)}"


def list_captures(
    client: PoliteClient, url_prefix: str, since_year: int, mimetype: str | None = None
) -> list[Capture]:
    """Every distinct URL under `url_prefix` captured with status 200 since `since_year`.

    `collapse=urlkey` keeps one row per URL; `captures_for` lists them all.
    """
    reply = client.get(cdx_query_url(url_prefix, since_year, mimetype))
    return parse_cdx(reply.body.decode("utf-8", errors="replace"))


def captures_for(client: PoliteClient, url: str) -> list[Capture]:
    """All status-200 captures of one exact URL, newest first."""
    query = (
        f"{CDX_URL}?url={quote(url, safe='/:?=&')}"
        "&fl=original,timestamp,mimetype,statuscode,length&filter=statuscode:200"
    )
    reply = client.get(query)
    found = parse_cdx(reply.body.decode("utf-8", errors="replace"))
    return sorted(found, key=lambda c: c.timestamp, reverse=True)


RBI_HOSTS = frozenset({"rbi.org.in", "www.rbi.org.in"})
_QUERY = re.compile(r"Id=(\d+)&Mode=0", re.IGNORECASE)


def page_id(url: str, page: str, key: str = "Id") -> int | None:
    """The numeric `key` of an RBI page URL such as `/Scripts/{page}?Id=N&Mode=0`.

    The archive's index also holds junk URLs (other paths glued onto the page
    name, stray punctuation), so the host and path must match exactly.
    """
    parts = urlsplit(url)
    if parts.hostname not in RBI_HOSTS or parts.path.lower() != f"/scripts/{page.lower()}":
        return None
    match = re.fullmatch(rf"{key}=(\d+)(&Mode=0)?", parts.query, re.IGNORECASE)
    return int(match.group(1)) if match else None


def notification_id(url: str) -> int | None:
    """The `Id` of a notification page (`NotificationUser.aspx?Id=N&Mode=0`)."""
    if not _QUERY.fullmatch(urlsplit(url).query):
        return None
    return page_id(url, "NotificationUser.aspx")
