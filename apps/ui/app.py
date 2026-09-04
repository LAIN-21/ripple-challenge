from __future__ import annotations

import os

import requests
import streamlit as st

ORCH = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
DEFAULT_QUESTION = "Assess whether Port X is becoming congested."

st.set_page_config(page_title="Ledger402", layout="wide")
st.title("Ledger402")
st.caption("Autonomous Intelligence Procurement")
st.info(
    "Demo uses synthetic provider intelligence. "
    "x402 and XRPL settlement are real on Testnet."
)

question = st.text_input("Research Question", value=DEFAULT_QUESTION)
budget = st.number_input("Research Budget (drops)", min_value=0, value=5000, step=100)
st.caption("Displayed as XRP in the sidebar after a run. Budget is data-procurement only (no XRPL network fee).")

if st.button("Run Research", type="primary"):
    try:
        response = requests.post(
            f"{ORCH.rstrip('/')}/research",
            json={
                "task_type": "port_congestion",
                "question": question,
                "budget_drops": int(budget),
            },
            timeout=180,
        )
        if response.status_code >= 400:
            st.error(response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text)
        else:
            st.session_state["result"] = response.json()
    except Exception as exc:
        st.error(str(exc))

result = st.session_state.get("result")
if not result:
    st.write("Run a port-congestion research question to see the procurement workflow.")
    st.stop()

events = result.get("event_log") or []
labels = {
    "RESEARCH_REQUEST_UNDERSTOOD": "Understanding research request",
    "PUBLIC_SOURCE_QUERIED": "Public data queried",
    "PROVIDER_EVALUATED": "Premium provider evaluated",
    "PURCHASE_APPROVED": "Spending policy approved",
    "HTTP_402_OBSERVED": "HTTP 402 Payment Required observed",
    "X402_PAYMENT_NEGOTIATION_STARTED": "x402 payment negotiation started",
    "XRPL_PAYMENT_CONFIRMED": "XRPL payment confirmed",
    "PREMIUM_RESOURCE_UNLOCKED": "Premium intelligence unlocked",
}

st.subheader("Workflow")
for event in events:
    label = labels.get(event.get("type"), event.get("type"))
    st.write(f"✓ {label}")

initial = result.get("initial_result") or {}
st.write(f"Initial confidence: {int((result.get('initial_confidence') or 0) * 100)}%")
st.write(f"Agent decision: {result.get('decision')}")
st.write(f"Reason: {result.get('reason')}")

final = result.get("final_result") or {}
st.subheader("FINAL RESULT")
st.write(f"Congestion Risk: {final.get('congestion_risk', '—')}")
st.write(f"Confidence: {int((result.get('final_confidence') or 0) * 100)}%")
for line in final.get("evidence") or []:
    st.write(f"- {line}")
if result.get("fallback"):
    st.warning(f"Fallback: {result.get('fallback')} ({result.get('premium_purchase')})")

spent = int(result.get("spent_drops") or 0)
remaining = int(result.get("remaining_budget_drops") or 0)
starting = spent + remaining
tx = result.get("transaction_hash")

with st.sidebar:
    st.header("Procurement budget")
    st.write(f"Starting budget: {starting / 1_000_000:.4f} XRP ({starting} drops)")
    st.write(f"Spent: {spent / 1_000_000:.4f} XRP ({spent} drops)")
    st.write(f"Remaining: {remaining / 1_000_000:.4f} XRP ({remaining} drops)")
    st.write("Paid provider: Satellite Logistics Intelligence" if spent else "Paid provider: none")
    st.write(f"XRPL transaction: {tx or '—'}")
    st.write(f"Status: {result.get('payment_status')}")
    fee = result.get("network_fee_drops")
    if fee is not None:
        st.write(f"XRPL network fee (separate): {fee} drops")
    if tx:
        st.markdown(f"[Open on Testnet explorer](https://testnet.xrpl.org/transactions/{tx})")
