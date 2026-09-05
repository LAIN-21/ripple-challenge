"""Shared run bus: chat starts once, Streamlit and chat both watch."""

from __future__ import annotations

import json
import threading

from fastapi.testclient import TestClient

from ledger402 import run_bus
from tests.test_graph import (
    QUESTION,
    free_provider_up,  # noqa: F401 - fixture
    paying_agent,  # noqa: F401 - fixture
)


def client(paying_agent):  # noqa: F811
    from apps.orchestrator.main import app

    return TestClient(app)


def test_start_and_watch_see_the_same_events(paying_agent):  # noqa: F811
    http = client(paying_agent)
    started = http.post(
        "/research/start",
        json={"question": QUESTION, "target_confidence": 0.85},
    )
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    with http.stream("GET", "/research/watch", params={"run_id": run_id}) as response:
        assert response.status_code == 200
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
    assert messages[0]["run_id"] == run_id

    snap = http.get("/research/active").json()
    assert snap["status"] == "done"
    assert snap["run_id"] == run_id
    assert snap["result"]["settlement_count"] == 1
    assert snap["result"]["run_id"] == run_id


def test_second_start_while_running_is_conflict(monkeypatch):
    from apps.orchestrator.main import app

    started = threading.Event()
    release = threading.Event()

    def blocked_stream(**kwargs):
        started.set()
        release.wait(timeout=5)
        yield {"kind": "start", "run_id": kwargs.get("run_id"), "question": kwargs["question"]}
        yield {"kind": "result", "result": {"run_id": kwargs.get("run_id")}}

    monkeypatch.setattr(run_bus, "stream_agent", blocked_stream)
    http = TestClient(app)
    first = http.post("/research/start", json={"question": QUESTION})
    assert first.status_code == 200
    assert started.wait(timeout=2)

    second = http.post("/research/start", json={"question": QUESTION})
    assert second.status_code == 409

    release.set()
    with http.stream("GET", "/research/watch", params={"run_id": first.json()["run_id"]}):
        pass


def test_watch_unknown_run_is_not_found(paying_agent):  # noqa: F811
    http = client(paying_agent)
    response = http.get("/research/watch", params={"run_id": "does-not-exist"})
    assert response.status_code == 404


def test_active_idle_when_nothing_has_run():
    from apps.orchestrator.main import app

    snap = TestClient(app).get("/research/active").json()
    assert snap["status"] == "idle"
    assert snap["run_id"] is None
    assert snap["result"] is None


def test_chat_page_is_served():
    from apps.chat.main import app

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Assistant" in response.text
    assert "/research/start" in response.text
    assert "testnet.xrpl.org/transactions/" in response.text
    assert 'id="invoice-nav"' in response.text
    assert "Download invoice JSON" in response.text
    assert "bindInvoiceDownloads" in response.text
