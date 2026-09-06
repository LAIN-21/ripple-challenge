"""View-only Streamlit pacing and decision-graph painting."""

from __future__ import annotations

from apps.ui.flow_graph import (
    MONEY,
    graph_html,
    live_metrics,
    next_revealed,
    node_of,
    paint_state,
)


def test_invoice_and_core_events_map_to_nodes():
    assert node_of("RESEARCH_REQUEST_UNDERSTOOD") == "understand"
    assert node_of("PROVIDERS_DISCOVERED") == "discover"
    assert node_of("PUBLIC_SOURCE_QUERIED") == "gather_public"
    assert node_of("CONFIDENCE_ASSESSED") == "assess"
    assert node_of("PROVIDERS_RANKED") == "rank"
    assert node_of("HTTP_402_OBSERVED") == "procure"
    assert node_of("REPORT_SYNTHESIZED") == "synthesize"
    assert node_of("AUDIT_ANCHOR_COMPUTED") == "anchor"
    assert node_of("PROCUREMENT_INVOICE_GENERATED") == "anchor"


def test_procure_handshake_events_are_money():
    for event_type in (
        "HTTP_402_OBSERVED",
        "X402_PAYMENT_NEGOTIATION_STARTED",
        "XRPL_PAYMENT_CONFIRMED",
        "PREMIUM_RESOURCE_UNLOCKED",
    ):
        assert event_type in MONEY
        assert node_of(event_type) == "procure"


def test_paint_walks_the_main_path_and_lights_the_edge():
    events = [
        {"type": "RESEARCH_REQUEST_UNDERSTOOD"},
        {"type": "PROVIDERS_DISCOVERED"},
        {"type": "HTTP_402_OBSERVED"},
    ]
    paint = paint_state(events)
    assert paint.visited == frozenset({"understand", "discover"})
    assert paint.active == "procure"
    assert paint.money is True
    assert paint.lit_edge == "discover-procure"


def test_finished_run_marks_the_active_node_visited():
    paint = paint_state([{"type": "PROCUREMENT_INVOICE_GENERATED"}], finished=True)
    assert paint.active is None
    assert "anchor" in paint.visited
    assert paint.money is False


def test_reveal_cursor_never_dumps_a_burst():
    run_id, revealed = next_revealed("run-1", 20, None, 0)
    assert run_id == "run-1"
    assert revealed == 2  # 20 behind > 12, step 2
    assert revealed < 20

    run_id, revealed = next_revealed("run-1", 20, "run-1", 2)
    assert revealed == 4

    run_id, revealed = next_revealed("run-1", 10, "run-1", 8)
    assert revealed == 9  # 2 behind, step 1


def test_new_run_id_resets_the_cursor():
    run_id, revealed = next_revealed("run-2", 8, "run-1", 8)
    assert run_id == "run-2"
    assert revealed == 1


def test_idle_has_nothing_to_reveal():
    run_id, revealed = next_revealed(None, 5, "run-1", 5)
    assert run_id is None
    assert revealed == 0


def test_live_metrics_follow_revealed_events_only():
    events = [
        {"type": "CONFIDENCE_ASSESSED", "detail": {"confidence": 0.58}},
        {"type": "XRPL_PAYMENT_CONFIRMED", "detail": {"price_drops": 1200}},
        {"type": "CONFIDENCE_ASSESSED", "detail": {"confidence": 0.87}},
    ]
    partial = live_metrics(events[:1])
    assert round(partial["confidence"], 2) == 0.58
    assert partial["settlements"] == 0
    full = live_metrics(events)
    assert round(full["confidence"], 2) == 0.87
    assert full["settlements"] == 1
    assert full["spent_drops"] == 1200


def test_graph_html_marks_the_active_node():
    html = graph_html([{"type": "PROVIDERS_DISCOVERED"}])
    assert 'data-node="discover"' in html
    assert 'class="node active"' in html
    invoice_html = graph_html([{"type": "PROCUREMENT_INVOICE_GENERATED"}])
    assert 'data-node="anchor"' in invoice_html
    assert 'class="node active"' in invoice_html
