"""Ledger402 three-panel clearinghouse dashboard."""

from __future__ import annotations

import json
import os

import plotly.graph_objects as go
import requests
import streamlit as st

ORCH = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
GATEWAY = os.getenv("PROVIDER_URL", os.getenv("FREE_PROVIDER_URL", "http://localhost:8001"))
DEFAULT_QUESTION = (
    "Assess whether Port of Singapore (PSA) is facing critical yard and terminal congestion"
)
DROPS_PER_XRP = 1_000_000
EXPLORER_TX = "https://testnet.xrpl.org/transactions/{hash}"

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

st.set_page_config(page_title="Ledger402", layout="wide")


def xrp(drops: float) -> str:
    return f"{drops / DROPS_PER_XRP:.4f} XRP"


@st.cache_data(ttl=15)
def fetch_royalties() -> dict:
    response = requests.get(f"{GATEWAY.rstrip('/')}/royalties", timeout=5)
    response.raise_for_status()
    return response.json()


def fetch_capabilities() -> dict:
    try:
        response = requests.get(f"{ORCH.rstrip('/')}/capabilities", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return {}


def merged_metrics(result: dict) -> dict[str, float]:
    merged: dict[str, float] = {}
    for item in result.get("evidence") or []:
        payload = item.get("payload") or {}
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        for key, value in {**metrics, **payload}.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[key] = float(value)
    return merged


def advisory_markdown(result: dict) -> str:
    report = result.get("report") or {}
    lines = [
        "# Ledger402 Advisory Dossier",
        "",
        f"**Subject:** {result.get('subject') or ''}",
        f"**Question:** {result.get('question') or ''}",
        f"**Verdict:** {report.get('congestion_risk', '—')}",
        f"**Confidence:** {(result.get('final_confidence') or 0):.1%}",
        f"**Spent:** {result.get('spent_drops') or 0} drops",
        "",
        "## Executive summary",
        report.get("summary") or "",
        "",
        "## Evidence cited",
    ]
    for bullet in report.get("evidence") or []:
        lines.append(f"- {bullet}")
    lines += ["", "## Caveats"]
    for caveat in report.get("caveats") or []:
        lines.append(f"- {caveat}")
    lines += ["", "## On-ledger verification"]
    for purchase in result.get("purchases") or []:
        if purchase.get("status") != "SUCCESS":
            continue
        tx = purchase.get("transaction_hash") or ""
        lines.append(
            f"- {purchase.get('provider_name')}: [{tx}]({EXPLORER_TX.format(hash=tx)}) "
            f"({purchase.get('price_drops')} drops)"
        )
    anchor = result.get("audit_anchor") or {}
    if anchor:
        lines += ["", f"**SHA-256 audit anchor:** `{anchor.get('audit_hash', '')}`"]
    return "\n".join(lines)


def run_stream(payload: dict):
    params = {
        "question": payload["question"],
        "budget_drops": payload["budget_drops"],
        "target_confidence": payload["target_confidence"],
        "max_purchases": payload["max_purchases"],
        "delivery_tier": payload["delivery_tier"],
        "replay": str(payload["replay"]).lower(),
    }
    events: list[dict] = []
    result = None
    error = None
    log_box = st.empty()
    with requests.get(
        f"{ORCH.rstrip('/')}/research/stream",
        params=params,
        stream=True,
        timeout=300,
    ) as response:
        if response.status_code >= 400:
            error = response.text
            return events, result, error
        for raw in response.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "):
                continue
            chunk = json.loads(raw[len("data: ") :])
            kind = chunk.get("kind")
            if kind == "event":
                events.append(chunk.get("event") or {})
                with log_box.container():
                    for event in events[-12:]:
                        label = EVENT_LABELS.get(event.get("type"), event.get("type"))
                        st.caption(f"{event.get('at', '')} · {label}")
            elif kind == "result":
                result = chunk.get("result")
            elif kind == "error":
                error = chunk.get("reason")
    return events, result, error


capabilities = fetch_capabilities()
st.title("Ledger402")
st.caption("Two-sided agent-native data clearinghouse on the XRP Ledger")
if capabilities.get("llm_enabled"):
    st.caption(
        f"Reasoning: Gemini ({capabilities.get('llm_model')}) for classification and "
        "Tier 1 prose only — never for spending."
    )
else:
    st.caption("Reasoning: deterministic fallbacks. Spending decisions stay unit-tested Python.")

st.info(
    "Provider intelligence is synthetic. x402 negotiation and XRPL Testnet settlement are real "
    "unless Offline Replay Mode is checked."
)

left, center, right = st.columns([1.1, 2.0, 1.3])

with left:
    st.subheader("Directive")
    question = st.text_area("Research objective", value=DEFAULT_QUESTION, height=90)
    target = st.slider(
        "Target confidence",
        min_value=0.60,
        max_value=0.95,
        value=0.85,
        step=0.01,
        help="0.85 settles once (1200 drops). 0.92 settles twice (1800 drops).",
    )
    tier_label = st.radio(
        "Output",
        (
            "Tier 1: Strategic Advisory Dossier",
            "Tier 2: Raw Verified Data Bundle",
        ),
    )
    delivery_tier = "tier_1" if tier_label.startswith("Tier 1") else "tier_2"
    replay = st.checkbox("Use Offline Replay Mode", value=False)
    budget = st.number_input("Procurement budget (drops)", min_value=0, value=5000, step=100)
    max_purchases = st.number_input("Max settlements per run", min_value=0, max_value=5, value=3, step=1)
    if st.button("Run research", type="primary"):
        st.session_state.pop("error", None)
        st.session_state.pop("result", None)
        st.session_state.pop("tier", None)
        try:
            _events, result, error = run_stream(
                {
                    "question": question,
                    "budget_drops": int(budget),
                    "target_confidence": float(target),
                    "max_purchases": int(max_purchases),
                    "delivery_tier": delivery_tier,
                    "replay": replay,
                }
            )
            if error:
                st.session_state["error"] = error
            else:
                st.session_state["result"] = result
                st.session_state["tier"] = delivery_tier
        except Exception as exc:
            st.session_state["error"] = str(exc)

    if st.session_state.get("error"):
        st.error("The agent declined this objective or the run failed.")
        st.write(st.session_state["error"])

result = st.session_state.get("result")
active_tier = st.session_state.get("tier") or delivery_tier

with center:
    st.subheader("Deliverable")
    if not result:
        st.write("Run a research objective to render the dossier or data bundle.")
    elif result.get("error"):
        st.warning(result.get("reason") or result.get("error"))
    elif active_tier == "tier_2" or result.get("delivery_tier") == "tier_2":
        bundle = result.get("data_bundle") or {}
        records = bundle.get("records") or []
        st.caption(bundle.get("discount") or "")
        if records:
            st.dataframe(records, width="stretch", hide_index=True)
        else:
            st.write("No joined records.")
        st.download_button(
            "Download JSON Bundle",
            data=bundle.get("json") or json.dumps(records, indent=2),
            file_name="Ledger402_Data_Bundle.json",
            mime="application/json",
        )
        st.download_button(
            "Download CSV Bundle",
            data=bundle.get("csv") or "",
            file_name="Ledger402_Data_Bundle.csv",
            mime="text/csv",
        )
        st.markdown("**Cryptographic license manifest**")
        st.json(
            {
                "receipts": bundle.get("receipts"),
                "odrl": bundle.get("odrl"),
                "integrity_hash": bundle.get("integrity_hash"),
            }
        )
    else:
        report = result.get("report") or {}
        metrics = merged_metrics(result)
        berth = metrics.get("berth_occupancy") or metrics.get("berth_occupancy_ratio")
        yard = metrics.get("yard_utilization") or metrics.get("container_yard_utilization_ratio")
        spent = int(result.get("spent_drops") or 0)
        c1, c2, c3 = st.columns(3)
        c1.metric("Berth occupancy", f"{berth:.0%}" if berth is not None else "—")
        c2.metric("Yard saturation", f"{yard:.0%}" if yard is not None else "—")
        c3.metric("Total drops spent", spent)
        if yard is not None and yard >= 0.85:
            st.error("CRITICAL BOTTLENECK DETECTED")
        chart_a, chart_b = st.columns(2)
        with chart_a:
            if berth is not None and yard is not None:
                fig = go.Figure(
                    go.Bar(
                        x=["Berth occupancy", "Yard utilization"],
                        y=[berth * 100, yard * 100],
                        marker_color=["#1565C0", "#C62828" if yard >= 0.85 else "#EF6C00"],
                    )
                )
                fig.update_layout(yaxis_title="%", height=280, margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig, width="stretch")
        with chart_b:
            queue = metrics.get("vessel_queue") or metrics.get("vessel_queue_count")
            wait = metrics.get("average_wait_hours")
            if queue is not None:
                fig = go.Figure(
                    go.Bar(
                        x=["Vessel queue", "Avg wait hours"],
                        y=[queue, wait or 0],
                        marker_color="#EF6C00",
                    )
                )
                fig.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig, width="stretch")
        st.markdown(report.get("summary") or "")
        for line in report.get("evidence") or []:
            st.write(f"- {line}")
        st.markdown("**Cryptographic verification**")
        for purchase in result.get("purchases") or []:
            if purchase.get("status") != "SUCCESS":
                continue
            tx = purchase.get("transaction_hash")
            if tx:
                st.markdown(
                    f"- {purchase.get('provider_name')}: "
                    f"[{tx[:16]}…]({EXPLORER_TX.format(hash=tx)})"
                )
        anchor = result.get("audit_anchor") or {}
        if anchor:
            st.code(anchor.get("audit_hash", ""), language=None)
        markdown_text = advisory_markdown(result)
        st.download_button(
            "Download Advisory Dossier",
            data=markdown_text,
            file_name="Ledger402_Advisory_Dossier.md",
            mime="text/markdown",
        )

