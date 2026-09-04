import pytest

from ledger402.payment import (
    PaymentRequirementRejected,
    REQUIREMENT_REJECTED,
    SUCCESS,
    requirement_matches,
    select_payment_requirement,
    purchase_premium,
    reset_cache,
)


EXPECTED = {
    "expected_drops": 1200,
    "remaining_budget_drops": 5000,
    "expected_pay_to": "rMerchantPayToAddressForTests",
    "expected_network": "xrpl:1",
}

VALID = {
    "scheme": "exact",
    "network": "xrpl:1",
    "amount": "1200",
    "asset": "XRP",
    "payTo": "rMerchantPayToAddressForTests",
    "maxTimeoutSeconds": 60,
}


def test_requirement_matches_valid_invoice():
    assert requirement_matches(VALID, **EXPECTED) is True


@pytest.mark.parametrize(
    "override",
    [
        {"amount": "1201"},
        {"amount": "1199"},
        {"asset": "RLUSD"},
        {"payTo": "rWrongMerchant"},
        {"network": "xrpl:0"},
        {"scheme": "upto"},
    ],
)
def test_requirement_rejects_field_mismatches(override):
    invoice = {**VALID, **override}
    assert requirement_matches(invoice, **EXPECTED) is False


def test_requirement_rejects_amount_over_remaining_budget():
    tight = {**EXPECTED, "remaining_budget_drops": 1199}
    assert requirement_matches(VALID, **tight) is False


def test_select_raises_when_no_match():
    with pytest.raises(PaymentRequirementRejected):
        select_payment_requirement([{**VALID, "amount": "1"}], **EXPECTED)


class _FakeUnpaid:
    status_code = 402
    headers = {}
    text = "Payment Required"


class _FakePaid:
    def __init__(self, status_code, body=None, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body or {}
        self.content = b"{}" if body is not None else b""
        self.text = text

    def json(self):
        return self._body


def _install_paying_session(monkeypatch, invoice, *, remaining=5000, paid_status=200):
    from ledger402 import payment as payment_mod

    sign_calls: list = []

    def fake_buyer_session(*, expected_drops, remaining_budget_drops, selector_state):
        class FakeSession:
            def get(self, url, timeout=None):
                try:
                    selected = payment_mod.select_payment_requirement(
                        [invoice],
                        "xrpl:1",
                        "exact",
                        None,
                        expected_drops=expected_drops,
                        remaining_budget_drops=remaining_budget_drops,
                        expected_pay_to="rMerchantPayToAddressForTests",
                        expected_network="xrpl:1",
                    )
                except PaymentRequirementRejected as exc:
                    selector_state["rejected"] = exc
                    return _FakePaid(402, text="Payment Required")
                sign_calls.append(selected)
                return _FakePaid(paid_status, body={"ok": True, "synthetic": True})

        return FakeSession()

    monkeypatch.setattr(payment_mod, "_buyer_session", fake_buyer_session)
    monkeypatch.setattr(payment_mod, "observe_unpaid_402", lambda *a, **k: _FakeUnpaid())
    return sign_calls


def _purchase(*, run_id, remaining_budget_drops=5000):
    return purchase_premium(
        url="http://example/p",
        run_id=run_id,
        provider_id="p1",
        expected_drops=1200,
        remaining_budget_drops=remaining_budget_drops,
    )


MISMATCH_INVOICES = [
    ("amount-high", {**VALID, "amount": "1201"}),
    ("amount-low", {**VALID, "amount": "1199"}),
    ("wrong-asset", {**VALID, "asset": "RLUSD"}),
    ("wrong-payto", {**VALID, "payTo": "rWrongMerchant"}),
    ("wrong-network", {**VALID, "network": "xrpl:0"}),
    ("wrong-scheme", {**VALID, "scheme": "upto"}),
]


@pytest.mark.parametrize("run_id,invoice", MISMATCH_INVOICES)
def test_mismatch_never_reaches_signing(monkeypatch, run_id, invoice):
    reset_cache()
    sign_calls = _install_paying_session(monkeypatch, invoice)
    result = _purchase(run_id=run_id)
    assert sign_calls == []
    assert result.state == REQUIREMENT_REJECTED
    assert result.tx_hash is None


def test_amount_over_budget_never_signs(monkeypatch):
    reset_cache()
    sign_calls = _install_paying_session(monkeypatch, VALID)
    result = _purchase(run_id="over-budget", remaining_budget_drops=1199)
    assert sign_calls == []
    assert result.state == REQUIREMENT_REJECTED


def test_matching_invoice_may_sign(monkeypatch):
    reset_cache()
    sign_calls = _install_paying_session(monkeypatch, VALID)
    result = _purchase(run_id="match-ok")
    assert sign_calls == [VALID]
    assert result.state == SUCCESS
