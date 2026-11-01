# Gap key: what the synthetic policies get wrong, on purpose

> **SYNTHETIC.** This is the answer key for FlexiPay's planted gaps. It is the
> ground truth for the impact pipeline's gap matching (M4). It was written by
> the same author as the policies, not by a model RegRadar evaluates.

A row is **verified** only after the rule was found in the circular's text in
the corpus; the quote is copied from that text. Doc IDs are corpus IDs
(`rbi-n<notification Id>`). Paragraph numbers are the circular's own.

Three kinds of row are deliberately *not* gaps. **Not applicable**: the rule
exists, but not for this entity. **Superseded**: an older rule would flag it,
the current one does not. **Permissive**: the text says "may", not "shall".
A pipeline that flags those is wrong.

## Gaps

| ID | Policy | What the policy says | The rule | Circular | Status |
| --- | --- | --- | --- | --- | --- |
| G1 | FP-06 §3.2 | Incidents reported to RBI within 24 hours | "shall be reported to RBI in the Incident Reporting Format (Annex 1) within 6 hours of detection" | `rbi-n12715` Master Directions on Cyber Resilience and Digital Payment Security Controls for non-bank PSOs, §22(d) | verified |
| G2 | FC-14 §3.1 | Penal interest of 2% a month added to the loan's rate | Penalty "shall not be levied in the form of 'penal interest' that is added to the rate of interest"; "no capitalisation of penal charges" | `rbi-n12527` Fair Lending Practice - Penal Charges in Loan Accounts, ¶3(i) | verified |
| G3 | FC-13 §4.1 | 3% prepayment fee in the first 30 days, including the 3-day cooling-off | Exit "by paying the principal and the proportionate APR without any penalty during an initial cooling-off period" (a one-time processing fee may be kept) | `rbi-n12848` RBI (Digital Lending) Directions, 2025, §10(i)-(ii) | verified |
| G4 | FC-13 §6.1 | DLG of 8% of each portfolio | "total amount of DLG cover on any outstanding portfolio … shall not exceed five per cent of the amount of that loan portfolio" | `rbi-n12514` Guidelines on Default Loss Guarantee (DLG) in Digital Lending, ¶6 | verified |
| G5 | FC-15 §2.1 | Credit information reported monthly, within 7 days of month end | Updated "on a fortnightly basis (i.e., as on 15th and last day of the respective month)", submitted "within seven (7) calendar days of the relevant reporting fortnight" | `rbi-n12718` Frequency of reporting of credit information by CIs to CICs, ¶2 | verified |
| G6 | FC-16 §2.1-2.2 | Classified as fraud within 7 days; borrower told afterwards | A detailed Show Cause Notice, and "a reasonable time of not less than 21 days" to reply, before classification; a reasoned order. Applies to Base Layer NBFCs with assets of ₹500 crore and above (FlexiCredit: ₹560 crore, FP-00 §3.3) | `rbi-n12704` Master Directions on Fraud Risk Management in NBFCs, ¶1.2.1, ¶2.1.1-2.1.4 | verified |
| G7 | FC-13 §5.1 | PayLater limits raised automatically | "no automatic increase in credit limit unless an explicit request is received, evaluated and kept on record from the borrower" | `rbi-n12848` RBI (Digital Lending) Directions, 2025, §7(ii) | verified |
| G8 | FC-13 §3.2 | No KFS for loans of ₹10,000 or less | KFS instructions apply to "all retail and MSME term loan products extended by all regulated entities" | `rbi-n12663` Key Facts Statement (KFS) for Loans & Advances, ¶2 | verified |
| G9 | FP-00 §3.4, FP-12 §6.1 | Net worth ₹16 crore at the end of the third financial year since authorisation (March 2023) | "minimum net-worth of ₹25 crore by the end of third financial year of grant of authorisation" | `rbi-n12896` Master Direction on Regulation of Payment Aggregator (PA), ¶6(a) | verified |
| G10 | FP-12 §4.1 | Interest on 15% of the average escrow balance | "No interest shall be payable on the balances maintained in the escrow account(s) except on the core portion amount", computed as ¶17 sets out | `rbi-n12896` Master Direction on Regulation of Payment Aggregator (PA), ¶16 Table 1, ¶17 | verified |
| G11 | FC-17 §3.1 | Recovery calls and visits from 8 am to 9 pm | The NBFC and its agents must not resort to harassment, including "calling the borrower before 8:00 a.m. and after 7:00 p.m. for recovery of overdue loans" | `rbi-md362` RBI (NBFCs – Responsible Business Conduct) Directions, 2025, ¶100 | verified |
| G12 | FP-02 §2.3 | V-CIP recordings stored by a vendor in Singapore | "The NBFC shall store the entire data and recordings of V-CIP in a system / system located in India" (V-CIP is used for FlexiCredit borrowers, FP-02 §2.2) | `rbi-md361` RBI (NBFCs – Know Your Customer) Directions, 2025, V-CIP Records and Data Management (i) | verified |

## Deliberately not gaps

| ID | Policy | What the policy says | Why it is not a gap | Circular | Status |
| --- | --- | --- | --- | --- | --- |
| N1 | FP-05 §1.2, FP-18 §2.3 | IT Strategy Committee meets once a year | The quarterly ITSC rule is in the IT Governance MD, which applies to NBFCs in the Top, Upper and Middle Layers, not to FlexiCredit (Base Layer). FlexiPay, as a non-bank PSO, falls under `rbi-n12715` ¶7, which makes the Board responsible for oversight of information security risks and allows "primary oversight" to "be delegated to a sub-committee of the Board", with no meeting frequency | `rbi-n12562` Master Direction on IT Governance, Risk, Controls and Assurance Practices, ¶2 and ¶6 | not applicable, verified |
| N2 | FP-12 §2.1 | Merchants settled T+3 | The 2025 Master Direction leaves merchant settlement to "the agreement between the PA and the merchant", which "must transparently mention the settlement timelines" (FlexiPay's agreement does, FP-03 §5.1). Earlier PA guidelines fixed Ts+1 | `rbi-n12896` Master Direction on Regulation of Payment Aggregator (PA), ¶16 Table 1, Timelines | superseded, verified |
| N3 | FP-20 §3.1 | No risk-based step-up; the same two factors for every transaction | §8 is permissive: issuers "may … identify transactions for evaluation against behavioural / contextual parameters" and "additional checks beyond the minimum two-factor authentication may be resorted to". Two factors on every transaction (FP-20 §2.1) is the requirement | `rbi-n12898` RBI (Authentication mechanisms for digital payment transactions) Directions, 2025, ¶8 | permissive, verified |

## Planted but dropped

Kept here so the policies are not mistaken for a further gap source.

| ID | Policy | What the policy says | Why it was dropped |
| --- | --- | --- | --- |
| D1 | FP-01 §2.3, §4.2; FP-11 §3.1 | FlexiWallet can be loaded from the PayLater credit line | The rule against loading non-bank PPIs from credit lines is not in any corpus document (it was not issued as a notification) |
| D2 | FC-13 §4.2 | No cooling-off period for PayLater lines | The Digital Lending Directions' cooling-off (`rbi-n12848` §10) is for "a digital loan"; whether it covers a revolving line is not clear from the text |
