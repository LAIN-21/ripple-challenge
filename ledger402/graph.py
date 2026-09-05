"""The agentic procurement loop, as a LangGraph state machine.

    understand -> discover -> gather_public -> assess
                                                 |
                                 confidence >= target? -> synthesize -> anchor -> END
                                                 |
                                                rank
                                                 |
                              a candidate is worth buying? -> procure -> assess (cycle)
                                                 |
                                                 no -> synthesize -> anchor -> END

The cycle is the point. The morning MVP could evaluate one provider once; this agent buys
evidence, re-measures its own uncertainty against what arrived, and decides again. It
stops when the objective is met, when nothing left is worth buying, when the budget runs
out, or when it hits the per-run settlement ceiling.

Money is never moved by an LLM. `assess`, `rank`, and the policy gate are deterministic
and unit-tested; `understand` and `synthesize` are the only nodes that call inference, and
both degrade to deterministic behaviour.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Iterator, TypedDict

import requests
from langgraph.graph import END, StateGraph

from ledger402 import audit, classify, confidence as conf, payment, providers, ranking, synthesis, tasks
from ledger402.confidence import EvidenceItem
from ledger402.tasks import TaskSpec

DEFAULT_TARGET_CONFIDENCE = 0.85
DEFAULT_BUDGET_DROPS = 5000

# Hard ceiling on settlements per run. A safety rail, not a tuning knob: it bounds
# worst-case spend even if the confidence model or a provider misbehaves.
DEFAULT_MAX_PURCHASES = 3

PUBLIC_FETCH_TIMEOUT_SECONDS = 15.0


class AgentState(TypedDict, total=False):
    """Everything the loop carries. Serialisable so the UI can render any stage."""

    run_id: str
    question: str
    declared_task_type: str | None
    task_type: str
    subject: str
    classification: dict[str, Any]

    target_confidence: float
    budget_drops: int
    remaining_budget_drops: int
    spent_drops: int
    max_purchases: int

    catalog: list[dict[str, Any]]
    evidence: list[EvidenceItem]
    confidence: float
    initial_confidence: float | None
    iterations: int

    rankings: list[dict[str, Any]]
    purchases: list[dict[str, Any]]
    purchased_ids: list[str]

    report: dict[str, Any]
    audit_anchor: dict[str, Any]
    event_log: list[dict[str, Any]]

    error: str | None
    status_code: int
    stop_reason: str | None

    # A misconfiguration that no further iteration can fix (missing wallet, unresolvable
    # provider URL). Kept separate from stop_reason so a later ranking message cannot
    # bury the one line that tells the operator what to do.
    fatal_error: str | None

    # Hand-off between adjacent nodes. Declared on the schema because LangGraph only
    # persists channels the state type knows about.
    selected_provider_id: str | None
    dossier_summary: str


def _spec(state: AgentState) -> TaskSpec:
    spec = tasks.get_task(state.get("task_type") or "")
    if spec is None:  # pragma: no cover - routing prevents this
        raise RuntimeError(f"No task spec for {state.get('task_type')!r}")
    return spec


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- nodes


def understand(state: AgentState) -> dict[str, Any]:
    """Classify the business question. Fails closed on anything unsupported."""
    log = state["event_log"]
    result = classify.classify(state["question"], state.get("declared_task_type"))
    audit.add(log, "RESEARCH_REQUEST_UNDERSTOOD", **result.to_dict())

    if not result.supported:
        audit.add(log, "TASK_REJECTED", reason=result.rationale)
        return {
            "classification": result.to_dict(),
            "task_type": result.task_type,
            "error": "unsupported_task",
            "status_code": 400,
            "stop_reason": result.rationale,
        }

    subject = result.subject or "the port in question"
    return {
        "classification": result.to_dict(),
        "task_type": result.task_type,
        "subject": subject,
    }


def discover(state: AgentState) -> dict[str, Any]:
    """Find providers serving this task. A real x402 directory would plug in here."""
    catalog = providers.providers_for_category(state["task_type"])
    audit.add(
        state["event_log"],
        "PROVIDERS_DISCOVERED",
        count=len(catalog),
        providers=[
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "price_drops": p.get("price_drops"),
                "payment_required": p.get("payment_required"),
            }
            for p in catalog
        ],
    )
    return {"catalog": catalog}


def gather_public(state: AgentState) -> dict[str, Any]:
    """Fetch every free source before considering a purchase.

    Buying evidence that a free source already provides is the most basic way an agent
    wastes money, so the free tier is always exhausted first.
    """
    log = state["event_log"]
    evidence: list[EvidenceItem] = list(state.get("evidence") or [])

    for provider in state["catalog"]:
        if provider.get("payment_required"):
            continue
        try:
            url = providers.resolve_url(provider)
            response = requests.get(url, timeout=PUBLIC_FETCH_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            # A public source being down is not fatal; the agent can still buy evidence.
            audit.add(
                log,
                "PUBLIC_SOURCE_UNAVAILABLE",
                provider_id=provider.get("id"),
                reason=str(exc),
            )
            continue

        evidence.append(
            EvidenceItem(
                provider_id=str(provider.get("id")),
                provider_name=str(provider.get("name")),
                payload=payload,
                paid=False,
                price_drops=0,
            )
        )
        audit.add(
            log,
            "PUBLIC_SOURCE_QUERIED",
            provider_id=provider.get("id"),
            signals=sorted(tasks.signals_in(payload, _spec(state))),
            synthetic=True,
        )

    return {"evidence": evidence}


def assess(state: AgentState) -> dict[str, Any]:
    """Re-measure confidence against the evidence actually held."""
    spec = _spec(state)
    evidence = state.get("evidence") or []
    current = conf.confidence(evidence, spec)
    target = state["target_confidence"]
    gap = conf.uncertainty_gap(current, target)

    update: dict[str, Any] = {
        "confidence": current,
        "iterations": int(state.get("iterations") or 0) + 1,
    }
    if state.get("initial_confidence") is None:
        update["initial_confidence"] = current

    audit.add(
        state["event_log"],
        "CONFIDENCE_ASSESSED",
        confidence=current,
        target=target,
        uncertainty_gap=gap,
        sources=len(evidence),
        signal_coverage=round(conf.coverage_score(evidence, spec), 4),
    )
    return update


def rank(state: AgentState) -> dict[str, Any]:
    """Rank unpurchased paid providers by confidence bought per drop."""
    spec = _spec(state)
    result = ranking.rank_providers(
        state["catalog"],
        evidence=state.get("evidence") or [],
        spec=spec,
        current_confidence=state["confidence"],
        target_confidence=state["target_confidence"],
        remaining_budget_drops=state["remaining_budget_drops"],
        already_purchased=set(state.get("purchased_ids") or []),
    )
    best = result.best
    audit.add(
        state["event_log"],
        "PROVIDERS_RANKED",
        candidates=result.to_list(),
        selected=best.provider_id if best else None,
    )

    rankings = list(state.get("rankings") or [])
    rankings.append(
        {
            "iteration": state.get("iterations"),
            "confidence_before": state["confidence"],
            "candidates": result.to_list(),
            "selected": best.provider_id if best else None,
        }
    )

    # Always written, never left over: a stale selection from a previous iteration would
    # send the loop back to procure with nothing approved.
    update: dict[str, Any] = {"rankings": rankings, "selected_provider_id": None}
    if best is None:
        update["stop_reason"] = (
            "No remaining provider closes enough of the confidence gap to justify its price."
        )
    else:
        update["selected_provider_id"] = best.provider_id
        audit.add(
            state["event_log"],
            "PURCHASE_APPROVED",
            provider_id=best.provider_id,
            price_drops=best.price_drops,
            reason=best.reason,
        )
    return update


def procure(state: AgentState) -> dict[str, Any]:
    """Execute the approved purchase over x402 and settle on the XRP Ledger."""
    log = state["event_log"]
    selected_id = state.get("selected_provider_id")
    provider = next(
        (p for p in state["catalog"] if str(p.get("id")) == str(selected_id)), None
    )
    if provider is None:  # pragma: no cover - rank always selects from the catalog
        return {"stop_reason": "Selected provider vanished from the catalog."}

    price = int(provider.get("price_drops") or 0)
    purchases = list(state.get("purchases") or [])
    purchased_ids = list(state.get("purchased_ids") or [])
    evidence = list(state.get("evidence") or [])

    def record(status: str, **extra: Any) -> dict[str, Any]:
        entry = {
            "provider_id": str(provider.get("id")),
            "provider_name": str(provider.get("name")),
            "price_drops": price,
            "status": status,
            **extra,
        }
        purchases.append(entry)
        # Mark it purchased either way so a failed provider is not retried in a loop.
        purchased_ids.append(str(provider.get("id")))
        return entry

    try:
        payment.require_wallet_env()
        url = providers.resolve_url(provider)
    except RuntimeError as exc:
        record(payment.CONFIG_ERROR, error=str(exc))
        audit.add(log, "PROCUREMENT_FAILED", provider_id=provider.get("id"), reason=str(exc))
        # Configuration will not repair itself between iterations, and attempting every
        # remaining provider would only bury the actionable message.
        return {
            "purchases": purchases,
            "purchased_ids": purchased_ids,
            "stop_reason": str(exc),
            "fatal_error": str(exc),
        }

    try:
        result = payment.purchase_premium(
            url=url,
            run_id=state["run_id"],
            provider_id=str(provider.get("id")),
            expected_drops=price,
            remaining_budget_drops=state["remaining_budget_drops"],
            log=log,
        )
    except Exception as exc:
        # The transaction may already have been submitted; never retry blindly.
        record(payment.UNKNOWN, error=str(exc))
        audit.add(log, "PROCUREMENT_FAILED", provider_id=provider.get("id"), reason=str(exc))
        return {
            "purchases": purchases,
            "purchased_ids": purchased_ids,
            "stop_reason": f"Procurement failed: {exc}",
        }

    if result.state != payment.SUCCESS or not isinstance(result.body, dict):
        record(
            result.state,
            error=result.error,
            transaction_hash=result.tx_hash,
        )
        audit.add(
            log,
            "PROCUREMENT_FAILED",
            provider_id=provider.get("id"),
            state=result.state,
            reason=result.error,
        )
        return {
            "purchases": purchases,
            "purchased_ids": purchased_ids,
            "stop_reason": result.error or "Procurement did not succeed.",
        }

    record(
        payment.SUCCESS,
        transaction_hash=result.tx_hash,
        explorer_url=(
            payment.EXPLORER_TX.format(hash=result.tx_hash) if result.tx_hash else None
        ),
        network_fee_drops=result.network_fee_drops,
        odrl=result.body.get("odrl"),
    )
    evidence.append(
        EvidenceItem(
            provider_id=str(provider.get("id")),
            provider_name=str(provider.get("name")),
            payload=result.body,
            paid=True,
            price_drops=price,
        )
    )

    # Procurement budget only. The XRPL network fee is tracked separately and never
    # folded into the remaining budget.
    return {
        "purchases": purchases,
        "purchased_ids": purchased_ids,
        "evidence": evidence,
        "spent_drops": int(state.get("spent_drops") or 0) + price,
        "remaining_budget_drops": int(state["remaining_budget_drops"]) - price,
    }


def synthesize(state: AgentState) -> dict[str, Any]:
    """Write the analyst answer from the evidence the agent holds."""
    report = synthesis.synthesize(
        state.get("evidence") or [],
        question=state["question"],
        confidence=state.get("confidence") or 0.0,
        subject=state.get("subject") or "the subject",
    )
    audit.add(
        state["event_log"],
        "REPORT_SYNTHESIZED",
        method=report.method,
        verdict=report.verdict,
        confidence=state.get("confidence"),
    )
    return {"report": report.to_dict(), "dossier_summary": report.dossier_summary()}


def anchor(state: AgentState) -> dict[str, Any]:
    """Commit the composite SHA-256 proof over the run's settlements."""
    tx_hashes = [
        str(p["transaction_hash"])
        for p in state.get("purchases") or []
        if p.get("status") == payment.SUCCESS and p.get("transaction_hash")
    ]
    result = audit.compute_audit_anchor(
        dossier_summary=state.get("dossier_summary") or "",
        tx_hashes=tx_hashes,
    )
    audit.add(
        state["event_log"],
        "AUDIT_ANCHOR_COMPUTED",
        audit_hash=result["audit_hash"],
        settlement_count=result["settlement_count"],
    )
    return {"audit_anchor": result}


