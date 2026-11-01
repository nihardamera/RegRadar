---
doc_id: FP-05
title: Information Security Policy
entity: FlexiPay India Private Limited and FlexiCredit Finance Private Limited
synthetic: true
owner: Chief Information Security Officer
version: 3.3
effective: 2024-03-01
last_reviewed: 2024-03-01
---

> **SYNTHETIC.** FlexiPay India and FlexiCredit Finance are fictional companies,
> written to evaluate RegRadar. Nothing here is a real company's policy.

# Information Security Policy

## 1. Governance
1.1 The Board approves this policy. The CISO reports to the CEO and presents
the information security posture to the IT Strategy Committee.

1.2 The IT Strategy Committee meets once a year.

## 2. Asset management
2.1 Every information asset has a named owner and a classification
(public, internal, confidential, restricted). Customer and payment data is
restricted.

## 3. Access control
3.1 Production systems are reached only through a bastion host with
multi-factor authentication. Privileged access is granted for a fixed time
and every session is logged.

3.2 Access rights are reviewed every 6 months.

## 4. Security of systems and applications
4.1 AES-256 encryption at rest; TLS 1.2 or higher in transit.

4.2 Vulnerability scans run monthly on internet-facing systems. An
external firm performs a penetration test of the FlexiPay app and Checkout
once a year.

4.3 Critical vulnerabilities are fixed within 15 days and high ones within
30 days.

4.4 Mobile apps check for rooted or jail-broken devices, use certificate
pinning and are obfuscated.

## 5. Monitoring
5.1 Logs from production systems go to a SIEM watched by an outsourced
Security Operations Centre, 24 hours a day. Logs are kept for 180 days.

## 6. Training
6.1 All staff complete security awareness training when they join and once
a year after that.

## 7. Incidents
7.1 Incidents are handled under FP-06.
