# RegRadar

Cited answers and impact reports over 290 Reserve Bank of India circulars and
Master Directions, measured at every step. Every claim cites the circular text it
rests on, and code checks every citation before anything is shown. For a new
circular, RegRadar lists the obligations, matches them against a company's
policies with citations, and builds an action plan.

Every number below comes from a committed evaluation file, with a 95% interval.

**Demo:** [huggingface.co/spaces/nihar-damera/RegRadar](https://huggingface.co/spaces/nihar-damera/RegRadar):
the 150 golden questions with the cited answers RegRadar gave, the 12 impact reports
and the evaluation. It is a static page of committed results (Hugging Face charges for
Gradio hosting); live search and answers run locally with `regradar.demo`.

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

The interactive demo (search, example answers, impact reports, and live answers
when a key is set, behind a $1 cap and per-visitor rate limits) runs on an embedded
Qdrant file, no server needed:

```bash
uv sync --extra demo
uv run python -m regradar.demo build-index   # from cached vectors
uv run python -m regradar.demo serve         # http://localhost:7860
uv run python -m regradar.site build         # the static page published to the Space
```

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
   RegRadar's retriever; a random sample of 30 reviewed by Nihar Damera (28 approved; 2 flagged, both resolved without change).
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

Each choice below was made against an alternative, and most were settled by a
measurement rather than a preference.

**1. Read the RBI site through the Internet Archive, not through a spoofed browser.**
rbi.org.in blocks automated clients (HTTP 418, a JavaScript challenge). Posing as a
browser would have worked and broken the site's stated wishes. Archive captures, with a
named User-Agent, 2 s between requests and a cache, gave 290 documents, at the cost of
142 notifications that exist only as CAPTCHA pages (`corpus/CARD.md`). Every document
keeps its RBI URL and archive URL.

**2. Gold answers are character ranges, not chunk IDs.** If the golden set named
chunks, every change of chunking would invalidate it, and chunking could not be
compared fairly. Each answer is a set of required parts, each with one or more exact
text ranges (a rule restated in a later Direction counts too). A retrieved chunk
"hits" when it overlaps a range, so fixed, recursive and section chunks are scored on
the same questions. The cost: every quote had to be located in the cleaned text, and
the cleaner cannot change offsets without re-locating them.

**3. Hybrid retrieval by default; the reranker measured and left off.** Hybrid beat
dense-only on test recall@10 by +5.7 points [+1.4, +11.4]. The cross-encoder helped on
dev but not on test, and costs 1.6-7 s a query on CPU against 9 ms for hybrid
(`eval/retrieval_latency.json`). A component that adds seconds and no measured gain
does not ship, however standard it is.

**4. Fusion in code, after Qdrant's own was found not to be repeatable.** The same
query gave a different top 5 on 9 of 40 immediate repeats, because server-side RRF
broke ties arbitrarily. Fusing in code with the same formula and ties broken by chunk
ID made every query repeatable, and it moved a headline number: the test MRR gain over
dense fell from +10.5 to +7.7, no longer clear of zero. The README reports the
repeatable number.

**5. Code, not the model, decides whether an answer stands.** Every claim must cite a
chunk the model was given, every number must appear in the cited text, and each claim
must share at least half its content words with what it cites. A failing answer is retried once with
the problems listed, then withheld rather than shown with a warning: a compliance user
reads past warnings. This is v1's idea (code checks overrule the verifier) made
general. On test, 4.3% of answers were withheld and 95% of out-of-corpus questions
declined.

**6. Unanswerable questions are a fifth of the golden set.** A RAG system that always
answers looks good on answerable questions alone. 30 of 150 questions have no answer in
the corpus, each with the keyword searches that found nothing recorded, so declining
is measured as a skill, not left to chance.

**7. A judge is trusted only as far as it agrees with people.** The judge was tuned on
dev labels and scored once on held-out labels behind a lock. Two findings changed it:
its verdicts contradicted its own reasons (so it now rules per claim and code decides
faithfulness), and citation enforcement left almost no unfaithful answers, so κ for
faithfulness was undefined. Planted errors, scored by script, measure what κ could not.
Correctness κ is 0.76 on 30 labels, and the interval says how little 30 labels prove.

**8. The impact pipeline's plan is written by code.** The model extracts obligations
(with quotes that code finds in the circular) and rates them against cited policy
paragraphs (with quotes that code finds in the paragraph). The action plan, owners,
priorities, due dates and the verdict are then computed, so "no action needed" cannot
sit beside a list of actions, the contradiction v1's verifier let through. Whatever
fails the checks twice goes to a review queue, not into the plan.

**9. A synthetic company with planted gaps and traps, so the pipeline can be scored.**
Real policy libraries are confidential and come with no answer key. FlexiPay's 21
policies were written to break 12 rules on purpose, each verified against the
circular's text, plus 3 traps that look like gaps but are not (not applicable,
superseded, a "may" rule). The traps are as important as the gaps: the pipeline found
11 of 12 gaps but took 2 of 3 traps, which is the honest picture of where it needs a
reviewer.

**10. DSPy was measured, and not adopted.** MIPROv2 and GEPA were run on the
cited-answer step with a judge-free metric that returns feedback, optimising on dev and
scoring once on 90 held-out questions. MIPROv2 was +3.7 points [−2.5, +9.8]; GEPA was
−3.7 [−10.1, +2.6] after fitting its 28 validation questions (its rewritten prompt quotes
their misses). Neither beats the hand-written prompt beyond noise, so the hand-written
prompt stays. Re-running variants until one cleared zero on the same test set would
have manufactured a gain; the result is reported as measured.

**11. The cheapest capable model, with the spend designed in.** Haiku 5.5 does the
answering, judging and impact work; Sonnet 5.5 only proposes and reflects for DSPy.
Every call goes through one client that is dry-run by default, caches by prompt (Claude
takes no temperature, so the cache is what makes a re-run reproducible), writes each
paid call to a ledger, and refuses a call that could cross the budget. The whole
project cost $2.25.

**12. CI checks quality without a model or a database.** The gate recomputes recall,
MRR and citation precision for a fixed 30-question subset from committed retrieval and
answers, and re-runs the citation checks on stored claims. A change to retrieval or the
checks must come with refreshed results, so a regression appears in the same pull
request, and CI costs nothing.

**13. A static demo over a hosted one.** Hugging Face now charges for Gradio hosting,
and a public page that calls a model spends someone's key. The public demo shows the
committed results (every golden question with its cited answer and sources, the impact
reports, the evaluation); the interactive app with live answers, a spend cap and rate
limits runs locally.

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
  from the ones evaluated but still a model; a person reviewed a random 30 of
  the 150 golden questions, not all of them.
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
