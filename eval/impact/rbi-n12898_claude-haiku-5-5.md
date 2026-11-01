# RegRadar impact report: Reserve Bank of India (Authentication mechanisms for digital payment transactions) Directions, 2025

- Circular: `rbi-n12898`
- Model: `claude-haiku-5-5`; company: FlexiPay India (synthetic)
- Verdict: **action needed**
- Code checks: all passed
- 14 obligations: 2 met, 3 gap, 3 partial, 3 not covered, 3 not applicable; 0 for review
- Status: draft for human review

## Action plan

1. **Remove the 7-day cut-off and the negligence exclusion for losses arising from transactions not compliant with the directions, and compensate the customer in full without demur.**
   - Priority P1; owner: Head of Customer Experience; due: not stated in the circular
   - Rule (¶9(b)): "If any loss arises out of transactions effected without complying with these directions, the issuer shall compensate the customer for the loss in full without demur."
   - Policy: FP-10 §2.4
2. **Add a statement to FP-18 that FlexiPay and FlexiCredit will ensure compliance with applicable RBI payment and lending directions by April 1, 2026, and that the CCO register tracks each direction's compliance status against that date.**
   - Priority P2; owner: Company Secretary; due: April 01, 2026
   - Rule (¶3): "All Payment System Providers and Payment System Participants, including banks and non-bank entities, shall ensure compliance with these directions by April 01, 2026"
   - Policy: FP-18 §3.2
3. **Add risk-based step-up authentication to FP-20 and map the policy explicitly against the paragraph 6 principles.**
   - Priority P2; owner: Chief Information Security Officer; due: not stated in the circular
   - Rule (¶6): "The technology and process deployed for authenticating a payment instruction by the Payment System Provider / Payment System Participant(s) shall comply with the following principles"
   - Policy: FP-20 §3.1
4. **Require at least one dynamically generated, transaction-unique factor (such as a per-transaction OTP or cryptogram) for non-card-present payments in FP-20.**
   - Priority P2; owner: Chief Information Security Officer; due: not stated in the circular
   - Rule (¶6(b)): "It shall be ensured that for digital payment transactions, other than card present transactions, at least one of the factors of authentication is dynamically created or proven"
   - Policy: FP-20 §2.1
5. **Add a pre-deployment requirement to test the robustness and integrity of each authentication mechanism, and record sign-off, before it goes live.**
   - Priority P2; owner: Chief Information Security Officer; due: before deployment
   - Rule (¶9(a)): "An issuer shall ensure the robustness and integrity of the authentication mechanism before deployment."
   - Policy: FP-20 §2.1, FP-20 §2.2
6. **Add an explicit commitment that all personal data handling complies with the Digital Personal Data Protection Act, 2023, and map the policy obligations to that Act.**
   - Priority P2; owner: Data Protection Officer; due: not stated in the circular
   - Rule (¶9(c)): "Issuers shall ensure adherence to the provisions of Digital Personal Data Protection Act, 2023."
   - Policy: FP-08 §6.1

## Findings

| Obligation | ¶ | Status | Policy | Finding |
| --- | --- | --- | --- | --- |
| All digital payment transactions in India are required to meet the norm of two factors of authentication. |  | met | FP-20 §2.1, FP-20 §3.1 | The policy requires two factors for every FlexiWallet payment and the UPI PIN as the second factor for UPI payments, and §3.1 applies the same two factors to every transaction, which meets the rule for domestic digital payments; the cross-border card flow in FP-20 §4.1 relies only on the issuer's authentication and is outside this domestic two-factor rule as drafted. |
| All participants in the payment chain must comply with the broad principles in the Directions while using a form of authentication. |  | not covered | - | No paragraph shown refers to the broad principles in the Directions that participants must follow when using authentication, so compliance with them cannot be shown from the policies provided. |
| All Payment System Providers and Payment System Participants, including banks and non-bank entities, shall ensure compliance with these directions by April 01, 2026, unless indicated otherwise for any specific provision herein. | 3 | partial (medium) | FP-18 §3.2 | The policy has no statement that the group will ensure compliance with these directions by April 1, 2026; FP-18 §3.2 only requires a register of applicable RBI directions, with the implementing policy and owner, which supports but does not meet the deadline commitment. |
| The technology and process for authenticating a payment instruction by the Payment System Provider / Payment System Participant(s) must comply with the principles in paragraph 6. | 6 | gap (medium) | FP-20 §3.1 | The policy states there is no risk-based authentication, so every transaction gets the same two factors regardless of risk, and the paragraph 6 principles are not in the text provided, so compliance with them cannot be confirmed. |
| All digital payment transactions must be authenticated by at least two distinct factors of authentication as defined in paragraph 5(f), unless exempted under Annexure-1. | 6(a) | met | FP-20 §2.1, FP-20 §2.2 | The policy requires two factors for every FlexiWallet payment, UPI payments use the UPI PIN as the second factor, and card wallet loads use the card issuer's SMS OTP, so the two-factor requirement is met. |
| For digital payment transactions other than card present transactions, at least one of the authentication factors must be dynamically created or proven, such that the proof of possession sent as part of the transaction is unique to that transaction. | 6(b) | gap (medium) | FP-20 §2.1 | For ordinary payments the policy relies on a bound device and a static app PIN or UPI PIN, with no factor shown as dynamically created or unique to each transaction, although dynamic OTP is used only for card wallet loads. |
| The authentication factor must be such that compromise of one factor does not affect the reliability of the other factor. | 6(c) | not covered | - | No paragraph shown states that compromise of one authentication factor leaves the other factor reliable. |
| System Providers and System Participants shall offer an authentication or tokenisation service that is accessible to all the applications / token requestors functioning in that operating environment for all use cases / channels or token storage mechanisms. | 7 | not covered | - | No policy paragraph requires an authentication or tokenisation service to be offered to all applications and token requestors across all use cases and channels; FP-20 §2.3 only states that FlexiPay offers no biometric or alternative authentication factors, which does not address accessibility to other requestors. |
| An issuer shall ensure the robustness and integrity of the authentication mechanism before deployment. | 9(a) | partial (medium) | FP-20 §2.1, FP-20 §2.2 | The policy describes the authentication factors in use but says nothing about testing the robustness and integrity of the authentication mechanism before deployment. |
| If any loss arises out of transactions effected without complying with these directions, the issuer shall compensate the customer for the loss in full without demur. | 9(b) | gap (high) | FP-10 §2.4 | The policy makes the customer bear the whole loss after 7 days or where negligence is alleged, whereas the rule requires full compensation without demur for losses from non-compliant transactions. |
| Issuers shall ensure adherence to the provisions of Digital Personal Data Protection Act, 2023. | 9(c) | partial (medium) | FP-08 §6.1 | The policy sets up a Data Protection Officer reporting to the CCO but does not commit the company to adhere to the DPDP Act, 2023 in its processing and storage practices. |

## Not applicable (3)

- Card issuers shall, by October 01, 2026, put in place a mechanism to validate non-recurring, cross-border card not present (CNP) transactions, where request for authentication is raised by an overseas merchant or overseas acquirer.: The obligation applies to card issuers, and FlexiPay issues only semi-closed PPIs and acts as a payment aggregator, not a card issuer.
- Card issuers shall register their Bank Identification Numbers (BINs) with card networks.: The obligation applies to card issuers, and FlexiPay does not issue cards, so BIN registration does not apply.
- A risk-based mechanism for handling all cross-border CNP transactions shall also be put in place by card issuers by October 01, 2026.: The obligation applies to card issuers, and FlexiPay does not issue cards; its cross-border card acceptance is as a payment aggregator.