with right:
    tab_live, tab_b2c = st.tabs(["Live execution", "B2C marketplace"])
    with tab_live:
        if not result:
            st.caption("Execution trace appears here after a run.")
        else:
            st.metric("Confidence", f"{(result.get('final_confidence') or 0):.1%}")
            st.metric("Settlements", result.get("settlement_count") or 0)
            for event in result.get("event_log") or []:
                label = EVENT_LABELS.get(event.get("type"), event.get("type"))
                st.write(f"`{event.get('at', '')}` {label}")
    with tab_b2c:
        uploaded = st.file_uploader("Curator CSV / JSON", type=["csv", "json"])
        curator_label = st.text_input("Curator label", value="Independent SGSIN curator")
        price_drops = st.number_input("Price (drops)", min_value=1, value=400, step=50)
        if st.button("Register Dataset") and uploaded is not None:
            try:
                response = requests.post(
                    f"{GATEWAY.rstrip('/')}/api/b2c/upload",
                    files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "text/csv")},
                    data={"curator_label": curator_label, "price_drops": int(price_drops)},
                    timeout=60,
                )
                if response.status_code >= 400:
                    st.error(response.text)
                else:
                    st.session_state["b2c"] = response.json()
            except Exception as exc:
                st.error(str(exc))
        listing = st.session_state.get("b2c")
        if listing:
            st.success("Dataset registered")
            st.write(f"**Curator wallet:** `{listing.get('curator_address')}`")
            st.write(f"**x402 route:** `{listing.get('endpoint')}`")
            st.write(f"**Price:** {listing.get('price_drops')} drops")
            st.caption(f"Settlement mode: {listing.get('settlement_mode')}")
        try:
            roy = fetch_royalties()
            rows = roy.get("royalties") or []
            if rows:
                st.markdown("**Micro-royalties**")
                st.dataframe(rows, width="stretch", hide_index=True)
        except Exception as exc:
            st.caption(f"Royalties unavailable: {exc}")
