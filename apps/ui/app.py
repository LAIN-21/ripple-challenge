"""Ledger402 dashboard.

The deliverable spec asks for a dual-screen demo: a business view and an agent execution
view. Both live here as tabs, driven by the same run, so the audience can watch the agent
reason and then see what that reasoning bought.
"""

from __future__ import annotations

import json
import os

import plotly.graph_objects as go
import requests
import streamlit as st

ORCH = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
DEFAULT_QUESTION = "Assess whether Port X is becoming congested."
DROPS_PER_XRP = 1_000_000
EXPLORER_TX = "https://testnet.xrpl.org/transactions/{hash}"

# The agent's own vocabulary, rendered for humans. Unknown types fall through as-is so a
# new event never silently disappears from the trace.
EVENT_LABELS = {
    "RESEARCH_REQUEST_UNDERSTOOD": "Research objective understood",
    "TASK_REJECTED": "Task rejected (fail closed)",
    "PROVIDERS_DISCOVERED": "Providers discovered",
    "PUBLIC_SOURCE_QUERIED": "Public source queried (free)",
    "PUBLIC_SOURCE_UNAVAILABLE": "Public source unavailable",
    "CONFIDENCE_ASSESSED": "Confidence re-assessed",
    "PROVIDERS_RANKED": "Providers ranked by confidence per drop",
    "PURCHASE_APPROVED": "Spending policy approved",
    "HTTP_402_OBSERVED": "HTTP 402 Payment Required observed",
    "X402_PAYMENT_NEGOTIATION_STARTED": "x402 payment negotiation started",
    "XRPL_PAYMENT_CONFIRMED": "XRPL payment confirmed",
    "PREMIUM_RESOURCE_UNLOCKED": "Premium intelligence unlocked",
    "PROCUREMENT_FAILED": "Procurement failed",
    "PROCUREMENT_ABORTED": "Procurement aborted (configuration)",
    "OBJECTIVE_MET": "Objective met",
    "PURCHASE_CEILING_REACHED": "Purchase ceiling reached",
    "BUDGET_EXHAUSTED": "Procurement budget exhausted",
    "REPORT_SYNTHESIZED": "Report synthesized",
    "AUDIT_ANCHOR_COMPUTED": "Audit anchor committed",
}

MONEY_EVENTS = {
    "HTTP_402_OBSERVED",
    "X402_PAYMENT_NEGOTIATION_STARTED",
    "XRPL_PAYMENT_CONFIRMED",
    "PREMIUM_RESOURCE_UNLOCKED",
}

st.set_page_config(page_title="Ledger402", layout="wide")


def xrp(drops: float) -> str:
    return f"{drops / DROPS_PER_XRP:.4f} XRP"


