---
doc_id: FP-20
title: Authentication and Transaction Risk Standard
entity: FlexiPay India Private Limited
synthetic: true
owner: Chief Information Security Officer
version: 1.3
effective: 2024-08-01
last_reviewed: 2024-08-01
---

> **SYNTHETIC.** FlexiPay India and FlexiCredit Finance are fictional companies,
> written to evaluate RegRadar. Nothing here is a real company's policy.

# Authentication and Transaction Risk Standard

## 1. Device binding
1.1 The FlexiPay app is bound to the customer's SIM and device. A device
change needs a fresh SMS verification and is followed by a 24-hour cooling
period with a limit of ₹5,000.

## 2. Factors of authentication
2.1 Every payment from FlexiWallet uses two factors: the bound device
(possession) and the app PIN (knowledge). UPI payments use the UPI PIN as
the second factor.

2.2 Wallet loads by card use the card issuer's SMS OTP.

2.3 FlexiPay does not offer biometric or other alternative factors.

## 3. Risk-based checks
3.1 There is no risk-based step-up authentication: every transaction gets
the same two factors whatever its risk. Risk scoring is used only for
fraud alerts after the transaction (FP-04 3.1).

## 4. Cross-border transactions
4.1 FlexiPay Checkout accepts international cards for 210 merchants. Card
transactions from abroad are authenticated as the card issuer requires; no
extra checks are applied by FlexiPay.

## 5. Review
5.1 This standard is reviewed every two years.
