"""Build the corpus from the Internet Archive's captures of rbi.org.in.

    uv run python -m regradar.corpus.build pages --min-id 12500
    uv run python -m regradar.corpus.build select
    uv run python -m regradar.corpus.build pdfs
    uv run python -m regradar.corpus.build parse

Every step reads and writes under data/ (gitignored, outside iCloud) and can
be rerun: downloads are cached, so a rerun only fetches what is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from regradar.corpus.rbi_html import NotACircularPage, parse_notification_page
from regradar.corpus.wayback import (
    Capture,
    captures_for,
    cdx_query_url,
    notification_id,
    parse_cdx,
)
from regradar.fetch import FetchError, PoliteClient

DATA = Path("data")
CDX_DIR = DATA / "cdx"
CACHE = DATA / "cache" / "http"
WORK = DATA / "corpus"

NOTIFICATION_PAGES = "rbi.org.in/Scripts/NotificationUser.aspx"
NOTIFICATION_PDFS = "rbidocs.rbi.org.in/rdocs/notification/PDFs/"


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_index(
    client: PoliteClient, name: str, prefix: str, since: int, mime: str | None
) -> list[Capture]:
    """The CDX index for `prefix`, saved under data/cdx/ the first time."""
    path = CDX_DIR / name
    if not path.exists():
        reply = client.get(cdx_query_url(prefix, since, mime))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(reply.body)
    return parse_cdx(path.read_text(encoding="utf-8", errors="replace"))


def candidate_captures(
    captures: list[Capture], min_id: int, max_id: int
) -> dict[int, list[Capture]]:
    """Captures of each notification Id in range, the most promising first.

    A block page is ~1 KB compressed and a real page ~15 KB or more; the CDX
    length field is sometimes negative nonsense, which sorts last.
    """
    by_id: dict[int, list[Capture]] = defaultdict(list)
    for capture in captures:
        number = notification_id(capture.original)
        if number is not None and min_id <= number <= max_id and capture.mimetype == "text/html":
            by_id[number].append(capture)
    for found in by_id.values():
        found.sort(key=lambda c: (c.length > 8000, c.length, c.timestamp), reverse=True)
    return dict(sorted(by_id.items()))


def fetch_page(client: PoliteClient, number: int, found: list[Capture]) -> dict[str, Any]:
    """Read the first capture of notification `number` that is a real circular page."""
    tried: list[str] = []
    candidates = list(found)
    extra_listed = False
    while candidates:
        capture = candidates.pop(0)
        try:
            reply = client.get(capture.raw_url)
            page = parse_notification_page(reply.body)
        except (FetchError, NotACircularPage) as error:
            tried.append(f"{capture.timestamp}: {error}")
            if not candidates and not extra_listed:
                # The collapsed index lists one capture per URL; ask for all of them.
                extra_listed = True
                seen = {c.raw_url for c in found}
                candidates = [
                    c for c in captures_for(client, capture.original) if c.raw_url not in seen
                ][:3]
            continue
        body_path = WORK / "html" / f"{number}.txt"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(page.body_text, encoding="utf-8")
        return {
            "id": number,
            "page_url": f"https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id={number}&Mode=0",
            "capture_url": capture.raw_url,
            "capture_timestamp": capture.timestamp,
            "title": page.title,
            "pdf_url": page.pdf_url,
            "body_chars": len(page.body_text),
            "ok": True,
        }
    return {"id": number, "ok": False, "problems": tried}


def cmd_pages(args: argparse.Namespace) -> int:
    with PoliteClient(CACHE, min_interval=args.interval) as client:
        index = load_index(client, "notification_pages.txt", NOTIFICATION_PAGES, 2023, None)
        wanted = candidate_captures(index, args.min_id, args.max_id)
        print(f"{len(wanted)} notification Ids in [{args.min_id}, {args.max_id}] have captures")
        rows = []
        for done, (number, found) in enumerate(wanted.items(), 1):
            rows.append(fetch_page(client, number, found))
            if done % 25 == 0:
                ok = sum(r["ok"] for r in rows)
                print(
                    f"  {done}/{len(wanted)} read, {ok} usable, {client.requests_made} requests",
                    flush=True,
                )
        written = write_jsonl(WORK / "pages.jsonl", rows)
    ok = sum(r["ok"] for r in rows)
    print(f"{written} Ids, {ok} usable pages -> {WORK / 'pages.jsonl'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    pages = steps.add_parser(
        "pages", help="read the notification pages (title, PDF link, HTML body)"
    )
    pages.add_argument("--min-id", type=int, default=12500)
    pages.add_argument("--max-id", type=int, default=13999)
    pages.add_argument("--interval", type=float, default=2.0, help="seconds between requests")
    pages.set_defaults(run=cmd_pages)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
