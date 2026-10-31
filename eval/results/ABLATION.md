# Retrieval ablation (golden set v1)

Golden set v1 (`eval/golden/`, drafted by Claude Code; human review pending).
Answerable questions only: **dev n = 50, test n = 70**. 95% percentile-bootstrap
intervals (10,000 resamples). A retrieved chunk counts when it overlaps a gold
span; **hit@10** = every part of the answer touched in the top 10 (recall@10 at
question level); **span recall@10** = share of the gold text the top 10 cover.
Raw results: `retrieval_dev.json`, `retrieval_test.json`; paired differences:
`paired_differences.txt` (computed from the per-question scores in those files).

## Test (headline)

| Configuration | hit@10 | span recall@10 | MRR | nDCG@10 | words@10 |
| --- | --- | --- | --- | --- | --- |
| section / dense (granite) | 87.1 [78.6, 94.3] | 89.3 [82.1, 95.7] | 60.6 [51.3, 69.7] | 67.2 [59.3, 74.9] | 1851 |
| section / dense (bge) | 81.4 [71.4, 90.0] | 85.0 [77.1, 92.1] | 55.7 [47.3, 64.4] | 63.2 [55.2, 71.2] | 1933 |
| section / BM25 | 84.3 [75.7, 92.9] | 87.9 [80.7, 94.3] | 64.0 [54.6, 73.1] | 69.6 [61.3, 77.7] | 2101 |
| **section / hybrid** | **92.9 [85.7, 98.6]** | **94.3 [88.6, 98.6]** | **71.1 [62.9, 78.8]** | **76.7 [69.5, 83.4]** | 1954 |
| section / hybrid + rerank top 20 | 91.4 [84.3, 97.1] | 95.0 [90.7, 98.6] | 68.9 [60.7, 76.8] | 74.9 [68.4, 81.2] | 1955 |
| fixed / hybrid | 90.0 [82.9, 95.7] | 91.3 [84.3, 97.0] | 64.3 [55.4, 73.1] | 70.9 [63.2, 78.2] | 2117 |
| recursive / hybrid | 88.6 [80.0, 95.7] | 88.4 [80.6, 95.0] | 65.8 [56.7, 74.4] | 72.4 [64.2, 80.0] | 1703 |
| fixed / dense (granite) | 81.4 [71.4, 90.0] | 82.9 [73.6, 91.4] | 54.3 [45.1, 63.7] | 61.0 [52.7, 69.5] | 2083 |

All 18 configurations, both splits: `retrieval_test.md`, `retrieval_dev.md`.

## Paired differences (same questions), test and dev

| Comparison | test hit@10 | test MRR | dev hit@10 | dev MRR |
| --- | --- | --- | --- | --- |
| hybrid − dense (section) | **+5.7 [+1.4, +11.4]** | **+10.5 [+2.1, +19.1]** | +8.0 [+0.0, +18.0] | **+14.0 [+7.6, +20.9]** |
| hybrid − BM25 (section) | **+8.6 [+1.4, +15.7]** | **+7.1 [+0.6, +13.8]** | −2.0 [−8.0, +4.0] | +4.8 [−2.4, +12.6] |
| rerank top 20 − hybrid (section) | −1.4 [−7.1, +4.3] | −2.2 [−10.0, +5.6] | +6.0 [+0.0, +14.0] | +4.5 [−2.4, +12.1] |
| rerank top 50 − top 20 (section) | −1.4 [−4.3, +0.0] | −0.7 [−1.4, −0.1] | +0.0 | −0.2 [−0.5, +0.0] |
| section − fixed (hybrid) | +2.9 [−2.9, +8.6] | +6.8 [−2.0, +15.5] | −4.0 [−14.0, +6.0] | **+9.3 [+2.0, +16.9]** |
| section − recursive (hybrid) | +4.3 [−2.9, +11.4] | +5.4 [−3.1, +14.1] | +2.0 [−6.0, +10.0] | +3.1 [−3.6, +10.0] |
| bge − granite (section, dense) | −5.7 [−12.9, +0.0] | −4.9 [−14.3, +4.7] | +0.0 [−8.0, +8.0] | −0.1 [−10.8, +10.6] |

## What it says

1. **Hybrid beats dense-only**, on both splits, most clearly on ranking (MRR
   +10.5 test, +14.0 dev). On test, hybrid also beats BM25 alone.
2. **The cross-encoder reranker does not reliably help.** On dev it looked like
   a small gain (hit@10 +6.0, interval touching zero); on test it is −1.4. It
   costs 1.6-5 s a query on CPU (`eval/retrieval_latency.json`) against 9 ms for
   hybrid. Reranking 50 candidates instead of 20 adds nothing on either split.
   The rerankers are MS MARCO models trained on web queries; domain shift is a
   plausible reason, not a tested one.
3. **Section-aware chunking** is best on test but its lead over fixed and
   recursive chunks is within the intervals (it is clearer on dev MRR). Chunk
   sizes are matched (words@10 1,700-2,100), so this is about where cuts fall.
4. bge is no better than granite.

## The default, and how it was chosen

Default: **section-aware chunks, hybrid (granite + BM25, RRF), no reranker.**
Chosen on dev alone, the reranker (top 20) would have been kept: it led on dev
hit@10 and nDCG. It is left off because its dev gain was at the edge of its
interval, it adds seconds per query, and test did not reproduce it. That last
reason used the test split, so the test numbers for the default are not a
clean held-out estimate of a dev-chosen system; the dev-chosen alternative
(section / hybrid + rerank 20) scores 91.4 hit@10 and 68.9 MRR on test.
