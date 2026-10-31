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

## 2026-10-30 (Fri), night: M1 corpus built (gate pending)

**Done**
- Corpus: **290 documents** (262 notifications, 28 consolidated Master
  Directions), 2,945 pages, 841 tables, 5.5M characters; text from PDF for
  275, HTML for 15. Committed: `corpus/manifest.jsonl`, `corpus/docs/`,
  `corpus/AUDIT.md`, `corpus/CARD.md`. 290 is short of "~300": only ~13% of
  2023-26 titles are relevant once per-entity copies are dropped, and 142
  notifications from 2021-23 exist only as CAPTCHA captures. Ids were
  extended back to 11500 (2019), which also brings in the 2020 PA
  guidelines that the 2025 MD replaced.
- More parser findings, each a test: two columns with the same paragraph
  were both blanked (cells now judged one at a time); a table drawn over a
  whole page returned only some of its text (blocks are now dropped only
  when the table holds their words); some PDFs hold a page's text twice in
  overlapping layers, so recall now counts distinct words (word pairs were
  tried and rejected: the readers order tables differently); pypdf splits
  words, so fragments are matched against our text with spaces removed.
  Dropped-text flags: 27 documents → 6, all listed in the audit.
- Gap key: 12 verified gaps, 3 deliberate non-gaps (not applicable,
  superseded, permissive "may"), 2 dropped. v1's sample report, on the
  same authentication Directions, states a FlexiPay control ("additional
  verification steps for transactions exceeding ₹50,000 per month") that
  is in none of v1's knowledge-base files: an unsupported claim to show in
  the M4 v1-vs-v2 comparison.
- gitleaks caught a click-tracking `auth=` token RBI pasted into a public
  circular; allowed by fingerprint in `.gitleaksignore` with the reason.

**Next**
1. M1 explain-back gate (Nihar): tables and scanned pages; how we know
   parsing did not silently drop text.
2. Nihar: install OrbStack before M2; pick the dense embedding model with
   me (fastembed candidates, checked against current docs).
3. M2: strip the Hindi letterhead/footer, then fixed / recursive /
   section-aware chunking with stable chunk IDs; Qdrant hybrid + rerank.

**M1 gate (Nihar, unaided): passed.** Corrections given: comparing
PyMuPDF raw text with our output tests post-processing, not extraction
(independence needs another engine, or RBI's HTML); text-layer checks all
agree on a wrong text layer (the Hindi glyphs), so a real-word ratio
belongs with the drop checks; table cell counts match even when a merged
cell is copied; row sentences must be templated, not generated. Nihar's
ideas not yet built, folded into the start of M2: a per-page check that
every number and date pypdf finds is in our text; paragraph-numbering and
annex-reference anchors; a per-page ledger in the manifest.

**Environment (30 Oct, evening)**: OrbStack 2.2.5 installed for M2's Qdrant
(official arm64 DMG; signature checked: Developer ID "Orbital Labs, LLC"
HUAQ24HBR6, notarized). Docker 29.8.2, Compose v5.5.0; `docker` is on PATH
via `~/.zprofile`. Homebrew is not installed on this Mac.

## 2026-10-30 (Fri), late: M2 started; dense model chosen

**Dense model (Nihar's choice, 30 Oct):** `ibm-granite/granite-embedding-small-english-r2`
(Apache-2.0, 384-d, 8k tokens) as the primary; `BAAI/bge-small-en-v1.5`
(MIT, 384-d, 512 tokens) as a second dense row in the M3 ablation. Chosen
on what can be measured before the golden set exists (`eval/embedding_speed.json`,
`scripts/bench_embeddings.py`; Apple M4, 220-word passages, batch 8):

| Model | passages/s | corpus | query p50 | peak RSS | tokens cut |
| --- | --- | --- | --- | --- | --- |
| granite-small-r2 | 19.6 | 3.3 min | 3.0 ms | 3.7 GB | 0% |
| bge-small-en-v1.5 | 17.4 | 3.8 min | 3.3 ms | 0.6 GB | 4.1% (2.5% of chunks, mostly tables) |
| nomic-embed-v1.5 | 5.1 | 12.7 min | 10.2 ms | 7.0 GB | 0% |
| arctic-embed-m-long | 9.0 | 7.2 min | 8.1 ms | 2.0 GB | 4.1% (fastembed caps it at 512) |

Quality is not compared here; it is measured in M3. At batch 32, granite
peaked at 7.2 GB and nomic was killed for memory on this 16 GB Mac.

**Versions**: fastembed 0.9.0 (granite needs 0.9; qdrant-client's
fastembed extra, which wants <0.9, is not used: vectors are computed here),
qdrant-client 1.19.1, Qdrant server v1.19.2 in `docker-compose.yml`
(localhost only, telemetry off).

## 2026-10-30 (Fri), night: M2 retrieval built

**Done**
- Parse checks from the M1 gate: every number pypdf reads must be in our
  text (found a real drop: two side-by-side worked examples, the second
  blanked as a "copy"; a copy must now repeat the numbers too), and every
  page yields text or is listed (one blank page in the corpus).
- `regradar/chunking.py`: cleaning (letterhead, footers, page numbers,
  indexes, running headers: 5,473 lines) and three strategies with
  character offsets. On the corpus: fixed 4,899 chunks (median 220
  words), recursive 5,518 (189), section 4,657 (186, short sections packed
  within a chapter or annex). Numbering anchors: found in 286 of 290
  documents; 24 have forward gaps (table-row paragraphs, a PDF with its
  numbers in a separate column, amendments quoting other paragraphs).
  `eval/chunk_stats.json`.
- **Gold answers will be character ranges**, not chunk IDs, so one golden
  set scores every chunking strategy (a chunk is relevant when it overlaps
  the answer's range).
- `regradar/index.py`: Qdrant v1.19.2, one collection per strategy, granite
  + bge dense and BM25 sparse (IDF in Qdrant), hybrid by RRF in Qdrant,
  cross-encoder rerank of the top 50, filters on regulator, date range,
  circular number, kind and document. All three collections built
  (12-26 min each, dense vectors cached in `data.nosync/vectors`).
- Sanity check on real queries (not an evaluation): the right document and
  paragraph for the cyber-incident, penal-charges, DLG-cap and net-worth
  questions. **"RBI/2025-26/79"**: granite returned paragraph 79 of another
  Direction; BM25 found the circular first; hybrid second. Reranking with
  MiniLM-L12 over 50 candidates costs about 3 s a query on CPU.
- `eval/retrieval_latency.json` (Apple M4, 8 queries x 3, k = 10): BM25
  2.1 ms, dense 8-9 ms, hybrid 8.8 ms p50 (one Qdrant call for both arms
  and the fusion). Reranking the top 50 on CPU: MiniLM-L6 1.6 s,
  MiniLM-L12 5.1 s, bge-reranker-base 7.1 s p50. Reranking costs 180-800x
  retrieval and scales with the candidate count, so M3 measures what it
  buys at 20 and 50 candidates.

**Next**
1. M2 explain-back gate (Nihar).
2. M3: the question-writing tool (gold answers as character ranges), so
   Nihar can write the 150 questions; then the ablation (3 chunkings x
   granite / bge / BM25 / hybrid x rerank off / top 20 / top 50) with CIs.
   Query rewriting / HyDE / decomposition stay off until the eval exists.

**M2 gate (Nihar, unaided; 31 Oct): passed.** Checked against the index:
for "RBI/2025-26/79" the right chunk is BM25 rank 1 and *outside* dense's
top 50; the wrong one (md353 para 79) is dense 1 and BM25 3, so it wins
the fusion. Qdrant's RRF uses k = 2 by default (zero-based ranks; settable
since 1.16), not the paper's 60, and neither k rescues this query (0.75 vs
0.50 at k = 2). Per-prefetch RRF weights exist since 1.17. Corrections:
BM25's IDF already discounts corpus-wide words, so its real failure is
vocabulary mismatch; the MS MARCO rerankers are trained on web queries, so
domain shift could make reranking hurt; hit-at-a-threshold misses answers
split across chunks, so M3 reports span recall (share of the gold range
covered by the top k together) and tokens retrieved per query.
Ideas to test in M3, behind flags: an identifier route (a query matching
RBI/YYYY-YY/N applies the circular_number filter) and BM25-weighted RRF.
The golden set needs identifier-lookup questions for that.

## 2026-10-31 (Sat): M3 golden-set tool ready

**Done**
- `regradar/golden.py` (`sample`, `find`, `add`, `check`) and
  `eval/golden/CARD.md`. Gold answers are **parts** (all needed), each with
  **alternative spans** (any one will do), because the same rule is often
  restated: the penal-charges sentence is in the 2023 circular, the 2025
  NBFC Directions, the HFC Master Direction and the Scale Based Regulation
  MD. `add` finds the same words in other documents (exact text, not the
  retriever) and asks whether each counts. A quote that occurs several
  times in one document is listed with page and section to choose from
  (the penal-charges circular repeats it six times, once per kind of lender).
- `find` is keyword search, not RegRadar's retriever, so the set does not
  lean toward what the system finds. Split fixed by a hash of the ID (about
  a third dev). A test fails if any committed quote stops matching its range.
- Targets: 50 single-hop, 25 multi-hop, 30 number/date, 15 identifier
  (from the M2 gate), 30 unanswerable.

**Next**
1. Nihar: write the 150 questions (`uv run python -m regradar.golden add`;
   about 3-5 minutes each, so 8-12 hours in sittings). Read the card's
   writing guidance first. Commit as you go; `check` shows progress.
2. Me, meanwhile: the evaluation runner (span recall, hit@k, MRR, nDCG@10
   with bootstrap CIs; tokens retrieved per query), tested on a handful of
   throwaway questions that never enter the golden set.
- `regradar/evaluate.py`: hit@k, span recall@k (the union of the top k
  chunks, so an answer split across two chunks counts), MRR, part-based
  nDCG@10 (a second chunk of an already-found part earns nothing, so finer
  chunking cannot inflate it), words@k; 95% percentile-bootstrap CIs over
  questions (10,000 resamples, fixed seed) and paired-difference CIs.
  Retrieval is cached by question text and configuration
  (`data.nosync/eval_cache`), for reruns and the CI gate. The ablation is
  3 chunkings x {granite, bge, BM25, hybrid} + hybrid reranked at 20 and 50.
- Smoke-tested end to end on 6 practice questions written in the scratchpad
  (never in the golden set; results deleted). With n = 5 the intervals span
  40-100 points, which is why the real comparison waits for 150.

## 2026-10-31 (Sat), later: golden set v1 drafted

**Decision (Nihar, 31 Oct):** Claude Code drafts the golden set instead of
Nihar writing it. Conditions agreed in the chat: every record says it was
drafted by Claude Code; Nihar reviews (`uv run python -m regradar.golden
review`, about a minute a question; even 30 is worth it) and the review is
recorded per question; the 100 judge-calibration labels stay Nihar's, since
calibrating a judge against Claude's own labels would measure nothing; the
resume line changes from "hand-built".

**Done**: 150 questions from a stratified random sample of documents
(`eval/golden/CARD.md` has the method). Lessons that changed the tooling:
- Exact-text restatements of short phrases matched unrelated rules (a fraud
  reporting deadline for an ombudsman question), so they are added
  automatically only for quotes of 12+ words.
- The 2025-26 consolidated Directions restate older rules in new words, which
  exact matching misses; a word-overlap scan found 80 candidates and 44 were
  accepted by hand (rejected: other entity types, named instruments, same
  words in a different rule).
- The E-mandate Framework, 2026 consolidates and repeals the earlier
  e-mandate circulars; present-tense questions take it as the current law.
- Strike-through amendments extract as both old and new words ("REs shall
  may, at its option, provide the option a choice"): a parser limitation,
  and q141 keeps it as a hard case.
- Cleaner fix for `Tel.No.` footers deferred: it moves offsets, so it goes with
  the next planned re-index.
