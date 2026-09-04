from ledger402.payment import PurchaseRecord, SUCCESS, purchase_premium, reset_cache


def test_idempotency_does_not_pay_again_on_success(monkeypatch):
    reset_cache()
    from ledger402 import payment as payment_mod

    existing = PurchaseRecord(state=SUCCESS, tx_hash="H1", body={"ok": True})
    payment_mod._cache["r1:p1"] = existing
    monkeypatch.setattr(payment_mod, "observe_unpaid_402", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not GET")))
    reused = purchase_premium(url="http://example/p", run_id="r1", provider_id="p1")
    assert reused.tx_hash == "H1"
    assert reused.state == SUCCESS
