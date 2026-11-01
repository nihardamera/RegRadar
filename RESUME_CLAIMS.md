# Resume claims and their evidence

Nothing goes on the resume or in the README without a row here pointing at a
committed file that proves it. Rates are reported with 95% bootstrap CIs.

| Claim | Evidence | Status |
| --- | --- | --- |
| v1: code checks overrule the LLM verifier; on the RBI authentication directions the verifier said CONSISTENT and the checks marked INCONSISTENT | `examples/sample_report.md`; `rag_agents.py` `final_verdict` at tag `finscout-v1` | v1, verified |
| v1: 30 tests of the reading and checking code, no model needed | `tests/test_checks.py` at tag `finscout-v1`; CI | v1, verified (v1 code removed from v2 in M4; its failure modes have v2 tests, WORKLOG) |
| 290 public RBI documents (262 notifications 2019-2026, 28 consolidated Master Directions) ingested with metadata, RBI and archive URLs, PDF SHA-256 | `corpus/manifest.jsonl`, `corpus/CARD.md`; `tests/test_company.py` checks the cited ones | measured (M1). Say "290", not "~300" |
| Parse audit with three independent checks for lost text; 8 pages in 6 documents below 95% distinct-word recall against a second PDF reader | `corpus/AUDIT.md` (generated from the manifest) | measured (M1) |
| 21 synthetic policy documents, each labelled synthetic; 12 planted gaps verified against the circulars' text, plus 3 deliberate non-gaps | `company/`, `company/GAP_KEY.md`; `tests/test_company.py` | M1, verified |
| Hybrid BM25 + dense retrieval in Qdrant; 18-configuration ablation (3 chunkings x 4 retrievers + reranking) with bootstrap CIs and paired differences | `eval/results/ABLATION.md`, `retrieval_{dev,test}.json` | measured (M3) |
| Cross-encoder reranking tested and left off: helped on dev, not on test, at 1.6-5 s a query | `eval/results/ABLATION.md`, `eval/retrieval_latency.json` | measured; say "tested", not "uses" |
| 150-question golden set (50 single-hop, 25 multi-hop, 30 number/date, 15 identifier, 30 unanswerable), answers as text ranges with restated-rule alternatives | `eval/golden/questions.jsonl`, `eval/golden/CARD.md`; `tests/test_golden.py` | v1 complete. **Drafted by Claude Code, not hand-written**: say "drafted with Claude Code and reviewed by me" only once `check` shows the review done |
| recall@10 (hit@10) dense-only 87.1% → hybrid 92.9% on held-out test, paired +5.7 pts [+1.4, +11.4] (n = 70) | `eval/results/ABLATION.md`, `paired_differences.txt` | measured (M3). Do not claim an MRR gain on test: +7.7 [−0.7, +16.2] (clear on dev only). The default's choice used test (ABLATION.md) |
| Citation-enforced answers; LLM judge calibrated against my 55 human labels: held-out Cohen's κ = 0.76 [0.32, 1.00] on correctness (n = 30, 93% agreement); catches 15/18 planted faithfulness errors (83% [67, 100]) | `eval/judge/SUMMARY.md`, `eval/human/judge_labels.jsonl` | measured (M3). Faithfulness κ is not defined: every held-out answer was labelled faithful, so faithfulness rests on the planted-error rate (scored by script). Wide intervals: say "κ ≈ 0.76 on 30 held-out labels", not a precise figure |
| CI gate: hit@10, MRR and citation precision on a fixed 30-question subset, plus a re-run of the citation checks, from committed results (no model or Qdrant in CI) | `regradar/gate.py`, `eval/ci/`, `.github/workflows/ci.yml` | built, green |
| Impact pipeline (obligations → gap matching with citations → action plan, all code-checked) finds 11/12 planted policy gaps (strict match; 12/12 lenient) across 12 circulars for $0.65; takes 2/3 traps | `eval/results/IMPACT.md`, `eval/impact/`, `company/GAP_KEY.md` | measured (M4). Precision is not measured (29% of applicable obligations flagged): never quote the recall without the trap result. Gap key written by Claude Code |
| v1 vs v2 on the same circular (RBI authentication directions) | `examples/v1_vs_v2.md` | M4, qualitative; not a controlled comparison (different model and company docs) |
| FastAPI service: /search, /ask, /impact, /circulars, /health | `regradar/api.py`, `tests/test_api.py` | built, tested with fakes and smoke-tested live |
| DSPy MIPROv2 and GEPA on held-out test (n = 90): MIPROv2 +3.7 pts [−2.5, +9.8], GEPA −3.7 [−10.1, +2.6]; neither significant; $1.43 in all | `eval/results/DSPY.md`, `eval/results/dspy_test.json` | measured (M5). Claim "measured DSPy honestly: no significant gain; GEPA overfit 28 validation questions", not a gain |
| Live demo | — | pending (M6) |
