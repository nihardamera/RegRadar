# FlexiPay India: the synthetic company (data card)

> **Everything in this folder is synthetic.** FlexiPay India Private Limited,
> FlexiCredit Finance Private Limited, Coastal Commercial Bank and KYCStream
> are fictional. The documents were written for RegRadar's evaluation and are
> not any company's policy or legal advice.

**What it is.** 21 policy, product and procedure documents (`FP-00` to
`FP-20`) for a payments company that is an online payment aggregator, a PPI
issuer and a UPI TPAP, and the lending service provider for its own NBFC
subsidiary. It extends v1's six-file knowledge base (`knowledge_base/`, kept
for v1), and keeps v1's facts where they were consistent.

**Why it exists.** The impact pipeline (M4) matches a circular's
obligations against a company's policies and reports the gaps. To measure
that, the policies need gaps whose answers are known.

**How it was written.** The documents were written by hand (with Claude
Code, which is not one of the models RegRadar evaluates) to *partly* comply:
most sections follow the rules, and some deliberately do not. Each planted
gap is listed in [`GAP_KEY.md`](GAP_KEY.md) with the circular and paragraph
it breaks. A gap stays in the key only after it has been checked against the
circular's text in the corpus.

**Structure.** Each file has YAML front matter (`doc_id`, `title`, `entity`,
`synthetic: true`, `owner`, `version`, `effective`, `last_reviewed`) and
numbered sections, so an answer can cite `FC-13 §4.1`. Some policies were
last reviewed before the rule they should implement was issued; that is
deliberate too.

**Limits.** One fictional company; documents far shorter and cleaner than a
real policy library; the gaps are ones a single author thought to plant.