# ---------------------------------------------------------------------- routing


def route_after_understand(state: AgentState) -> str:
    return END if state.get("error") else "discover"


def route_after_assess(state: AgentState) -> str:
    """The loop's exit test: objective met, ceiling reached, or budget exhausted."""
    log = state["event_log"]
    if state["confidence"] >= state["target_confidence"]:
        audit.add(
            log,
            "OBJECTIVE_MET",
            confidence=state["confidence"],
            target=state["target_confidence"],
        )
        return "synthesize"

    purchases_made = len(
        [p for p in state.get("purchases") or [] if p.get("status") == payment.SUCCESS]
    )
    if purchases_made >= state["max_purchases"]:
        audit.add(log, "PURCHASE_CEILING_REACHED", max_purchases=state["max_purchases"])
        return "synthesize"

    if state["remaining_budget_drops"] <= 0:
        audit.add(log, "BUDGET_EXHAUSTED", remaining_budget_drops=0)
        return "synthesize"

    return "rank"


def route_after_rank(state: AgentState) -> str:
    return "procure" if state.get("selected_provider_id") else "synthesize"


def route_after_procure(state: AgentState) -> str:
    """A failed purchase returns to assess, which re-tests every exit condition.

    A misconfiguration is the exception: no later iteration can fix it, so the agent
    reports what it has rather than failing against every remaining provider.
    """
    if state.get("fatal_error"):
        audit.add(state["event_log"], "PROCUREMENT_ABORTED", reason=state["fatal_error"])
        return "synthesize"
    return "assess"


