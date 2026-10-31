# Resume claims and their evidence

Nothing goes on the resume or in the README without a row here pointing at a
committed file that proves it. Rates are reported with 95% bootstrap CIs.

| Claim | Evidence | Status |
| --- | --- | --- |
| v1: code checks overrule the LLM verifier; on the RBI authentication directions the verifier said CONSISTENT and the checks marked INCONSISTENT | `examples/sample_report.md`; `rag_agents.py` `final_verdict` | v1, verified |
| v1: 30 tests of the reading and checking code, no model needed | `tests/test_checks.py`; CI | v1, verified |
| 290 public RBI documents (262 notifications 2019-2026, 28 consolidated Master Directions) ingested with metadata, RBI and archive URLs, PDF SHA-256 | `corpus/manifest.jsonl`, `corpus/CARD.md`; `tests/test_company.py` checks the cited ones | measured (M1). Say "290", not "~300" |
| Parse audit with three independent checks for lost text; 8 pages in 6 documents below 95% distinct-word recall against a second PDF reader | `corpus/AUDIT.md` (generated from the manifest) | measured (M1) |
| 21 synthetic policy documents, each labelled synthetic; 12 planted gaps verified against the circulars' text, plus 3 deliberate non-gaps | `company/`, `company/GAP_KEY.md`; `tests/test_company.py` | M1, verified |
| Hybrid BM25 + dense in Qdrant with a cross-encoder reranker; ablation table with CIs | — | pending (M2/M3) |
| 150-question golden set (50 single-hop, 25 multi-hop, 30 number/date, 15 identifier, 30 unanswerable), answers as text ranges with restated-rule alternatives | `eval/golden/questions.jsonl`, `eval/golden/CARD.md`; `tests/test_golden.py` | v1 complete. **Drafted by Claude Code, not hand-written**: say "drafted with Claude Code and reviewed by me" only once `check` shows the review done |
| recall@10 dense-only … → hybrid + rerank … [CI] | — | pending (M3) |
| Citation-enforced answers; judge calibrated to my labels, Cohen's κ = … | — | pending (M3) |
| CI gate on recall@10 and citation precision | — | pending (M3) |
| Impact pipeline, v1 vs v2 on the same circular | — | pending (M4) |
| DSPy MIPROv2 / GEPA: +… pts on held-out data for $… | — | pending (M5) |
| Live demo | — | pending (M6) |
