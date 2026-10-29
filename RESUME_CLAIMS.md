# Resume claims and their evidence

Nothing goes on the resume or in the README without a row here pointing at a
committed file that proves it. Rates are reported with 95% bootstrap CIs.

| Claim | Evidence | Status |
| --- | --- | --- |
| v1: code checks overrule the LLM verifier; on the RBI authentication directions the verifier said CONSISTENT and the checks marked INCONSISTENT | `examples/sample_report.md`; `rag_agents.py` `final_verdict` | v1, verified |
| v1: 30 tests of the reading and checking code, no model needed | `tests/test_checks.py`; CI | v1, verified |
| ~300 public RBI circulars ingested with metadata and source URLs | — | pending (M1) |
| ~20 synthetic policy documents, each labelled synthetic | — | pending (M1) |
| Hybrid BM25 + dense in Qdrant with a cross-encoder reranker; ablation table with CIs | — | pending (M2/M3) |
| 150-question hand-written golden set, ≥ 20 unanswerable | — | pending (M3) |
| recall@10 dense-only … → hybrid + rerank … [CI] | — | pending (M3) |
| Citation-enforced answers; judge calibrated to my labels, Cohen's κ = … | — | pending (M3) |
| CI gate on recall@10 and citation precision | — | pending (M3) |
| Impact pipeline, v1 vs v2 on the same circular | — | pending (M4) |
| DSPy MIPROv2 / GEPA: +… pts on held-out data for $… | — | pending (M5) |
| Live demo | — | pending (M6) |
