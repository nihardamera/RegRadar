# DSPy: MIPROv2 and GEPA on the cited-answer step

**Result: neither optimiser beat the hand-written prompt on held-out test by more
than the noise.** MIPROv2 is +3.7 points [−2.5, +9.8]; GEPA is −3.7 [−10.1, +2.6].
Both improved the validation score they optimised against, and GEPA's gain did not
transfer.

Raw results: [`dspy_test.json`](dspy_test.json) (per-question test scores, so every
interval here can be recomputed); programs: [`../dspy/`](../dspy/); code:
[`regradar/optimize.py`](../../regradar/optimize.py).

## Setup

- **Program:** answer a golden question from its five retrieved chunks (section /
  hybrid, fixed per question in `eval/dspy/retrieval.json`) with claims that cite
  them; the citation checks of `regradar/answer.py` decide whether it stands (one
  retry with the problems, then withheld). Only the instructions and demonstrations
  differ between programs.
- **Metric (no judge):** an answerable question scores the mean of citation recall
  and citation precision against the gold spans, and 0 if declined or withheld;
  declining scores 1 when the question is unanswerable or retrieval missed the
  answer. It also returns feedback in words (parts missed, which chunk had them,
  which check failed), which GEPA reads.
- **Data:** 60 dev questions split 32 train / 28 validation by a hash of the ID;
  **90 test questions scored once per program at the end.** Never used for
  optimising.
- **Models:** task Haiku 5.5 (effort low); MIPROv2's proposer and GEPA's reflection
  model Sonnet 5.5 (effort medium). MIPROv2 `auto="light"`, up to 2 bootstrapped
  demonstrations; GEPA 200 metric calls. All calls through the project's cached,
  capped client.

## Results

| Program | Validation (n = 28) | **Test (n = 90)** | Test − baseline (paired) |
| --- | --- | --- | --- |
| Baseline: the hand-written prompt | 0.71 [0.56, 0.85] | **0.80 [0.73, 0.86]** | |
| MIPROv2 (new instructions + 2 demonstrations) | 0.83 [0.69, 0.93] | **0.84 [0.78, 0.90]** | +3.7 [−2.5, +9.8] |
| GEPA (rewritten instructions) | 0.83 [0.72, 0.93] | **0.77 [0.69, 0.84]** | −3.7 [−10.1, +2.6] |

Scores are means of the per-question metric (0 to 1); differences in points.
95% percentile-bootstrap intervals, 10,000 resamples.

## Cost

| | USD |
| --- | --- |
| MIPROv2 optimisation (Sonnet proposals, Haiku trials; includes a first attempt that stopped on a missing dependency, whose calls the second attempt replayed from cache) | 0.69 |
| GEPA optimisation | 0.50 |
| Scoring three programs on validation and test | 0.24 |
| **Total** | **1.43** |

## What it says

1. **28 validation questions are too few to optimise a prompt against.** GEPA's
   instructions grew from 90 to 693 words and quote specific misses from its
   training questions ("Past misses: a question asked what is required of every
   digital payment..."). That is fitting the examples, and test fell.
2. **MIPROv2 points the right way but is within noise.** Its instructions add a
   step-by-step procedure and checks for near-duplicate and superseded documents,
   plus two demonstrations. The paired interval's half-width is about 6 points at
   n = 90; confirming +3.7 would take roughly 250 test questions at this variance.
3. **The hand-written prompt was already shaped by the same failures** (the number
   check, the not-found rule), and the code checks catch the worst outputs whatever
   the prompt. There was less left to find than in the papers' benchmarks.
4. The baseline here (0.80) is the DSPy port of the production prompt, not the
   production run itself: the adapter adds its own field markers, so its outputs
   differ slightly from `answers_test_*.json`.
