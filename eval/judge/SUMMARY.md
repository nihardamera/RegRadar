# Judge calibration: held-out results

Judge: `claude-haiku-5-5`, effort low, prompt 2 (`regradar/judge.py`).
Scored once (`eval/judge/heldout.lock`). Written by `python -m regradar.judge summary`
from `calibration_heldout.json` and `eval/human/judge_labels.jsonl`.

| Cases | n | Label | Agreement | Cohen's kappa [95% CI] | Human yes | Judge yes |
| --- | --- | --- | --- | --- | --- | --- |
| all labelled | 30 | correct | 93.3 [83.3, 100.0] | 0.76 [0.32, 1.00] | 83% | 83% |
| all labelled | 30 | faithful | 83.3 [70.0, 96.7] | not defined (no human 'no' labels) | 100% | 83% |
| natural sample | 28 | correct | 96.4 [89.3, 100.0] | 0.84 [0.00, 1.00] | 86% | 89% |
| natural sample | 28 | faithful | 89.3 [75.0, 100.0] | not defined (no human 'no' labels) | 100% | 89% |

Planted errors marked unfaithful: 15/18 = 83.3% [66.7, 100.0]; by kind condition 1/3, entity 5/6, negation 5/5, number 3/3, wrong_chunk 1/1. Missed: q039~condition, q070~condition, q120~entity.
