---
doc_id: FP-01
title: Product Catalogue
entity: FlexiPay India Private Limited (with FlexiCredit Finance Private Limited)
synthetic: true
owner: Chief Product Officer
version: 6.1
effective: 2026-02-01
last_reviewed: 2026-02-01
---

> **SYNTHETIC.** FlexiPay India and FlexiCredit Finance are fictional companies,
> written to evaluate RegRadar. Nothing here is a real company's policy.

# FlexiPay India: Product Catalogue

## 1. FlexiUPI
1.1 UPI payments through the FlexiPay app, as a TPAP on Coastal Commercial
Bank's handle `@cfbflexi`. Supports peer-to-peer transfers, merchant QR
payments, bill payments and UPI AutoPay mandates.

1.2 Default limit ₹1,00,000 per transaction, as set by NPCI; FlexiPay applies
a lower limit of ₹5,000 for the first 24 hours after a new device is bound.

## 2. FlexiWallet
2.1 **FlexiWallet Small** is a small PPI opened with a mobile number verified
by OTP and a self-declared name and identity number. It can be loaded only
from a bank account or a card. Outstanding balance is capped at ₹10,000, and
loads at ₹10,000 a month and ₹1,20,000 a year. It cannot be used for cash
withdrawal or fund transfers to other wallets or bank accounts.

2.2 **FlexiWallet Full-KYC** is a PPI held after full KYC (FP-02). Outstanding
balance is capped at ₹1,00,000. It can send money to bank accounts and other
wallets, and can be linked to any UPI app.

2.3 Both wallets can be loaded by UPI, debit card, credit card and net
banking. Customers with an active FlexiCredit PayLater line can also load
FlexiWallet from that line (see 4.2).

## 3. FlexiPay Checkout (Payment Aggregator)
3.1 An online payment gateway and aggregation service for merchants:
cards, UPI, net banking and wallets. Merchants are onboarded under FP-03.

3.2 Funds collected for merchants are held in an escrow account with Coastal
Commercial Bank and settled under FP-12.

## 4. FlexiCredit loans (through FlexiCredit Finance)
4.1 **FlexiCredit Instant**: unsecured personal loans of ₹5,000 to ₹2,00,000
for 3 to 24 months, at a fixed rate of 18% to 32% a year. Applications,
disbursal and repayment all happen in the FlexiPay app.

4.2 **FlexiCredit PayLater**: a revolving credit line of ₹2,000 to ₹50,000,
billed monthly and repayable interest-free within 30 days of the bill date.
It can be spent at FlexiPay Checkout merchants or used to load FlexiWallet.

4.3 Loan terms, charges and the cooling-off rules are in FC-13 and FC-14.
