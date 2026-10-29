"""The synthetic company must always be labelled synthetic, and its documents
must be citable by a stable ID."""

from __future__ import annotations

import re

from regradar.company import load_policies

BANNER = "> **SYNTHETIC.** FlexiPay India and FlexiCredit Finance are fictional companies"


def test_every_policy_is_labelled_synthetic_in_its_metadata_and_its_text() -> None:
    policies = load_policies()
    assert len(policies) >= 20
    for policy in policies:
        assert policy.synthetic, policy.path.name
        assert policy.body.lstrip().startswith(BANNER), policy.path.name


def test_ids_are_unique_and_match_the_index_in_the_profile() -> None:
    policies = load_policies()
    ids = [policy.doc_id for policy in policies]
    assert len(ids) == len(set(ids))
    profile = next(policy for policy in policies if policy.doc_id == "FP-00")
    indexed = re.findall(r"^\| (F[PC]-\d\d) \| (.+?) \|$", profile.body, re.MULTILINE)
    titles = {policy.doc_id: policy.title for policy in policies}
    assert {doc_id for doc_id, _title in indexed} | {"FP-00"} == set(ids)
    for doc_id, title in indexed:
        assert titles[doc_id].startswith(title.split(" (")[0]), doc_id


def test_cross_references_point_at_documents_that_exist() -> None:
    policies = load_policies()
    ids = {policy.doc_id for policy in policies}
    for policy in policies:
        for ref in re.findall(r"\b(F[PC]-\d\d)\b", policy.body):
            assert ref in ids, f"{policy.doc_id} cites {ref}"


def test_every_policy_has_numbered_sections_to_cite() -> None:
    for policy in load_policies():
        assert re.search(r"^## 1\. ", policy.body, re.MULTILINE), policy.doc_id
        assert re.search(r"^1\.1 ", policy.body, re.MULTILINE), policy.doc_id