@st.cache_data(ttl=30)
def fetch_capabilities() -> dict:
    try:
        response = requests.get(f"{ORCH.rstrip('/')}/capabilities", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return {}


# ----------------------------------------------------------------------- controls

st.title("Ledger402")
st.caption("Autonomous intelligence procurement on the XRP Ledger")

capabilities = fetch_capabilities()
if capabilities.get("llm_enabled"):
    provider = (capabilities.get("llm_provider") or "").capitalize()
    st.caption(
        f"Reasoning: LangGraph loop · {provider} ({capabilities.get('llm_model')}) for "
        "question classification and report writing only — never for spending decisions."
    )
else:
    st.caption(
        "Reasoning: LangGraph loop, fully deterministic (no GROQ_API_KEY/GEMINI_API_KEY set). "
        "Classification and report writing use rule-based fallbacks."
    )

st.info(
    "Provider intelligence is synthetic. x402 negotiation and XRPL Testnet settlement "
    "are real."
)

question = st.text_input("Research objective", value=DEFAULT_QUESTION)

col_budget, col_target, col_cap = st.columns(3)
with col_budget:
    budget = st.number_input(
        "Procurement budget (drops)", min_value=0, value=5000, step=100
    )
with col_target:
    target = st.slider(
        "Target confidence",
        min_value=0.60,
        max_value=0.95,
        value=0.85,
        step=0.01,
        help=(
            "The agent buys evidence until it reaches this. At 0.85 it settles once "
            "(satellite). Raise it above 0.88 and it buys a second feed."
        ),
    )
with col_cap:
    max_purchases = st.number_input(
        "Max settlements per run", min_value=0, max_value=5, value=3, step=1,
        help="Safety rail bounding worst-case spend, independent of the budget.",
    )

st.caption(
    "Budget covers data procurement only. XRPL network fees are reported separately and "
    "never deducted from it."
)

if st.button("Run research", type="primary"):
    st.session_state.pop("result", None)
    with st.spinner("Agent is discovering, deciding and settling…"):
        try:
            response = requests.post(
                f"{ORCH.rstrip('/')}/research",
                json={
                    "question": question,
                    "budget_drops": int(budget),
                    "target_confidence": float(target),
                    "max_purchases": int(max_purchases),
                },
                timeout=300,
            )
            if response.status_code >= 400:
                detail = response.json().get("detail", response.text) if response.headers.get(
                    "content-type", ""
                ).startswith("application/json") else response.text
                st.session_state["error"] = detail
            else:
                st.session_state["result"] = response.json()
                st.session_state.pop("error", None)
        except Exception as exc:
            st.session_state["error"] = str(exc)

error = st.session_state.get("error")
if error:
    st.error("The agent declined this objective.")
    if isinstance(error, dict):
        st.write(error.get("reason") or error.get("error"))
        with st.expander("Classification"):
            st.json(error.get("classification") or {})
    else:
        st.write(error)

result = st.session_state.get("result")
if not result:
    st.write("Run a research objective to see the procurement loop.")
    st.stop()

report = result.get("report") or {}
spent = int(result.get("spent_drops") or 0)
remaining = int(result.get("remaining_budget_drops") or 0)
starting = int(result.get("budget_drops") or (spent + remaining))
purchases = result.get("purchases") or []
successful = [p for p in purchases if p.get("status") == "SUCCESS"]

# -------------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("Procurement")
    st.metric("Spent", xrp(spent), delta=f"{spent} drops")
    st.metric("Remaining", xrp(remaining), delta=f"{remaining} drops")
    st.caption(f"Starting budget: {xrp(starting)} ({starting} drops)")

    st.divider()
    st.subheader("Settlements")
    if not successful:
        st.write("None.")
    for purchase in successful:
        st.write(f"**{purchase['provider_name']}** — {purchase['price_drops']} drops")
        tx = purchase.get("transaction_hash")
        if tx:
            st.caption(f"`{tx[:16]}…`")
            st.markdown(f"[Open on Testnet explorer]({EXPLORER_TX.format(hash=tx)})")
        fee = purchase.get("network_fee_drops")
        if fee is not None:
            st.caption(f"Network fee (separate): {fee} drops")

    failed = [p for p in purchases if p.get("status") != "SUCCESS"]
    if failed:
        st.divider()
        st.subheader("Not settled")
        for purchase in failed:
            st.write(f"{purchase['provider_name']} — {purchase['status']}")

    anchor = result.get("audit_anchor") or {}
    if anchor:
        st.divider()
        st.subheader("Audit anchor")
        st.caption("SHA-256(report ‖ XOR of settlement hashes ‖ timestamp)")
        st.code(anchor.get("audit_hash", ""), language=None)
        st.caption(f"{anchor.get('settlement_count', 0)} settlement(s) folded in")

# ------------------------------------------------------------------------- tabs

business_tab, agent_tab, evidence_tab = st.tabs(
    ["Executive briefing", "Agent execution", "Evidence & rights"]
)

with business_tab:
    initial_confidence = result.get("initial_confidence") or 0.0
    final_confidence = result.get("final_confidence") or 0.0

    headline_left, headline_right = st.columns([2, 1])
    with headline_left:
        st.subheader(report.get("congestion_risk", "—"))
        st.write(report.get("summary", ""))
    with headline_right:
        st.metric(
            "Confidence",
            f"{final_confidence:.0%}",
            delta=f"{(final_confidence - initial_confidence):+.0%} from public evidence",
        )
        target_confidence = result.get("target_confidence") or 0.0
        if result.get("objective_met"):
            st.caption(f"Target {target_confidence:.0%} — met")
        else:
            # Both figures at one decimal: "92% but not reached" reads as a bug when the
            # agent actually stopped at 91.6%.
            st.caption(
                f"Target {target_confidence:.1%} — not reached "
                f"(stopped at {final_confidence:.1%})"
            )

    if not result.get("objective_met") and result.get("stop_reason"):
        st.warning(result["stop_reason"])

    st.divider()

    chart_left, chart_right = st.columns(2)

    with chart_left:
        st.markdown("**Confidence bought**")
        # A waterfall reads as "what each purchase was worth", which is the whole
        # commercial argument of the product. Steps are the *realised* confidence
        # deltas between consecutive assessments, not the projections used to decide.
        assessments = [
            event["detail"]["confidence"]
            for event in result.get("event_log") or []
            if event.get("type") == "CONFIDENCE_ASSESSED"
        ]
        steps = [
            (assessments[i + 1] - assessments[i]) * 100
            for i in range(len(assessments) - 1)
        ][: len(successful)]

        labels = ["Public evidence"] + [
            f"{purchase['provider_name']}<br>({purchase['price_drops']} drops)"
            for purchase in successful[: len(steps)]
        ]
        y_values = [initial_confidence * 100] + steps

        waterfall = go.Figure(
            go.Waterfall(
                orientation="v",
                measure=["absolute"] + ["relative"] * len(steps),
                x=labels,
                y=y_values,
                text=[
                    f"{value:+.1f}" if index else f"{value:.1f}"
                    for index, value in enumerate(y_values)
                ],
                textposition="outside",
                connector={"line": {"color": "rgba(128,128,128,0.4)"}},
                increasing={"marker": {"color": "#2E7D32"}},
                totals={"marker": {"color": "#1565C0"}},
            )
        )
        waterfall.add_hline(
            y=(result.get("target_confidence") or 0) * 100,
            line_dash="dot",
            annotation_text="target",
        )
        waterfall.update_layout(
            yaxis_title="Confidence (%)",
            showlegend=False,
            height=340,
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(waterfall, use_container_width=True)

    with chart_right:
        st.markdown("**Congestion signals**")
        merged: dict[str, float] = {}
        for item in result.get("evidence") or []:
            for key, value in (item.get("payload") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    merged[key] = float(value)

        display = [
            ("Yard utilization", merged.get("yard_utilization"), "%"),
            ("Berth occupancy", merged.get("berth_occupancy"), "%"),
            ("Anchored vessels", merged.get("anchored_vessels_delta"), "Δ%"),
            ("Container density", merged.get("container_density_delta"), "Δ%"),
            ("Truck activity", merged.get("truck_activity_delta"), "Δ%"),
        ]
        display = [(label, value, unit) for label, value, unit in display if value is not None]
        if display:
            bars = go.Figure(
                go.Bar(
                    x=[value * 100 for _, value, _ in display],
                    y=[f"{label} ({unit})" for label, _, unit in display],
                    orientation="h",
                    marker_color=[
                        "#C62828" if value >= 0.85 else "#EF6C00" if value >= 0.3 else "#1565C0"
                        for _, value, _ in display
                    ],
                    text=[f"{value * 100:.0f}" for _, value, _ in display],
                    textposition="outside",
                )
            )
            bars.update_layout(
                height=340, showlegend=False, margin=dict(l=10, r=30, t=30, b=10)
            )
            st.plotly_chart(bars, use_container_width=True)
        else:
            st.write("No numeric signals in the evidence set.")

    if report.get("evidence"):
        st.markdown("**Evidence cited**")
        for line in report["evidence"]:
            st.write(f"- {line}")

    for caveat in report.get("caveats") or []:
        st.caption(f"⚠ {caveat}")

with agent_tab:
    st.markdown("**Decision trace**")
    head_a, head_b, head_c, head_d = st.columns(4)
    head_a.metric("Loop iterations", result.get("iterations", 0))
    head_b.metric("Settlements", result.get("settlement_count", 0))
    head_c.metric("Spent", f"{spent} drops")
    head_d.metric("Providers seen", len(result.get("providers_considered") or []))

    st.divider()
    st.markdown("**Ranking per iteration**")
    for round_index, ranking_round in enumerate(result.get("rankings") or [], start=1):
        st.caption(
            f"Iteration {round_index} — confidence "
            f"{(ranking_round.get('confidence_before') or 0):.0%}"
        )
        rows = [
            {
                "Provider": candidate["provider_name"],
                "Price (drops)": candidate["price_drops"],
                "Marginal gain": f"{candidate['marginal_confidence_gain']:.1%}",
                "Conf / 1000 drops": candidate["confidence_per_1000_drops"],
                "Bought": "✓" if candidate["provider_id"] == ranking_round.get("selected") else "",
                "Reason": candidate["reason"],
            }
            for candidate in ranking_round.get("candidates") or []
        ]
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No paid candidates remained.")

    st.divider()
    st.markdown("**Execution log**")
    for event in result.get("event_log") or []:
        event_type = event.get("type", "")
        label = EVENT_LABELS.get(event_type, event_type)
        marker = "💸" if event_type in MONEY_EVENTS else "•"
        st.write(f"{marker} `{event.get('at', '')}` {label}")
        detail = event.get("detail") or {}
        if detail:
            with st.expander("detail", expanded=False):
                st.json(detail)

with evidence_tab:
    st.markdown("**Evidence held by the agent**")
    for item in result.get("evidence") or []:
        badge = (
            f"paid — {item['price_drops']} drops" if item.get("paid") else "free"
        )
        st.markdown(f"**{item['provider_name']}** ({badge})")
        payload = dict(item.get("payload") or {})
        policy = payload.pop("odrl", None)
        st.json(payload)
        if policy:
            st.caption("Usage rights received with payment (ODRL)")
            st.code(json.dumps(policy, indent=2), language="json")
        st.divider()

    anchor = result.get("audit_anchor") or {}
    if anchor:
        st.markdown("**Audit anchor**")
        st.caption(anchor.get("verification", ""))
        st.json(anchor)
