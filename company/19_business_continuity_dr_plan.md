---
doc_id: FP-19
title: Business Continuity and Disaster Recovery Plan
entity: FlexiPay India Private Limited and FlexiCredit Finance Private Limited
synthetic: true
owner: Chief Technology Officer
version: 2.1
effective: 2024-06-01
last_reviewed: 2024-06-01
---

> **SYNTHETIC.** FlexiPay India and FlexiCredit Finance are fictional companies,
> written to evaluate RegRadar. Nothing here is a real company's policy.

# Business Continuity and Disaster Recovery Plan

## 1. Critical services
1.1 FlexiUPI, FlexiWallet, FlexiPay Checkout and loan repayment collection.

## 2. Recovery objectives
2.1 Recovery time objective (RTO): 2 hours for critical services. Recovery
point objective (RPO): 15 minutes.

## 3. Sites
3.1 Primary: AWS Mumbai (ap-south-1). Disaster recovery: AWS Hyderabad
(ap-south-2), in warm standby with continuous database replication.

## 4. Testing
4.1 A full switch-over to the disaster-recovery site is tested once a year.
Component fail-over tests run every quarter.

## 5. People
5.1 Operations teams can work remotely from day one of an outage. Customer
support has a second site in Pune.

## 6. Communication
6.1 For an outage of a critical service longer than 30 minutes, customers
see an in-app banner, and the sponsor bank and NPCI are informed.

## 7. Review
7.1 The plan is reviewed every year, and after every real fail-over.
