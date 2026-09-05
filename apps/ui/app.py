"""Ledger402 three-panel clearinghouse dashboard."""

from __future__ import annotations

import json
import os

import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components

from apps.ui.flow_graph import graph_html, live_metrics, next_revealed

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
    "PROCUREMENT_INVOICE_GENERATED": "Institutional invoice generated",
}

AUDIT_MEMO_TYPE_HEX = "6C65646765723430323A6175646974"
LOG_EXTRAS = ("reason", "tx_hash", "price_drops", "status_code")

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


def event_clock(event: dict) -> str:
    at = str(event.get("at") or "")
    if "T" in at:
        return at.split("T", 1)[1][:8]
    return at[-8:] if len(at) >= 8 else at


def format_event_line(event: dict) -> str:
    label = EVENT_LABELS.get(event.get("type"), event.get("type") or "event")
    detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
    extras = [
        f"{key}={detail[key]}"
        for key in LOG_EXTRAS
        if detail.get(key) not in (None, "")
    ]
    suffix = f" · {' · '.join(extras)}" if extras else ""
    return f"{event_clock(event)} · {label}{suffix}"


def render_live_log(events: list[dict], *, limit: int | None = 8) -> None:
    visible = events[-limit:] if limit else events
    if not visible:
        st.caption("Execution trace appears here after a run.")
        return
    st.markdown("\n".join(f"- `{format_event_line(event)}`" for event in visible))


def render_invoice(invoice: dict, result: dict) -> None:
    st.subheader(f"Procurement invoice (`{invoice.get('invoice_id')}`)")
    st.caption(f"Generated {invoice.get('generated_at') or '—'}")
    line_items = invoice.get("line_items") or []
    if not line_items:
        st.info("No on-ledger settlement this run (public-only).")

    for item in line_items:
        amount = item.get("amount_paid") or {}
        tx = item.get("tx_hash")
        pay_to = item.get("seller_address") or "n/a"
        explorer = item.get("tx_explorer_url") or (EXPLORER_TX.format(hash=tx) if tx else None)
        with st.container(border=True):
            st.markdown(f"**{item.get('vendor_name') or item.get('provider_id')}** — {amount.get('drops', 0)} drops")
            st.caption(f"Seller `pay_to`: `{pay_to}`")
            if tx and explorer:
                st.markdown(f"Tx hash: [`{tx}`]({explorer})")
            elif tx:
                st.code(tx, language=None)
            else:
                st.caption("No transaction hash on this line.")

    summary = invoice.get("financial_summary") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Data cost (settled)", f"{summary.get('total_drops_spent', 0)} drops")
    c2.metric("Network fee (settled)", f"{summary.get('total_network_fee_drops', 0)} drops")
    c3.metric("Protocol take 2.5%", f"{summary.get('protocol_fee_drops', 0)} drops")
    st.caption(
        f"Net settlement **{summary.get('net_settlement_drops', 0)} drops** "
        "(data cost + network fee). Protocol take is disclosed, not collected on-ledger."
    )

    invoice_json = invoice.get("json") or json.dumps(invoice, indent=2, default=str)
    dc1, dc2 = st.columns(2)
    with dc1:
        st.download_button(
            "Download invoice JSON",
            data=invoice_json,
            file_name=f"Invoice_{result.get('run_id')}.json",
            mime="application/json",
        )
    with dc2:
        st.download_button(
            "Download invoice Markdown",
            data=invoice.get("markdown") or "",
            file_name=f"Invoice_{result.get('run_id')}.md",
            mime="text/markdown",
        )


def run_stream(payload: dict, log_box=None):
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
                if log_box is not None:
                    with log_box.container():
                        render_live_log(events, limit=8)
            elif kind == "result":
                result = chunk.get("result")
            elif kind == "error":
                error = chunk.get("reason")
    return events, result, error


def fetch_active() -> dict:
    try:
        response = requests.get(f"{ORCH.rstrip('/')}/research/active", timeout=2)
        response.raise_for_status()
        return response.json()
    except Exception:
        return {
            "status": "idle",
            "run_id": None,
            "question": None,
            "events": [],
            "result": None,
            "error": None,
        }


STATUS_LABELS = {
    "idle": "Waiting for chat",
    "running": "Running",
    "done": "Done",
    "error": "Failed",
}


def reveal_events(run_id: str | None, events: list[dict]) -> list[dict]:
    prev_run = st.session_state.get("live_run_id")
    prev_n = int(st.session_state.get("live_revealed") or 0)
    run_id, revealed = next_revealed(run_id, len(events), prev_run, prev_n)
    st.session_state["live_run_id"] = run_id
    st.session_state["live_revealed"] = revealed
    return events[:revealed]


def observer_events(snap: dict) -> tuple[str | None, list[dict], dict | None, str]:
    status = snap.get("status") or "idle"
    if status in {"running", "done", "error"}:
        result = snap.get("result")
        events = snap.get("events") or []
        return snap.get("run_id"), events, result, status
    result = st.session_state.get("result")
    events = st.session_state.get("events") or (result.get("event_log") if result else []) or []
    run_id = (result or {}).get("run_id") or ("advanced" if events else None)
    derived = "done" if result else ("running" if events else "idle")
    return run_id, events, result, derived

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
    "unless Offline Replay Mode is checked. Send the prompt from the chat at http://localhost:8600 "
    "— this dashboard follows that run."
)

left, center, right = st.columns([1.1, 2.0, 1.3])


