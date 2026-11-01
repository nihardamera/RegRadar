# RegRadar

Cited answers and impact reports over 290 Reserve Bank of India circulars and
Master Directions, measured at every step. Every claim cites the circular text it
rests on, and code checks every citation before anything is shown. For a new
circular, RegRadar lists the obligations, matches them against a company's
policies with citations, and builds an action plan.

Every number below comes from a committed evaluation file, with a 95% interval.

## Results

**Retrieval** (70 held-out questions; `eval/results/ABLATION.md`)

| Configuration | recall@10 (hit@10) | MRR | nDCG@10 |
| --- | --- | --- | --- |
| dense only (granite-small-r2) | 87.1 [78.6, 94.3] | 60.6 [51.3, 69.7] | 67.2 [59.3, 74.9] |
| BM25 only | 84.3 [75.7, 92.9] | 64.0 [54.6, 73.1] | 69.6 [61.3, 77.7] |
| **hybrid (BM25 + dense, RRF)**, the default | **92.9 [85.7, 98.6]** | **68.3 [60.1, 75.9]** | **74.6 [67.7, 81.2]** |
| hybrid + cross-encoder rerank (top 20) | 91.4 [84.3, 97.1] | 68.9 [60.7, 76.8] | 74.9 [68.4, 81.2] |

Hybrid beats dense-only by **+5.7 points recall@10 [+1.4, +11.4]** on the same
questions. Its MRR gain is clear on dev (+14.0 [+7.6, +20.9]) but not on test
(+7.7 [−0.7, +16.2]). The reranker did not help on test and costs 1.6–5 s a query
on CPU against 9 ms for hybrid, so it is off by default.

**Answers** (Haiku 5.5, 90 held-out questions; `eval/results/answers_test_*.json`)

| Measure | Result |
| --- | --- |
| Answerable questions answered | 91.4% [84.3, 97.1] |
| Withheld because the citations did not hold (after one retry) | 4.3% [0.0, 10.0] |
| Citation precision / recall | 70.4% [62.4, 78.1] / 84.3% [75.7, 92.1] |
| Out-of-corpus questions correctly declined | 95.0% [85.0, 100.0] |

**LLM judge, calibrated against human labels** (`eval/judge/SUMMARY.md`): on 30
held-out labels, Cohen's κ = 0.76 [0.32, 1.00] for correctness (93% agreement).
Every held-out answer was labelled faithful, so κ for faithfulness is not defined;
instead the judge was scored on 18 planted errors and caught 15 (83% [67, 100]).

**Impact reports against planted gaps** (Haiku 5.5, 12 circulars, $0.65;
`eval/results/IMPACT.md`)

| Measure | Result |
| --- | --- |
| Planted policy gaps found (the flag states the rule's key fact) | 11/12 = 92% [65, 99] |
| Traps flagged as gaps (not applicable, superseded, "may" rules; lower is better) | 2/3 |
| Reports failing a code check | 0 of 12 |

The pipeline flags 29% of applicable obligations, most of them outside the key,
and precision is not measured: read the recall with that in mind.

**DSPy prompt optimisation** (cited-answer step, 90 held-out questions;
`eval/results/DSPY.md`): neither optimiser beat the hand-written prompt by more
than the noise. MIPROv2 +3.7 points [−2.5, +9.8]; GEPA −3.7 [−10.1, +2.6], after
fitting its 28 validation questions (its rewritten prompt quotes their misses).
Optimising and scoring cost $1.43.

## What the evaluation caught

Measuring each step changed the system more than any idea did:

- **Qdrant's server-side fusion was not repeatable**: 9 of 40 queries changed their
  top 5 on an immediate repeat. Fusion moved into code (same formula, ties broken
  by ID); the hybrid MRR gain on test fell from +10.5, which excluded zero, to +7.7,
  which does not. The README reports the second number.
- **The citation check rejected good answers** for repeating numbers from the
  question and for mangling long circular numbers; fixed, and recorded as seen on
  test (`WORKLOG.md`).
- **The judge's verdicts contradicted its own reasons** ("claim 2 is not supported",
  then faithful = true). Fixed by asking for a verdict per claim and deciding
  faithfulness in code.
- **Human labels alone could not calibrate faithfulness**: citation enforcement
  leaves almost no unfaithful answers, and κ needs both kinds. Planted errors,
  scored by script, filled the gap.
- **GEPA overfit**: validation rose from 0.71 to 0.83 and test fell. The result is
  reported as measured, not as the validation number.
