# RegRadar for an NBFC compliance team

*One page for the Chief Compliance Officer of a mid-size NBFC (₹500–5,000 crore
assets, Base or Middle Layer). Figures marked **measured** come from this
repository's evaluation files; everything else is a planning assumption to be
replaced with the customer's own numbers in discovery.*

## The problem

The RBI issues circulars and Master Directions every week, and consolidated
Directions now restate years of earlier circulars in new words. For each one,
someone has to answer: does it apply to us, what exactly must we do, by when,
and which of our policies no longer comply? Today that is an analyst reading
the circular, then searching a policy library by memory. The cost is analyst
time, and the risk is the obligation nobody connected to the policy that
breaks it.

## What RegRadar does

1. **Ask:** answers a question about the circulars with claims that each cite
   the circular text. Code checks every citation before an answer is shown; an
   answer that fails twice is withheld, not shown with a warning.
2. **Impact:** for a new circular, lists each obligation with its paragraph and
   a quote, rates it against the company's policies (met, gap, partial, not
   covered, not applicable) citing policy paragraphs, and builds an action plan
   with owners and dates. Anything the checks cannot verify goes to a review queue.

Every output is a **draft for a named reviewer**, never a filing.

## Discovery questions

1. Which regulators and document types matter (RBI only? SEBI, IRDAI, FIU-IND)?
2. Where does the policy library live (SharePoint, a GRC tool, PDFs), and who owns each policy?
3. How is a new circular handled today: who reads it, how long does it take, where is the decision recorded?
4. What is the NBFC's layer and asset size, and which activities does it carry on (co-lending, digital lending, PPIs)? Applicability turns on these.
5. What would a wrong answer cost: a missed obligation, or a false alarm? Which is worse for you?
6. Can documents leave your network? Which cloud regions, if any, are approved?
7. Who would review RegRadar's drafts, and how many hours a week can they give it?

## Success metrics (agree before a pilot)

| Metric | How it is measured | This repository (measured, synthetic company) |
| --- | --- | --- |
| Retrieval: the answer text is in the top 10 | Golden questions written from the customer's own circulars | 92.9% [85.7, 98.6] on 70 held-out questions (`eval/results/ABLATION.md`) |
| Answers withheld rather than wrong | Share of answers rejected by the citation checks | 4.3% rejected; 95% of out-of-corpus questions declined (`eval/results/answers_test_*.json`) |
| Planted policy gaps found | A gap key written by the compliance team before the pilot | 11 of 12 across 12 circulars (`eval/results/IMPACT.md`) |
| Traps avoided (not applicable, superseded, "may" rules) | Same key | 1 of 3 avoided: it applied a Middle-Layer rule to a Base-Layer NBFC and read a "may" rule as a gap |
| Share of obligations flagged (the reviewer's workload) | Flags ÷ applicable obligations | 29%; precision not yet measured, which a pilot must do |
| Analyst time per circular | Timed, before and after | to measure in the pilot |

## ROI model

Hours saved = circulars a month × (hours today − hours with RegRadar). Value =
hours saved × loaded cost of an analyst hour. Illustration only, to be replaced
in discovery: 40 relevant circulars a month × (6 h − 2.5 h) × ₹2,500 an hour ≈
₹3.5 lakh a month. Model cost is small beside this: the whole evaluation in this
repository, including impact reports on 12 circulars, cost under $3 of API calls.
The larger costs are the reviewer's time and integration with the policy library.

## Deployment options

| Option | Data path | Fits |
| --- | --- | --- |
| Customer VPC (AWS Mumbai / Azure Central India), model via the cloud's managed Claude endpoint in-region | Circulars, policies and prompts stay in the customer's cloud account | Most NBFCs; data residency in India |
| On-premises retrieval, model API for generation only | Policies are embedded and searched locally; only retrieved paragraphs are sent to the model | Strict policy-confidentiality requirements |
| Fully local (open model on the customer's GPUs) | Nothing leaves the network | Highest control; lower answer quality, needs re-evaluation on the golden set |

**DPDP Act, 2023.** Circulars are public. Policies are confidential but rarely
hold personal data; customer data is not needed and should not be loaded.
If any personal data enters (e.g. complaint samples), RegRadar is a processor
for the NBFC as fiduciary: purpose limitation, retention limits on the response
cache and ledger, and access logs apply.

## The human-review queue

Items go to a reviewer, not into the plan, when: an obligation's quote is not
found in the circular; a rating cites a paragraph it was not shown or misquotes
it; the ratings contradict each other; or an obligation is "not covered" by any
policy. The reviewer accepts, edits or rejects each item; their decisions are the
labels that re-calibrate the checks and the judge.

## Risk register

| Risk | Control |
| --- | --- |
| A missed obligation (the costliest error) | Section-by-section extraction; coverage check (every obligation rated or queued); "not covered" items always reviewed |
| A false gap (time wasted) | Severity and citations on every gap; the reviewer sees the policy quote beside the rule |
| Applicability judged wrongly (layer, size, activity) | Company profile given to the model; "not applicable" findings listed with reasons for review |
| A superseded rule applied | Corpus metadata (dates, repeal lists); consolidated Directions preferred; still a known weakness |
| Model or vendor change shifts behaviour | CI gate on a fixed question set; re-run the golden set and the gap key on any model change |
| Confidential policies leave the network | VPC or on-prem retrieval options above; no training on customer data |

## What happens when the model is wrong

- **It cites text that does not say what it claims:** code catches most of this
  (quotes and numbers must be in the cited text); the answer is retried once,
  then withheld.
- **It reads a "may" rule as a "must", or misjudges applicability:** code cannot
  catch this. In this repository's evaluation the pipeline did take such traps
  (2 of 3 traps, `eval/results/IMPACT.md`), which is why every gap is a draft with the rule
  and the policy quoted side by side for the reviewer.
- **It misses an obligation entirely:** the coverage check catches obligations
  that were extracted but not rated, not ones never extracted. Mitigation: the
  reviewer reads the circular's section list against the obligation list.
- **It is confidently wrong in a way nobody notices:** sample audits. A reviewer
  re-checks a random 10% of accepted items each month, and the judge's agreement
  with them (Cohen's κ, measured at 0.76 on correctness here) is tracked over time.
