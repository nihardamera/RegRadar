"""Build the corpus from the Internet Archive's captures of rbi.org.in.

    uv run python -m regradar.corpus.build pages --min-id 12500
    uv run python -m regradar.corpus.build select
    uv run python -m regradar.corpus.build pdfs
    uv run python -m regradar.corpus.build parse
    uv run python -m regradar.corpus.build audit

Every step reads and writes under data/ (gitignored, outside iCloud) and can
be rerun: downloads are cached, so a rerun only fetches what is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from regradar.corpus.audit import render
from regradar.corpus.document import describe, near_duplicates, text_of
from regradar.corpus.pdf import UnreadablePdf, parse_pdf
from regradar.corpus.rbi_html import NotACircularPage, parse_notification_page
from regradar.corpus.select import select
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
# Committed: the record of what is in the corpus and where each file came from.
MANIFEST = Path("corpus") / "manifest.jsonl"

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
        # Merge with earlier runs over other Id ranges; this run's rows win.
        path = WORK / "pages.jsonl"
        merged = {row["id"]: row for row in read_jsonl(path)} if path.exists() else {}
        merged.update({row["id"]: row for row in rows})
        written = write_jsonl(path, (merged[key] for key in sorted(merged)))
    ok = sum(r["ok"] for r in rows)
    print(f"{written} Ids, {ok} usable pages -> {WORK / 'pages.jsonl'}")
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    pages = list(read_jsonl(WORK / "pages.jsonl"))
    chosen = select(pages, args.limit)
    write_jsonl(WORK / "selected.jsonl", chosen)
    usable = sum(1 for p in pages if p.get("ok"))
    print(f"{len(chosen)} of {usable} usable pages selected -> {WORK / 'selected.jsonl'}")
    return 0


def _pdf_key(url: str) -> str:
    """rbidocs paths vary in case (`Notification/PDFs` and `notification/PDFs`)."""
    return url.split("://", 1)[-1].lower()


def fetch_pdf(
    client: PoliteClient, url: str, index: dict[str, Capture]
) -> tuple[bytes | None, str | None, str]:
    """(bytes, capture URL, problem) for the first capture that really is a PDF."""
    candidates = [index[_pdf_key(url)]] if _pdf_key(url) in index else []
    listed = False
    problem = "no capture of the PDF in the archive"
    while True:
        while candidates:
            capture = candidates.pop(0)
            try:
                reply = client.get(capture.raw_url)
            except FetchError as error:
                problem = str(error)
                continue
            if b"%PDF-" in reply.body[:1024]:
                return reply.body, capture.raw_url, ""
            problem = f"capture {capture.timestamp} is not a PDF"
        if listed:
            return None, None, problem
        listed = True
        candidates = [c for c in captures_for(client, url) if c.mimetype == "application/pdf"][:3]


def cmd_pdfs(args: argparse.Namespace) -> int:
    selected = list(read_jsonl(WORK / "selected.jsonl"))
    with PoliteClient(CACHE, min_interval=args.interval) as client:
        index_rows = load_index(
            client, "notification_pdfs_2024on.txt", NOTIFICATION_PDFS, 2024, "application/pdf"
        )
        index = {_pdf_key(c.original): c for c in index_rows}
        rows = []
        for done, page in enumerate(selected, 1):
            body, capture_url, problem = fetch_pdf(client, page["pdf_url"], index)
            row = {"id": page["id"], "pdf_url": page["pdf_url"], "ok": body is not None}
            if body is not None:
                row |= {"pdf_capture_url": capture_url, "sha256": hashlib.sha256(body).hexdigest()}
            else:
                row["problem"] = problem
            rows.append(row)
            if done % 25 == 0:
                ok = sum(r["ok"] for r in rows)
                print(f"  {done}/{len(selected)} PDFs, {ok} read", flush=True)
    write_jsonl(WORK / "pdfs.jsonl", rows)
    print(f"{sum(r['ok'] for r in rows)} of {len(rows)} PDFs read -> {WORK / 'pdfs.jsonl'}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    client = PoliteClient(CACHE)  # reads the cache only; never fetches here
    pdfs = {row["id"]: row for row in read_jsonl(WORK / "pdfs.jsonl")}
    rows: list[dict[str, Any]] = []
    texts: dict[str, str] = {}
    for page in read_jsonl(WORK / "selected.jsonl"):
        html_text = (WORK / "html" / f"{page['id']}.txt").read_text(encoding="utf-8")
        found = pdfs.get(page["id"], {})
        parsed, problem = None, found.get("problem")
        cached = client.cached(found["pdf_capture_url"]) if found.get("ok") else None
        if cached is not None:
            try:
                parsed = parse_pdf(cached.body)
            except UnreadablePdf as error:
                problem = str(error)
        row = describe(page, html_text, parsed, problem)
        if found.get("ok"):
            row |= {"pdf_capture_url": found["pdf_capture_url"], "pdf_sha256": found["sha256"]}
        rows.append(row)
        text = text_of(row, html_text, parsed)
        if text:
            texts[row["doc_id"]] = text
            document = {"doc_id": row["doc_id"], "title": row["title"], "text": text}
            if parsed is not None and row["text_source"] == "pdf":
                document["pages"] = [{"number": p.number, "text": p.text} for p in parsed.pages]
            out = WORK / "docs" / f"{row['doc_id']}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    ok = [row for row in rows if row["status"] == "ok"]
    copies = near_duplicates([(row["doc_id"], texts[row["doc_id"]]) for row in ok])
    for row in rows:
        if row["doc_id"] in copies:
            row["status"] = "near_duplicate"
            row["duplicate_of"] = copies[row["doc_id"]]
    in_corpus = [row for row in rows if row["status"] == "ok"][: args.target]
    keep = {row["doc_id"] for row in in_corpus}
    for row in rows:
        row["in_corpus"] = row["doc_id"] in keep
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(MANIFEST, rows)
    counts = Counter(row["status"] for row in rows)
    print(f"{len(rows)} documents: {dict(counts)}; {len(in_corpus)} in the corpus -> {MANIFEST}")
    return 0


def cmd_audit(_args: argparse.Namespace) -> int:
    rows = list(read_jsonl(MANIFEST))
    out = MANIFEST.parent / "AUDIT.md"
    out.write_text(render(rows), encoding="utf-8")
    print(f"audit of {len(rows)} documents -> {out}")
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
    chooser = steps.add_parser("select", help="choose the circulars FlexiPay would need")
    chooser.add_argument("--limit", type=int, default=380, help="more than the target, for losses")
    chooser.set_defaults(run=cmd_select)
    pdf_step = steps.add_parser("pdfs", help="fetch the selected circulars' PDFs")
    pdf_step.add_argument("--interval", type=float, default=2.0)
    pdf_step.set_defaults(run=cmd_pdfs)
    parse_step = steps.add_parser("parse", help="parse, check and write the manifest")
    parse_step.add_argument("--target", type=int, default=300)
    parse_step.set_defaults(run=cmd_parse)
    audit = steps.add_parser("audit", help="write corpus/AUDIT.md from the manifest")
    audit.set_defaults(run=cmd_audit)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