def build_graph():
    """Compile the agent. Structure is static, so callers may cache the result."""
    graph = StateGraph(AgentState)

    graph.add_node("understand", understand)
    graph.add_node("discover", discover)
    graph.add_node("gather_public", gather_public)
    graph.add_node("assess", assess)
    graph.add_node("rank", rank)
    graph.add_node("procure", procure)
    graph.add_node("synthesize", synthesize)
    graph.add_node("anchor", anchor)

    graph.set_entry_point("understand")
    graph.add_conditional_edges("understand", route_after_understand, {"discover": "discover", END: END})
    graph.add_edge("discover", "gather_public")
    graph.add_edge("gather_public", "assess")
    graph.add_conditional_edges(
        "assess", route_after_assess, {"rank": "rank", "synthesize": "synthesize"}
    )
    graph.add_conditional_edges(
        "rank", route_after_rank, {"procure": "procure", "synthesize": "synthesize"}
    )
    graph.add_conditional_edges(
        "procure", route_after_procure, {"assess": "assess", "synthesize": "synthesize"}
    )
    graph.add_edge("synthesize", "anchor")
    graph.add_edge("anchor", END)

    return graph.compile()


_compiled = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


# ------------------------------------------------------------------- entry point


def _initial_state(
    *,
    question: str,
    budget_drops: int,
    task_type: str | None,
    run_id: str | None,
    target_confidence: float | None,
    max_purchases: int | None,
) -> AgentState:
    """Build the starting state. Shared by the blocking and streaming entry points."""
    run_id = run_id or str(uuid.uuid4())
    target = (
        float(target_confidence)
        if target_confidence is not None
        else _env_float("LEDGER402_TARGET_CONFIDENCE", DEFAULT_TARGET_CONFIDENCE)
    )
    ceiling = (
        int(max_purchases)
        if max_purchases is not None
        else _env_int("LEDGER402_MAX_PURCHASES", DEFAULT_MAX_PURCHASES)
    )

    return {
        "run_id": run_id,
        "question": question,
        "declared_task_type": task_type,
        "task_type": task_type or tasks.PORT_CONGESTION,
        "subject": "",
        "target_confidence": max(0.0, min(1.0, target)),
        "budget_drops": int(budget_drops),
        "remaining_budget_drops": int(budget_drops),
        "spent_drops": 0,
        "max_purchases": max(0, ceiling),
        "catalog": [],
        "evidence": [],
        "confidence": 0.0,
        "initial_confidence": None,
        "iterations": 0,
        "rankings": [],
        "purchases": [],
        "purchased_ids": [],
        "event_log": audit.new_log(),
        "error": None,
        "status_code": 200,
        "stop_reason": None,
        "fatal_error": None,
    }


