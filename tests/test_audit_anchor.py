"""The composite SHA-256 proof anchor (deliverable spec, pillar 2)."""

from __future__ import annotations

from ledger402 import audit

HASH_A = "A" * 64
HASH_B = "B" * 64
SUMMARY = "HIGH congestion risk at Port X."


def test_fold_is_order_independent():
    """Two runs that bought the same evidence must anchor identically."""
    assert audit.xor_fold_hashes([HASH_A, HASH_B]) == audit.xor_fold_hashes([HASH_B, HASH_A])


def test_fold_of_no_settlements_is_zero():
    """A zero fold marks a report that no on-ledger purchase backs."""
    assert audit.xor_fold_hashes([]) == "0" * 64
    assert audit.xor_fold_hashes([None, ""]) == "0" * 64


def test_fold_ignores_case_and_hex_prefix():
    assert audit.xor_fold_hashes(["0x" + HASH_A.lower()]) == audit.xor_fold_hashes([HASH_A])


def test_fold_skips_non_hex_without_corrupting_the_anchor():
    assert audit.xor_fold_hashes(["not-a-hash", HASH_A]) == audit.xor_fold_hashes([HASH_A])


def test_anchor_is_deterministic_for_a_fixed_timestamp():
    first = audit.compute_audit_anchor(
        dossier_summary=SUMMARY, tx_hashes=[HASH_A], timestamp="2026-09-05T10:00:00+00:00"
    )
    second = audit.compute_audit_anchor(
        dossier_summary=SUMMARY, tx_hashes=[HASH_A], timestamp="2026-09-05T10:00:00+00:00"
    )
    assert first["audit_hash"] == second["audit_hash"]
    assert len(first["audit_hash"]) == 64


def test_a_changed_report_breaks_the_anchor():
    """The whole point: the anchor must not verify against altered findings."""
    anchor = audit.compute_audit_anchor(dossier_summary=SUMMARY, tx_hashes=[HASH_A])
    assert audit.verify_audit_anchor(anchor, SUMMARY)
    assert not audit.verify_audit_anchor(anchor, SUMMARY + " Actually LOW.")


def test_a_changed_settlement_set_breaks_the_anchor():
    anchor = audit.compute_audit_anchor(dossier_summary=SUMMARY, tx_hashes=[HASH_A])
    forged = {**anchor, "tx_hashes": [HASH_B]}
    assert not audit.verify_audit_anchor(forged, SUMMARY)


def test_field_separator_prevents_boundary_confusion():
    """A summary must not be able to impersonate the hash field and shift the preimage."""
    folded = audit.xor_fold_hashes([HASH_A])
    stamp = "2026-09-05T10:00:00+00:00"
    honest = audit.compute_audit_anchor(
        dossier_summary="report", tx_hashes=[HASH_A], timestamp=stamp
    )
    spoofed = audit.compute_audit_anchor(
        dossier_summary=f"report{folded}", tx_hashes=[HASH_A], timestamp=stamp
    )
    assert honest["audit_hash"] != spoofed["audit_hash"]


def test_anchor_records_what_is_needed_to_recompute_it():
    anchor = audit.compute_audit_anchor(dossier_summary=SUMMARY, tx_hashes=[HASH_A, HASH_B])
    assert anchor["settlement_count"] == 2
    assert anchor["algorithm"] == "SHA-256"
    assert anchor["tx_hashes"] == [HASH_A, HASH_B]
    assert anchor["timestamp"]


def test_verify_rejects_an_empty_anchor():
    assert not audit.verify_audit_anchor({}, SUMMARY)


def test_events_are_timestamped():
    log = audit.new_log()
    audit.add(log, "TEST_EVENT", value=1)
    assert log[0]["type"] == "TEST_EVENT"
    assert log[0]["detail"] == {"value": 1}
    assert log[0]["at"]
