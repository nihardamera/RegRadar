# Work log

The plan is `03_REGRADAR.md` in `~/Desktop/portfolio/roadmap/`. A new chat
resumes from here: read the plan, then the latest entry below.

## 2026-10-30 (Fri): M0 baseline

**Done**
- Full-history gitleaks scan of FinScoutAI (11 commits): no leaks.
- Baseline at `06fa2a0` in a throwaway venv from `requirements.txt`:
  30 tests passed.
- Tagged `06fa2a0` as `finscout-v1` and pushed the tag. Renamed the GitHub
  repo FinScoutAI → RegRadar (the old URL redirects, 301). The local folder is
  now `repos/RegRadar`. All v2 work happens on branch `v2`; main keeps showing
  v1 until M6.
- uv + `pyproject.toml`. v1's pins are now the `v1` extra; `uv lock` resolved
  them together (198 packages). Dev tools: pytest 9.2.0, ruff 0.17.3,
  mypy 2.4.1 (strict, on `regradar/` only), pre-commit 4.7.0. ruff skips the
  v1 files so they stay as tagged until they are ported in M4. The only edit
  to v1 is a final newline the end-of-file hook added to three files.
- pre-commit (ruff, gitleaks v8.30.1, hygiene hooks) and GitHub Actions
  (checks + a gitleaks scan of the full history).
- README: a "being rebuilt" note and "History: started as FinScoutAI".

**Gotchas**
- Like Commit-Suggestor: the venv and data live in `.venv.nosync` /
  `data.nosync` behind symlinks, because iCloud syncs ~/Desktop.
- No global git identity is set on this Mac, so it is set per repo.
- `astral-sh/setup-uv` publishes no floating major tag: `@v10` fails to
  resolve, so CI pins `@v10.3.3`. Commit-Suggestor's `ci.yml` has the same
  `@v10` pin and will fail the same way when its branch is pushed.
- CI is green on `v2` (both jobs; 30 passed).
- Docker and Ollama are not installed. v1 cannot run end to end without
  Ollama, but no milestone needs it to: M4 compares against the committed
  `examples/sample_report.md`.

**Next**
1. Nihar: install OrbStack (or Docker Desktop) before M2, for Qdrant.
2. M1: check rbi.org.in's robots.txt and terms, then the polite, cached
   fetcher for ~300 circulars with metadata, a parse audit (text dropped,
   scanned PDFs), and ~20 synthetic policy documents. M1 gate after that.

## 2026-10-30 (Fri), later: M1 corpus and parsing (in progress)

**Decisions**
- **Source: the Internet Archive, not rbi.org.in.** RBI's servers answer any
  non-browser client with HTTP 418 ("Unauthorised Access"); rbidocs serves
  a JavaScript challenge; `website.rbi.org.in` redirects to www. Getting
  past that means posing as a browser (v1 did, with Playwright), which is
  evading a block, so it is not done. web.archive.org has no robots.txt
  and serves the same public documents without load on RBI. The client
  names itself (`RegRadar/0.1 (...)`), waits ≥ 2 s between requests, backs
  off on 429/5xx/"temporarily offline", and caches everything. Every record
  keeps the RBI URL and the capture URL. Nihar asked about an agent
  browser; answered no for the bulk corpus, for the same reason.
- **The PDF is the text of record**; the notification page's HTML (when it
  has the circular, which 2026 pages mostly do not) is a second check.
- **Selection** (`regradar/corpus/select.py`): titles about FlexiPay's
  business, minus other entity types and markets. RBI's November 2025
  consolidation reissued nearly identical Directions per entity type
  ("Commercial Banks – KYC", "NBFCs – KYC", ...); only NBFC, payment-system
  and all-entity versions are kept, and near-copies are dropped by 5-word
  shingle Jaccard ≥ 0.8. Otherwise "which chunk answers this" is ambiguous.
- **Two sources**: notification pages (Ids 11500–13999, 2019–2026) and the
  Master Direction listing (243 consolidated MDs; 28 relevant, all kept).
- **Parsed text is committed** (`corpus/docs/*.json`); PDFs are not (SHA-256
  in the manifest). Rebuilding takes ~1,500 slow archive requests.

**Findings (each now a test)**
- PyMuPDF "repairs" an archived challenge page into an empty PDF → bytes
  without `%PDF-` are refused.
- The archive's crawler often kept RBI's CAPTCHA as the page. In Ids
  12000–12499, 142 of 485 have *only* CAPTCHA captures: a coverage hole
  that is not random. 24 of 831 in 12500–13999.
- Real headers: `RBI/DPSS/2024-25/123` (department in the number), and the
  date right-aligned on the reference line in PDFs.
- Table extraction read merged cells twice, sometimes stepping across
  columns. The first fix also deleted near-identical rows in a list of
  repealed circulars; the pypdf recall check caught it (page recall 0.70).
  Narrowed rule; and the pypdf check now runs both ways (recall = dropped
  text, precision = repeated text).
- Some Master Directions are one bordered box of prose; rendered as lines,
  not a one-column table.
- The Hindi letterhead and address footers extract with wrong glyphs (not
  private-use characters, so the garbled check does not see them).
  Boilerplate only; to strip before chunking in M2.

**Synthetic company**: 21 documents in `company/` (FlexiPay: PA-O, PPI
issuer, UPI TPAP, LSP; FlexiCredit: Base Layer NBFC-ICC). `GAP_KEY.md`:
10 gaps verified against the circular's text, 2 deliberate non-gaps (a rule
that does not apply to a Base Layer NBFC; a settlement rule the 2025 PA MD
replaced), 5 still to verify. Checking against the text changed the
profile: authorisation moved to March 2023, and FlexiCredit's assets set to
₹560 crore so the ₹500 crore threshold of the NBFC fraud Directions applies.