def _run_config(state: AgentState) -> dict[str, Any]:
    """recursion_limit bounds LangGraph's own step count; the agent's real spend ceiling
    is max_purchases. Each purchase costs roughly three graph steps."""
    return {"recursion_limit": 8 + int(state.get("max_purchases") or 0) * 4}


def run_agent(
    *,
    question: str,
    budget_drops: int = DEFAULT_BUDGET_DROPS,
    task_type: str | None = None,
    run_id: str | None = None,
    target_confidence: float | None = None,
    max_purchases: int | None = None,
) -> dict[str, Any]:
    """Run one research objective end to end and return a serialisable result."""
    initial = _initial_state(
        question=question,
        budget_drops=budget_drops,
        task_type=task_type,
        run_id=run_id,
        target_confidence=target_confidence,
        max_purchases=max_purchases,
    )
    final = get_graph().invoke(initial, _run_config(initial))
    return _serialize(final)


def progress_snapshot(state: AgentState) -> dict[str, Any]:
    """The few numbers a live view needs to redraw its gauges between events."""
    successful = [
        p for p in state.get("purchases") or [] if p.get("status") == payment.SUCCESS
    ]
    return {
        "confidence": state.get("confidence") or 0.0,
        "initial_confidence": state.get("initial_confidence"),
        "target_confidence": state.get("target_confidence") or 0.0,
        "iterations": state.get("iterations") or 0,
        "budget_drops": state.get("budget_drops") or 0,
        "spent_drops": state.get("spent_drops") or 0,
        "remaining_budget_drops": state.get("remaining_budget_drops") or 0,
        "settlement_count": len(successful),
        "evidence_count": len(state.get("evidence") or []),
        "latest_ranking": (state.get("rankings") or [None])[-1],
    }