@st.fragment(run_every=1)
def directive_panel():
    snap = fetch_active()
    status = snap.get("status") or "idle"
    st.subheader("Directive")
    st.info(STATUS_LABELS.get(status, status))
    observed_question = snap.get("question") or ""
    if observed_question:
        st.write(observed_question)
    else:
        st.caption("Waiting for a prompt from the chat interface.")
    with st.expander("Advanced"):
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
        replay = st.checkbox("Use Offline Replay Mode", value=False)
        budget = st.number_input("Procurement budget (drops)", min_value=0, value=5000, step=100)
        max_purchases = st.number_input(
            "Max settlements per run", min_value=0, max_value=5, value=3, step=1
        )
        delivery_tier = "tier_1" if tier_label.startswith("Tier 1") else "tier_2"
        if st.button("Run research", type="primary"):
            st.session_state.pop("error", None)
            st.session_state.pop("result", None)
            st.session_state.pop("tier", None)
            st.session_state.pop("events", None)
            st.session_state.pop("live_run_id", None)
            st.session_state.pop("live_revealed", None)
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
                st.session_state["events"] = _events
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
    if snap.get("error") and not snap.get("result"):
        st.session_state["error"] = snap["error"]


@st.fragment(run_every=1)
def deliverable_panel():
    snap = fetch_active()
    _run_id, _events, result, status = observer_events(snap)
    active_tier = (result or {}).get("delivery_tier") or st.session_state.get("tier") or "tier_1"
    st.subheader("Deliverable")
    if not result:
        if status == "running":
            st.write("Agent is procuring. Execution updates on the right.")
        else:
            st.write("Send a prompt from the chat to render the dossier.")
        return
    if result.get("error"):
        st.warning(result.get("reason") or result.get("error"))
        return
    if active_tier == "tier_2" or result.get("delivery_tier") == "tier_2":
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
            st.info(
                f"Yard utilization is {yard:.0%}, above the 85% threshold used for a high-congestion reading."
            )
        chart_a, chart_b = st.columns(2)
        with chart_a:
            if berth is not None and yard is not None:
                fig = go.Figure(
                    go.Bar(
                        x=["Berth occupancy", "Yard utilization"],
                        y=[berth * 100, yard * 100],
                        marker_color=["#1565C0", "#EF6C00"],
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
        markdown_text = advisory_markdown(result)
        st.download_button(
            "Download Advisory Dossier",
            data=markdown_text,
            file_name="Ledger402_Advisory_Dossier.md",
            mime="text/markdown",
        )

    invoice = result.get("invoice") if not result.get("error") else None
    if invoice:
        render_invoice(invoice, result)
    elif not result.get("error"):
        st.info("No on-ledger settlement this run (public-only).")


@st.fragment(run_every=0.4)
def execution_panel():
    snap = fetch_active()
    run_id, events, result, status = observer_events(snap)
    visible = reveal_events(run_id, events)
    caught_up = bool(events) and len(visible) >= len(events)
    finished = status in {"done", "error"} and caught_up
    gauges = live_metrics(visible)
    st.subheader("Execution")
    m1, m2 = st.columns(2)
    m1.metric("Confidence", f"{gauges['confidence']:.1%}" if gauges["confidence"] else "—")
    m2.metric("Settlements", int(gauges["settlements"]))
    components.html(graph_html(visible, finished=finished), height=580, scrolling=False)
    render_live_log(visible, limit=None)


@st.fragment(run_every=1)
def engine_panel():
    snap = fetch_active()
    _run_id, _events, result, _status = observer_events(snap)
    with st.expander("B2C marketplace and XRPL engine"):
        st.caption("Native XRPL primitives backing this settlement layer.")
        st.success("Primitive: Payment with Atomic Memo")
        funding_asset = (result or {}).get("funding_asset", "XRP") if result else "XRP"
        if funding_asset == "RLUSD":
            st.info("DEX Auto-Bridge: RLUSD → XRP Pathfinding — ACTIVE this run")
        else:
            st.info("DEX Auto-Bridge: RLUSD → XRP Pathfinding — available (funded in XRP this run)")
        st.caption("Consensus speed: ~3.4s (XRPL Testnet close time)")

        line_items = ((result or {}).get("invoice") or {}).get("line_items") or [] if result else []
        proven = [item for item in line_items if item.get("memo_proof")]
        if proven:
            st.markdown("**On-ledger audit memo, decoded**")
            for item in proven:
                with st.container(border=True):
                    st.write(f"`{item.get('vendor_name')}`")
                    st.code(
                        "MemoType (hex):  " + AUDIT_MEMO_TYPE_HEX + "\n"
                        "Decoded:         ledger402:audit\n"
                        f"MemoData (hex):  {item['memo_proof']}\n"
                        "Decoded:         SHA-256(requested payload spec) — atomic "
                        "proof of what this settlement paid for",
                        language=None,
                    )
        else:
            st.caption("The decoded audit memo appears here once a purchase settles.")

        st.divider()
        st.markdown("**B2C marketplace**")
        uploaded = st.file_uploader("Curator CSV / JSON", type=["csv", "json"])
        curator_label = st.text_input("Curator label", value="Independent SGSIN curator")
        price_drops = st.number_input("Price (drops)", min_value=1, value=400, step=50, key="b2c_price")
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


with left:
    directive_panel()
with center:
    deliverable_panel()
with right:
    execution_panel()
    engine_panel()