- **The gap-key scorer read the wrong circular for one row**, so one trap was
  scored against the wrong report and one circular was never run. Fixed before
  reporting.

## Use it

```bash
uv sync --extra llm
docker compose up -d qdrant                  # Qdrant 1.19, telemetry off
uv run python -m regradar.index build --strategy section
uv run python -m regradar.impact index       # the synthetic company's policies

export ANTHROPIC_API_KEY=...                 # from your secret store
REGRADAR_MODEL=claude-haiku-5-5 REGRADAR_SPEND=1 uv run uvicorn regradar.api:app
```

| Endpoint | Does |
| --- | --- |
| `POST /search` | hybrid retrieval with filters (dates, document kind, circular number); no model call |
| `POST /ask` | an answer whose every claim cites a chunk, or "not found"; withheld if the citations fail twice |
| `POST /impact` | obligations, gaps against the policies, an action plan, a review queue |
| `GET /circulars/{id}` | metadata and the RBI and archive URLs |

Without `REGRADAR_SPEND=1` the model runs dry: only cached requests are answered.
Every paid call is written to a ledger and refused past a $5 budget.

## How it was built

1. **Corpus** (`corpus/CARD.md`): RBI's servers refuse automated clients, so the
   290 documents were read from Internet Archive captures, with a named
   User-Agent, 2 s between requests and a cache. PDFs are parsed with PyMuPDF and
   checked against a second extractor (pypdf) page by page.
2. **Chunking**: section-aware chunks of up to 220 words within a chapter or annex,
   with character offsets; fixed and recursive chunking were measured against it.
3. **Retrieval**: Qdrant with two dense models and BM25 (IDF), reciprocal rank
   fusion in code, an optional cross-encoder, and payload filters.
4. **Golden set** (`eval/golden/CARD.md`): 150 questions (50 single-hop, 25
   multi-hop, 30 number/date, 15 identifier, 30 unanswerable), each with the exact
   gold text, split dev/test by a hash of the ID. Drafted by Claude Code from a
   stratified random sample of documents, located by keyword search, never by
   RegRadar's retriever; human review is pending.
5. **Answers** (`regradar/answer.py`): JSON claims with citations; code checks that
   every cited chunk was given, that every number appears in the cited text, and
   that the claim shares its words with what it cites; one retry, then withheld.
6. **Judge** (`regradar/judge.py`): tuned on dev labels, scored once on held-out
   labels behind a lock.
7. **Impact** (`regradar/impact.py`): obligations quoted from each section, gap
   matching against 197 policy paragraphs of a synthetic company with 12 planted
   gaps and 3 traps (`company/GAP_KEY.md`), a plan built by code. v1's checks
   (contradictory ratings, "nothing needed" alongside actions) are ported and
   extended. `examples/v1_vs_v2.md` compares both versions on one circular.
8. **CI** gates retrieval and citation quality on a fixed 30-question subset from
   committed results, so no model or Qdrant is needed in CI.

## Design decisions

*To be written by Nihar Damera.*

## Reproduce

```bash
uv run python -m regradar.evaluate --split test        # retrieval ablation (Qdrant)
uv run python -m regradar.evaluate_answers --model claude-haiku-5-5 --split test --spend
uv run python -m regradar.judge summary                 # from committed labels
uv run python -m regradar.evaluate_impact score --model claude-haiku-5-5
uv run python -m regradar.gate check                    # what CI runs
```

Model calls are cached under `data/llm_cache/`, so a re-run with the cache costs
nothing. The whole project's API spend is in the ledger there.

## Limitations

- One synthetic company, whose policies and gap key were written by one author
  (Claude Code), far shorter and cleaner than a real policy library.
- The golden set and the gap key were drafted by Claude Code, a different model
  from the ones evaluated but still a model; human review of the golden set is
  pending.
- 30 held-out human labels give a wide interval on κ.
- The impact pipeline's precision is not measured.
- Strike-through amendments in PDFs extract as both old and new text.
- The corpus is a sample of 290 documents, not every RBI circular; 142 notification
  pages in one ID range exist only as CAPTCHA captures in the archive.

## History: started as FinScoutAI

This repository was FinScoutAI until October 2026: four CrewAI agents on a local
Llama 3 8B, with code checks that overrule the model's own verifier. The v1 code is
tagged [`finscout-v1`](https://github.com/nihardamera/RegRadar/tree/finscout-v1).
v2 keeps the domain and the idea that code, not a model, has the last word on
citations and contradictions.
