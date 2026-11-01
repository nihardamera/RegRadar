# v1 against v2 on the same circular

Both versions were run on the RBI's
[Authentication mechanisms for digital payment transactions Directions, 2025](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12898&Mode=0)
(RBI/2025-26/79, corpus ID `rbi-n12898`).

- v1 report: [`sample_report.md`](sample_report.md) (Llama 3 8B, 2026-10-06, at tag `finscout-v1`)
- v2 report: [`../eval/impact/rbi-n12898_claude-haiku-5-5.md`](../eval/impact/rbi-n12898_claude-haiku-5-5.md) (Haiku 5.5)

**This is not a controlled comparison.** The model, the method and the company
documents all differ: v1 read six short policy files, and v2 reads the 21 synthetic
policies in `company/`, which were written later with planted gaps. What the
comparison does show is what each design lets through.

| | v1 (four CrewAI agents) | v2 (pipeline with code checks) |
| --- | --- | --- |
| Unit of analysis | 5 "key changes" summarised from the circular | 14 obligations, each with a paragraph number and a quote that code found in the circular |
| Evidence for "what we do today" | Free text; no citation | Every met / gap / partial rating cites policy paragraphs (`FP-20 §2.1`) and quotes one; code checks the quote is in the paragraph |
| Unsupported claims | "additional verification steps for transactions exceeding ₹50,000 per month": in v1's knowledge base, ₹50,000 is the Video-KYC threshold in the KYC policy, not an authentication step | Cannot cite text it was not shown, or quote what the paragraph does not say: such ratings are sent back, then held for review |
| Contradictions | Cross-border changes rated "Applies: No" and "Impact: High"; the verifier agent said CONSISTENT and only the code checks caught it | The same contradiction is refused by code before a rating is accepted (`rating_problems`); the three card-issuer obligations are rated not applicable with reasons (FlexiPay issues PPIs, not cards) |
| Action plan | Written by a model, including two generic "review the assessment" actions | Built by code: one action per gap or partial, owner from the cited policy's front matter, priority from severity, due date from the obligation |
| Verdict | Read from the verifier's last line, overruled by code checks | Decided by code from the ratings; "no action needed" only with no actions and nothing in review |
| Result on this circular | INCONSISTENT (code checks failed) | Action needed; all code checks passed; 6 actions (1 P1, 5 P2) |

## Where v2 is wrong

v2 is not right everywhere, and its errors are the kind to know about:

- **It took the trap.** Paragraph 8 of the circular is permissive: issuers "may"
  add risk-based checks beyond two factors. FlexiPay's standard (FP-20 §3.1) has
  no risk-based step-up, and the gap key lists that as *not* a gap (N3). v2 rated
  the paragraph 6 principles as a gap citing FP-20 §3.1 and proposed "add
  risk-based step-up authentication". The prompt says a "may" rule is never a
  gap; the model reached the same place through a different obligation.
- **Findings beyond the key need a person.** v2 also flags that FlexiPay's
  everyday payments use a static PIN with device binding and no factor that is
  "dynamically created or proven" per transaction (¶6(b)), and that the customer
  liability policy (FP-10 §2.4) puts losses on the customer after 7 days where the
  circular says the issuer "shall compensate the customer for the loss in full
  without demur" (¶9(b)). Neither is in the gap key. Both read as plausible gaps,
  but the key's author did not plant them, so they are counted as unkeyed flags,
  not as hits.

How often v2 finds the planted gaps, and how often it takes the traps, across all
12 circulars in the key, is in [`../eval/results/IMPACT.md`](../eval/results/IMPACT.md).
