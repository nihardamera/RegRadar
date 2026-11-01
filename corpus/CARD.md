# RBI corpus: data card

**What it is.** 290 public Reserve Bank of India documents: 262 notifications
(circulars, directions and master directions, 2019–2026) and 28 of the
Master Directions issued in the November 2025 consolidation. They are the
documents a compliance team at a payment aggregator, PPI issuer and UPI app
with an NBFC lending arm (the synthetic FlexiPay group in
[`../company/`](../company/README.md)) would need to read.

**Source and acknowledgement.** The content is the Reserve Bank of India's,
from [rbi.org.in](https://www.rbi.org.in). RBI permits reproduction with
acknowledgement of the source. Each document's RBI page URL is in
[`manifest.jsonl`](manifest.jsonl).

## How it was gathered

RBI's servers refuse automated clients: `www.rbi.org.in` answers HTTP 418
("Unauthorised Access") and `rbidocs.rbi.org.in` serves a JavaScript
challenge. Rather than pose as a browser, the corpus was read from the
Internet Archive's captures of those pages (web.archive.org has no
robots.txt restrictions). The client names itself in its User-Agent, waits at
least 2 seconds between requests, backs off on overload and caches every
response, so nothing was downloaded twice: 2,688 distinct archive responses
cached, fetched over several hours on 30 Oct 2026.

| Step | Count |
| --- | --- |
| Notification Ids 11500–13999 with an archived capture since 2023 | 1,649 |
| ... of which a real notification page | 1,483 |
| Master Directions listed on the consolidated listing page | 243 |
| Selected as relevant (rule below) | 295 |
| In the corpus (after near-copies and unreadable documents) | **290** |

Each manifest row keeps the RBI URL, the archive capture URL, the PDF's
SHA-256, and the parse checks. The parsed text of every document in the
corpus is committed in [`docs/`](docs/), page by page, so chunk IDs and the
golden set do not depend on refetching. The PDFs are not committed.

## Selection

[`regradar/corpus/select.py`](../regradar/corpus/select.py): a title is kept
when it names FlexiPay's business (payments, PPIs, payment aggregators, UPI,
cards, KYC/AML, digital lending, NBFCs, credit information, loan charges,
recovery, fraud, cyber and IT, outsourcing, customer service, grievances)
and not another kind of entity (commercial, small finance, co-operative or
regional rural banks, AIFIs, ARCs, HFCs) or market (forex, government
securities, currency, priority sector, capital).

The November 2025 consolidation reissued nearly the same Directions for each
kind of entity. Only the NBFC, payment-system and all-entity versions are
kept, and documents sharing ≥ 80% of their 5-word shingles are near-copies
(4 dropped). Without that, two chunks would answer each question equally
well and the golden set's "correct chunk" would be ambiguous.

## What is in it

- **Kinds**: 186 circulars, 70 directions, 33 master directions, 1 draft
  (a draft is not law; it is labelled `kind: draft`).
- **Dates**: 2019 to 2026 (one Master Direction dated 2016, updated 2021);
  by year 26, 37, 36, 27, 34, 31, 59, 39 for 2019–2026.
- **Size**: 2,945 PDF pages, 841 tables (as Markdown), 5.5 million characters.
- **Text from**: the PDF for 275 documents; the web page's HTML for 15 whose
  PDF the archive does not hold.
- **Metadata found**: date 290/290, circular number 279/290, department
  278/290, addressees 204/290 (Directions usually have none). See
  [`AUDIT.md`](AUDIT.md).

## Superseded and repealed documents

The corpus holds rules and the rules that replaced them, on purpose: the
2020 payment aggregator guidelines and the 2025 Master Direction; the 2016
KYC Master Direction and the 2025 NBFC KYC Directions. Many 2019–2024
circulars were repealed by the 2025 consolidation. The manifest gives each
document's date so retrieval can filter by it; it does not yet record
"repealed by". A question about current law has to prefer the newer text.

## Known gaps and biases

- **Not random**: in Ids 12000–12499 (2021–2023), 142 of 485 pages exist in
  the archive *only* as RBI's CAPTCHA page, which the archive's own crawler
  was served. Those circulars are missing whatever their subject (24 of 831
  in 12500–13999; none in 11500–11999).
- 16 selected PDFs could not be read from the archive: 14 were never
  captured (mostly 2026 notifications) and 2 exist only as challenge pages.
  15 of them are read from the web page's HTML instead; the one with neither
  (the 2025 re-issue of the Integrated Ombudsman Scheme) is left out. The
  2021 scheme itself is in the corpus.
- Only Ids with a capture since 2023 were considered.
- Selection is by title; a relevant circular with an unhelpful title is
  missed. The rule was checked by reading the titles it rejected.
- One regulator (RBI). SEBI and IRDAI are not included.

## Parse quality

Three independent checks, in [`AUDIT.md`](AUDIT.md):

1. Every page is compared with pypdf's reading of the same text layer: 8
   pages in 6 documents keep under 95% of pypdf's distinct words (dropped
   text); 43 pages in 30 documents repeat over 5% of their words (mostly a
   stamp box or a table cell read twice).
2. 237 documents also have the circular as HTML: the median share of the
   HTML's words found in the PDF text is 1.000 (5th percentile 0.991,
   minimum 0.853).
3. No scanned pages (no page with under 40 characters of text and an image
   over half of it).

The Hindi letterhead and footer on every circular extract with wrong glyphs;
they are boilerplate and are stripped before chunking.

## Rebuilding

```bash
uv run python -m regradar.corpus.build pages --min-id 11500 --max-id 13999
uv run python -m regradar.corpus.build masters
uv run python -m regradar.corpus.build select
uv run python -m regradar.corpus.build pdfs
uv run python -m regradar.corpus.build parse
uv run python -m regradar.corpus.build audit
```

A rebuild from an empty cache makes roughly 2,700 archive requests, plus
retries (several hours: the archive takes seconds to answer each one). The archive's holdings change, so a later rebuild may
select a slightly different set; the SHA-256 in the manifest identifies the
exact PDFs used here.
