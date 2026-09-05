"""PREIMAGE-SHA-256 crypto-condition encoding for conditional delivery escrows.

xrpl.org documents the wire format (draft-thomas-crypto-conditions-02 section 8.1)
but publishes only one worked example. That example is the ground truth here.
"""

from __future__ import annotations

from ledger402.payment import build_preimage_condition

XRPL_DOCS_CONDITION = (
    "A0258020E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855810100"
)
XRPL_DOCS_FULFILLMENT = "A0028000"


def test_empty_preimage_matches_the_xrpl_docs_reference_vector():
    condition, fulfillment = build_preimage_condition(b"")
    assert condition == XRPL_DOCS_CONDITION
    assert fulfillment == XRPL_DOCS_FULFILLMENT


def test_condition_is_deterministic_for_the_same_preimage():
    condition_1, fulfillment_1 = build_preimage_condition(b"ledger402-demo-secret")
    condition_2, fulfillment_2 = build_preimage_condition(b"ledger402-demo-secret")
    assert condition_1 == condition_2
    assert fulfillment_1 == fulfillment_2


def test_different_preimages_yield_different_conditions():
    condition_1, _ = build_preimage_condition(b"delivered-payload-one")
    condition_2, _ = build_preimage_condition(b"delivered-payload-two")
    assert condition_1 != condition_2


def test_fulfillment_reveals_the_exact_preimage_bytes():
    preimage = b"the-32-byte-secret-goes-here!!!!"
    _, fulfillment = build_preimage_condition(preimage)
    # Fulfillment = A0 <len> 80 <preimage-len> <preimage>; the tail is the preimage itself.
    assert bytes.fromhex(fulfillment).endswith(preimage)
