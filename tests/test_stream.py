"""Streaming: the live view must see every step, once, in order."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ledger402 import graph, payment
from tests.test_graph import (
    QUESTION,
    SATELLITE_PAYLOAD,
    TELEMETRY_PAYLOAD,
    free_provider_up,  # noqa: F401 - fixture
    paying_agent,  # noqa: F401 - fixture
)


def test_stream_emits_start_events_and_result(paying_agent):  # noqa: F811
    chunks = list(graph.stream_agent(question=QUESTION, budget_drops=5000, target_confidence=0.85))

    assert chunks[0]["kind"] == "start"
    assert chunks[-1]["kind"] == "result"
    assert all(c["kind"] == "event" for c in chunks[1:-1])


def test_every_event_is_emitted_exactly_once_and_in_order(paying_agent):  # noqa: F811
    chunks = list(graph.stream_agent(question=QUESTION, budget_drops=5000, target_confidence=0.92))
    events = [c for c in chunks if c["kind"] == "event"]

    # Indices are contiguous from zero: nothing dropped, nothing repeated.
    assert [c["index"] for c in events] == list(range(len(events)))

    streamed = [c["event"] for c in events]
    final_log = chunks[-1]["result"]["event_log"]
    assert streamed == final_log


def test_stream_result_matches_the_blocking_run(paying_agent):  # noqa: F811
    """The live view and the dashboard must not disagree about what happened."""
    streamed = list(
        graph.stream_agent(question=QUESTION, budget_drops=5000, target_confidence=0.85, run_id="a")
    )[-1]["result"]
    payment.reset_cache()
    blocking = graph.run_agent(
        question=QUESTION, budget_drops=5000, target_confidence=0.85, run_id="b"
    )

    for field in ("settlement_count", "spent_drops", "remaining_budget_drops", "objective_met"):
        assert streamed[field] == blocking[field], field
    assert round(streamed["final_confidence"], 4) == round(blocking["final_confidence"], 4)


def test_snapshot_tracks_spending_as_it_happens(free_provider_up, settling_agent):  # noqa: F811
    """Uses the faithful payment mock so the payment-internal events are really emitted.
    Per-event snapshot timing is covered in detail by tests/test_stream_pacing.py."""
    chunks = list(graph.stream_agent(question=QUESTION, budget_drops=5000, target_confidence=0.92))
    spent = [c["snapshot"]["spent_drops"] for c in chunks if c["kind"] == "event"]

    assert spent[0] == 0
    assert spent[-1] == 1800
    # Spending only ever goes up: a live gauge must never jump backwards.
    assert spent == sorted(spent)


def test_stream_of_a_rejected_objective_still_terminates(free_provider_up):  # noqa: F811
    chunks = list(graph.stream_agent(question="Should we enter the Japanese market?"))
    assert chunks[-1]["kind"] == "result"
    assert chunks[-1]["result"]["error"] == "unsupported_task"


def test_stream_reports_a_crash_instead_of_hanging(monkeypatch, free_provider_up):  # noqa: F811
    def boom(state):
        raise RuntimeError("node exploded")

    monkeypatch.setattr(graph, "_compiled", None)
    monkeypatch.setattr(graph, "discover", boom)
    chunks = list(graph.stream_agent(question=QUESTION))
    graph._compiled = None

    assert chunks[-1]["kind"] == "error"
    assert "node exploded" in chunks[-1]["reason"]


# ------------------------------------------------------------------ HTTP surface


@pytest.fixture
def client(monkeypatch, paying_agent):  # noqa: F811
    from apps.orchestrator.main import app

    return TestClient(app)


def test_sse_endpoint_streams_events(client):
    with client.stream(
        "GET", "/research/stream", params={"question": QUESTION, "target_confidence": 0.85}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    messages = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    kinds = [m["kind"] for m in messages]
    assert kinds[0] == "start"
    assert kinds[-1] == "result"
    assert "event" in kinds


def test_live_page_is_served(client):
    response = client.get("/live")
    assert response.status_code == 200
    assert "Ledger402" in response.text
    # The page drives itself from the stream; a missing EventSource means a dead page.
    assert "EventSource" in response.text


def test_capabilities_endpoint(client):
    body = client.get("/capabilities").json()
    assert body["supported_task_types"] == ["port_congestion"]
    assert body["llm_enabled"] is False
