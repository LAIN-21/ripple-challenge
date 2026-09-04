from types import SimpleNamespace

import pytest

from ledger402.payment import (
    PurchaseRecord,
    SUCCESS,
    UNKNOWN,
    purchase_premium,
    reset_cache,
)


def test_idempotency_does_not_pay_again_on_success(monkeypatch):
    reset_cache()
    from ledger402 import payment as payment_mod

    existing = PurchaseRecord(state=SUCCESS, tx_hash="H1", body={"ok": True})
    payment_mod._cache["r1:p1"] = existing
    monkeypatch.setattr(payment_mod, "observe_unpaid_402", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not GET")))
    reused = purchase_premium(
        url="http://example/p",
        run_id="r1",
        provider_id="p1",
        expected_drops=1200,
        remaining_budget_drops=5000,
    )
    assert reused.tx_hash == "H1"
    assert reused.state == SUCCESS


def test_missing_wallet_does_not_enter_payment_cache(monkeypatch):
    reset_cache()
    from ledger402 import payment as payment_mod

    monkeypatch.delenv("XRPL_WALLET_SEED", raising=False)
    with pytest.raises(RuntimeError, match="wallet configuration missing"):
        purchase_premium(
            url="http://example/p",
            run_id="no-wallet",
            provider_id="p1",
            expected_drops=1200,
            remaining_budget_drops=5000,
        )
    assert "no-wallet:p1" not in payment_mod._cache


def _unpaid_402():
    return SimpleNamespace(status_code=402, headers={}, text="Payment Required")


def _install_paid_session(monkeypatch, *, status, headers=None, body=None, error=None):
    from ledger402 import payment as payment_mod

    get_calls = {"n": 0}

    class FakeResponse:
        def __init__(self):
            self.status_code = status
            self.headers = headers or {}
            self.content = b"{}" if body is not None else b""
            self.text = "upstream 500"
            self._body = body or {}

        def json(self):
            return self._body

    class FakeSession:
        def get(self, url, timeout=None):
            get_calls["n"] += 1
            if error is not None:
                raise error
            return FakeResponse()

    def fake_buyer_session(*, expected_drops, remaining_budget_drops, selector_state):
        del expected_drops, remaining_budget_drops, selector_state
        return FakeSession()

    monkeypatch.setattr(payment_mod, "_buyer_session", fake_buyer_session)
    monkeypatch.setattr(payment_mod, "observe_unpaid_402", lambda *a, **k: _unpaid_402())
    monkeypatch.setattr(
        payment_mod,
        "_decode_payment_header",
        lambda response: {"transaction": "TXHASH500", "network_fee": 12} if status != 200 or error else None,
    )
    return get_calls


def test_non_200_after_pay_is_unknown_and_not_retried(monkeypatch):
    reset_cache()
    get_calls = _install_paid_session(monkeypatch, status=500)
    first = purchase_premium(
        url="http://example/p",
        run_id="unk-run",
        provider_id="p1",
        expected_drops=1200,
        remaining_budget_drops=5000,
    )
    assert first.state == UNKNOWN
    assert first.tx_hash == "TXHASH500"
    assert first.network_fee_drops == 12
    second = purchase_premium(
        url="http://example/p",
        run_id="unk-run",
        provider_id="p1",
        expected_drops=1200,
        remaining_budget_drops=5000,
    )
    assert second.state == UNKNOWN
    assert get_calls["n"] == 1


def test_exception_after_pay_client_is_unknown_and_not_retried(monkeypatch):
    reset_cache()
    get_calls = _install_paid_session(monkeypatch, status=200, error=RuntimeError("facilitator timeout"))
    first = purchase_premium(
        url="http://example/p",
        run_id="exc-run",
        provider_id="p1",
        expected_drops=1200,
        remaining_budget_drops=5000,
    )
    assert first.state == UNKNOWN
    assert "facilitator timeout" in (first.error or "")
    second = purchase_premium(
        url="http://example/p",
        run_id="exc-run",
        provider_id="p1",
        expected_drops=1200,
        remaining_budget_drops=5000,
    )
    assert second is first
    assert get_calls["n"] == 1