def stream_agent(
    *,
    question: str,
    budget_drops: int = DEFAULT_BUDGET_DROPS,
    task_type: str | None = None,
    run_id: str | None = None,
    target_confidence: float | None = None,
    max_purchases: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Run one objective, yielding each audit event as the agent produces it.

    Emits `{"kind": "event"}` per audit entry, then one `{"kind": "result"}` carrying the
    same payload `run_agent` returns. A live view can therefore animate the run and still
    end up with the complete result.

    LangGraph streams state after each super-step rather than after each audit entry, so
    the event log is diffed against what has already been emitted. Every event reaches the
    client exactly once, in order.
    """
    initial = _initial_state(
        question=question,
        budget_drops=budget_drops,
        task_type=task_type,
        run_id=run_id,
        target_confidence=target_confidence,
        max_purchases=max_purchases,
    )
    yield {
        "kind": "start",
        "run_id": initial["run_id"],
        "question": question,
        "snapshot": progress_snapshot(initial),
    }

    emitted = 0
    last_state: AgentState = initial
    try:
        for state in get_graph().stream(
            initial, _run_config(initial), stream_mode="values"
        ):
            last_state = state
            log = state.get("event_log") or []
            snapshot = progress_snapshot(state)
            while emitted < len(log):
                yield {"kind": "event", "index": emitted, "event": log[emitted], "snapshot": snapshot}
                emitted += 1
    except Exception as exc:
        # A crashed run must still close the stream cleanly, or the view hangs forever.
        yield {"kind": "error", "reason": str(exc)}
        return

    yield {"kind": "result", "result": _serialize(last_state)}


def _serialize(state: AgentState) -> dict[str, Any]:
    """Flatten the graph state into the API response."""
    if state.get("error"):
        return {
            "run_id": state.get("run_id"),
            "question": state.get("question"),
            "error": state.get("error"),
            "status_code": state.get("status_code", 400),
            "reason": state.get("stop_reason"),
            "classification": state.get("classification"),
            "event_log": state.get("event_log", []),
        }

    successful = [
        p for p in state.get("purchases") or [] if p.get("status") == payment.SUCCESS
    ]
    initial_confidence = state.get("initial_confidence")

    return {
        "run_id": state.get("run_id"),
        "question": state.get("question"),
        "task_type": state.get("task_type"),
        "subject": state.get("subject"),
        "classification": state.get("classification"),
        "target_confidence": state.get("target_confidence"),
        "initial_confidence": initial_confidence,
        "final_confidence": state.get("confidence"),
        "objective_met": (state.get("confidence") or 0.0) >= (state.get("target_confidence") or 0.0),
        "iterations": state.get("iterations"),
        "stop_reason": state.get("fatal_error") or state.get("stop_reason"),
        "configuration_error": state.get("fatal_error"),
        "providers_considered": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "price_drops": p.get("price_drops"),
                "payment_required": p.get("payment_required"),
            }
            for p in state.get("catalog") or []
        ],
        "rankings": state.get("rankings", []),
        "purchases": state.get("purchases", []),
        "transaction_hashes": [p.get("transaction_hash") for p in successful],
        "settlement_count": len(successful),
        "budget_drops": state.get("budget_drops"),
        "spent_drops": state.get("spent_drops", 0),
        "remaining_budget_drops": state.get("remaining_budget_drops"),
        "evidence": [
            {
                "provider_id": item.provider_id,
                "provider_name": item.provider_name,
                "paid": item.paid,
                "price_drops": item.price_drops,
                "payload": item.payload,
            }
            for item in state.get("evidence") or []
        ],
        "report": state.get("report"),
        "audit_anchor": state.get("audit_anchor"),
        "event_log": state.get("event_log", []),
        "synthetic": True,
    }
