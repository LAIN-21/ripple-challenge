"""View-only decision graph and log pacing for the Streamlit observer.

Does not run the agent or spend. It paints already-emitted audit events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

NODE_OF = {
    "RESEARCH_REQUEST_UNDERSTOOD": "understand",
    "TASK_REJECTED": "understand",
    "PROVIDERS_DISCOVERED": "discover",
    "PUBLIC_SOURCE_QUERIED": "gather_public",
    "PUBLIC_SOURCE_UNAVAILABLE": "gather_public",
    "CONFIDENCE_ASSESSED": "assess",
    "OBJECTIVE_MET": "assess",
    "PURCHASE_CEILING_REACHED": "assess",
    "BUDGET_EXHAUSTED": "assess",
    "PROVIDERS_RANKED": "rank",
    "PURCHASE_APPROVED": "rank",
    "HTTP_402_OBSERVED": "procure",
    "X402_PAYMENT_NEGOTIATION_STARTED": "procure",
    "XRPL_PAYMENT_CONFIRMED": "procure",
    "PREMIUM_RESOURCE_UNLOCKED": "procure",
    "PROCUREMENT_FAILED": "procure",
    "PROCUREMENT_ABORTED": "procure",
    "REPORT_SYNTHESIZED": "synthesize",
    "AUDIT_ANCHOR_COMPUTED": "anchor",
    "PROCUREMENT_INVOICE_GENERATED": "anchor",
}

MONEY = frozenset(
    {
        "HTTP_402_OBSERVED",
        "X402_PAYMENT_NEGOTIATION_STARTED",
        "XRPL_PAYMENT_CONFIRMED",
        "PREMIUM_RESOURCE_UNLOCKED",
    }
)

NODES = (
    "understand",
    "discover",
    "gather_public",
    "assess",
    "rank",
    "procure",
    "synthesize",
    "anchor",
)

CATCH_UP_BEHIND = 12


def node_of(event_type: str | None) -> str | None:
    if not event_type:
        return None
    return NODE_OF.get(str(event_type))


def is_money_event(event_type: str | None) -> bool:
    return str(event_type or "") in MONEY


def next_revealed(
    run_id: str | None,
    event_count: int,
    prev_run_id: str | None,
    prev_revealed: int,
) -> tuple[str | None, int]:
    """Advance the playback cursor by one event (two if far behind). Never dump."""
    if not run_id:
        return None, 0
    revealed = 0 if run_id != prev_run_id else max(0, int(prev_revealed))
    remaining = max(0, int(event_count) - revealed)
    if remaining <= 0:
        return run_id, min(revealed, int(event_count))
    step = 2 if remaining > CATCH_UP_BEHIND else 1
    return run_id, revealed + step


def live_metrics(events: Iterable[dict[str, Any]]) -> dict[str, float | int]:
    confidence = 0.0
    settlements = 0
    spent = 0
    for event in events:
        event_type = event.get("type")
        detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
        if event_type == "CONFIDENCE_ASSESSED":
            confidence = float(detail.get("confidence") or confidence)
        elif event_type == "XRPL_PAYMENT_CONFIRMED":
            settlements += 1
            spent += int(detail.get("price_drops") or 0)
    return {
        "confidence": confidence,
        "settlements": settlements,
        "spent_drops": spent,
    }


@dataclass(frozen=True)
class GraphPaint:
    visited: frozenset[str]
    active: str | None
    money: bool
    lit_edge: str | None


def paint_state(events: Iterable[dict[str, Any]], *, finished: bool = False) -> GraphPaint:
    visited: set[str] = set()
    active: str | None = None
    money = False
    lit_edge: str | None = None
    for event in events:
        event_type = str(event.get("type") or "")
        node = NODE_OF.get(event_type)
        if not node:
            continue
        if active and active != node:
            visited.add(active)
            lit_edge = f"{active}-{node}"
        active = node
        money = event_type in MONEY
    if finished and active:
        visited.add(active)
        return GraphPaint(visited=frozenset(visited), active=None, money=False, lit_edge=lit_edge)
    return GraphPaint(visited=frozenset(visited), active=active, money=money, lit_edge=lit_edge)


def graph_html(events: Iterable[dict[str, Any]], *, finished: bool = False) -> str:
    paint = paint_state(events, finished=finished)
    node_class = {}
    for name in NODES:
        classes = ["node"]
        if name in paint.visited:
            classes.append("visited")
        if name == paint.active:
            classes.append("money" if paint.money else "active")
        node_class[name] = " ".join(classes)

    def edge_class(edge_id: str, extra: str = "") -> str:
        bits = ["edge"]
        if extra:
            bits.append(extra)
        if paint.lit_edge == edge_id:
            bits.append("lit")
        return " ".join(bits)

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; background: #ffffff; color: #31333f;
    font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  .node rect {{ fill: #ffffff; stroke: #d6d6d8; stroke-width: 1.5; }}
  .node text {{ fill: #31333f; font-size: 13px; font-family: ui-monospace, Menlo, monospace; }}
  .node.visited rect {{ stroke: #b0b3b8; fill: #f0f2f6; }}
  .node.visited text {{ fill: #31333f; }}
  .node.active rect {{
    stroke: #ff4b4b; fill: #fff5f5; stroke-width: 2.5;
  }}
  .node.active text {{ fill: #31333f; }}
  .node.money rect {{
    stroke: #c48a00; fill: #fffaf0; stroke-width: 2.5;
  }}
  .node.money text {{ fill: #31333f; }}
  .edge {{ stroke: #d6d6d8; stroke-width: 1.5; fill: none; marker-end: url(#flow-arrow); }}
  .edge.lit {{ stroke: #ff4b4b; marker-end: url(#flow-arrow-lit); }}
  .edge.cycle {{ stroke-dasharray: 5 4; }}
  .edge-label {{ fill: #808495; font-size: 10px; font-family: ui-monospace, Menlo, monospace; }}
</style></head>
<body>
<svg viewBox="0 0 430 600" style="width:100%;max-height:540px;height:auto">
  <defs>
    <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#d6d6d8"/>
    </marker>
    <marker id="flow-arrow-lit" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#ff4b4b"/>
    </marker>
  </defs>
  <path class="{edge_class("understand-discover")}" data-edge="understand-discover" d="M150,72 L150,100"/>
  <path class="{edge_class("discover-gather_public")}" data-edge="discover-gather_public" d="M150,146 L150,174"/>
  <path class="{edge_class("gather_public-assess")}" data-edge="gather_public-assess" d="M150,220 L150,252"/>
  <path class="{edge_class("assess-rank")}" data-edge="assess-rank" d="M150,298 L150,340"/>
  <path class="{edge_class("rank-procure")}" data-edge="rank-procure" d="M150,386 L150,428"/>
  <path class="{edge_class("procure-assess", "cycle")}" data-edge="procure-assess" d="M96,451 L40,451 L40,275 L94,275"/>
  <path class="{edge_class("assess-synthesize")}" data-edge="assess-synthesize" d="M206,275 L300,275 L300,320"/>
  <path class="{edge_class("rank-synthesize")}" data-edge="rank-synthesize" d="M206,363 L300,363"/>
  <path class="{edge_class("synthesize-anchor")}" data-edge="synthesize-anchor" d="M330,386 L330,428"/>
  <path class="{edge_class("procure-synthesize", "cycle")}" data-edge="procure-synthesize" d="M206,451 L238,451 L238,404 L282,404 L282,370"/>
  <text class="edge-label" x="8" y="365" transform="rotate(-90 8 365)">buy again</text>
  <text class="edge-label" x="228" y="268">target met</text>
  <text class="edge-label" x="212" y="357">nothing worth buying</text>
  <g class="{node_class["understand"]}" data-node="understand">
    <rect x="94" y="26" width="112" height="46" rx="9"/>
    <text x="150" y="54" text-anchor="middle">understand</text>
  </g>
  <g class="{node_class["discover"]}" data-node="discover">
    <rect x="94" y="100" width="112" height="46" rx="9"/>
    <text x="150" y="128" text-anchor="middle">discover</text>
  </g>
  <g class="{node_class["gather_public"]}" data-node="gather_public">
    <rect x="82" y="174" width="136" height="46" rx="9"/>
    <text x="150" y="202" text-anchor="middle">gather_public</text>
  </g>
  <g class="{node_class["assess"]}" data-node="assess">
    <rect x="94" y="252" width="112" height="46" rx="9"/>
    <text x="150" y="280" text-anchor="middle">assess</text>
  </g>
  <g class="{node_class["rank"]}" data-node="rank">
    <rect x="94" y="340" width="112" height="46" rx="9"/>
    <text x="150" y="368" text-anchor="middle">rank</text>
  </g>
  <g class="{node_class["procure"]}" data-node="procure">
    <rect x="94" y="428" width="112" height="46" rx="9"/>
    <text x="150" y="456" text-anchor="middle">procure</text>
  </g>
  <g class="{node_class["synthesize"]}" data-node="synthesize">
    <rect x="266" y="320" width="128" height="46" rx="9"/>
    <text x="330" y="348" text-anchor="middle">synthesize</text>
  </g>
  <g class="{node_class["anchor"]}" data-node="anchor">
    <rect x="274" y="428" width="112" height="46" rx="9"/>
    <text x="330" y="456" text-anchor="middle">anchor</text>
  </g>
  <text class="edge-label" x="150" y="530" text-anchor="middle">procure → assess → rank → procure is the loop</text>
  <text class="edge-label" x="150" y="550" text-anchor="middle">the agent re-measures uncertainty after every purchase</text>
  <text class="edge-label" x="150" y="576" text-anchor="middle">highlighted = real money moving on the XRP Ledger</text>
</svg>
</body></html>
"""
