"""Which circulars belong in the corpus.

The corpus is what a compliance team at FlexiPay (a payment aggregator, PPI
issuer and UPI app, and the lending service provider for its NBFC) would
need to read. A title is kept when it names one of those subjects and does
not name an unrelated kind of entity or market.

In late 2025 the RBI reissued its instructions as one set of Directions per
kind of entity ("Commercial Banks - KYC", "Small Finance Banks - KYC",
"Non-Banking Financial Companies - KYC", ...), with nearly the same text.
Only the NBFC, payment-system and all-entity versions are kept: near-copies
would make "which chunk answers this question" ambiguous in the golden set.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

INCLUDE = re.compile(
    r"payment|prepaid|\bPPI|aggregator|\bUPI\b|card|tokeni[sz]ation|mandate|"
    r"know your customer|\bKYC\b|money.laundering|\bAML\b|\bCFT\b|section 12a|"
    r"digital lending|\bNBFC|non-banking financial|lending|loan|credit information|"
    r"penal charges|fair practices?|interest rate|recovery|"
    r"fraud|cyber|information technology|\bIT\b|outsourcing|"
    r"customer service|customer protection|grievance|ombudsman|complaint|"
    r"account aggregator|data|authentication|key facts? statement|compensation",
    re.IGNORECASE,
)

# Entity types that are not FlexiPay or FlexiCredit, as RBI names them in titles.
OTHER_ENTITIES = re.compile(
    r"commercial banks?|small finance banks?|payments banks?|local area banks?|"
    r"regional rural banks?|\bRRBs?\b|co-?operative|\bUCBs?\b|"
    r"all india financial institutions?|\bAIFIs?\b|asset reconstruction|\bARCs?\b|"
    r"housing finance compan|\bHFCs?\b|primary dealers?|"
    r"state bank|foreign banks?|banking companies",
    re.IGNORECASE,
)

# Subjects that match INCLUDE by accident ("card" in "Aadhaar card", "data" in
# "data on deposits") but are not FlexiPay's business.
UNRELATED = re.compile(
    r"currency chest|bank ?notes?|coins?\b|sovereign gold|gold monetisation|"
    r"government securit|treasury bills?|state development loans|market borrowing|"
    r"foreign exchange|\bFEMA\b|export|import|overseas|external commercial|"
    r"priority sector|lead bank|second schedule|\bCRR\b|\bSLR\b|liquidity adjustment|"
    r"basel|capital adequacy|risk weights?|investment portfolio|"
    r"agricultur|kisan|farmer|self.help group|\bSHG|"
    r"interest equalisation|rupee drawing|vostro|"
    r"income tax|goods and services tax|pension|small savings|"
    r"y2k|year 2000|forex|\bATMs?\b|deposits?\b|agency banks?|government business|"
    r"capital market|irrevocable payment|bank finance to",
    re.IGNORECASE,
)


def relevant(title: str) -> bool:
    if not INCLUDE.search(title) or UNRELATED.search(title):
        return False
    names_nbfcs = re.search(r"NBFC|non-banking", title, re.IGNORECASE) is not None
    return names_nbfcs or not OTHER_ENTITIES.search(title)


def select(pages: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The newest `limit` relevant pages that have a PDF, newest first.

    Notification Ids rise with publication, so "newest" is the highest Id.
    """
    usable = [p for p in pages if p.get("ok") and p.get("pdf_url") and relevant(p["title"])]
    usable.sort(key=lambda p: p["id"], reverse=True)
    return usable[:limit]
