"""One in-process research run that chat and Streamlit can both watch.

`GET /research/stream` still starts a private run for tests and `/live`. Chat uses
`start()` so the dashboard can subscribe without invoking the agent a second time.
"""

from __future__ import annotations

import threading
import uuid
from queue import Empty, Full, Queue
from typing import Any, Iterator

from ledger402.graph import stream_agent

IDLE = "idle"
RUNNING = "running"
DONE = "done"
ERROR = "error"

_SENTINEL = object()
_SUBSCRIBER_MAX = 1000


class RunInProgress(Exception):
    """A chat/dashboard run is already executing."""


class UnknownRun(Exception):
    """No matching run exists to watch."""


class _ActiveRun:
    def __init__(self, run_id: str, question: str) -> None:
        self.run_id = run_id
        self.question = question
        self.status = RUNNING
        self.events: list[dict[str, Any]] = []
        self.chunks: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.subscribers: list[Queue] = []
        self.lock = threading.Lock()


_lock = threading.Lock()
_latest: _ActiveRun | None = None


def reset() -> None:
    """Drop the latest run. Tests only."""
    global _latest
    with _lock:
        _latest = None


def snapshot() -> dict[str, Any]:
    run = _latest
    if run is None:
        return {
            "status": IDLE,
            "run_id": None,
            "question": None,
            "events": [],
            "result": None,
            "error": None,
        }
    with run.lock:
        return {
            "status": run.status,
            "run_id": run.run_id,
            "question": run.question,
            "events": list(run.events),
            "result": run.result,
            "error": run.error,
        }


def start(
    *,
    question: str,
    budget_drops: int = 5000,
    task_type: str | None = None,
    run_id: str | None = None,
    target_confidence: float | None = None,
    max_purchases: int | None = None,
    delivery_tier: str | None = None,
    replay: bool = False,
) -> str:
    global _latest
    assigned = run_id or str(uuid.uuid4())
    with _lock:
        if _latest is not None and _latest.status == RUNNING:
            raise RunInProgress("A research run is already in progress.")
        run = _ActiveRun(assigned, question)
        _latest = run

    params = {
        "question": question,
        "budget_drops": budget_drops,
        "task_type": task_type,
        "run_id": assigned,
        "target_confidence": target_confidence,
        "max_purchases": max_purchases,
        "delivery_tier": delivery_tier,
        "replay": replay,
    }
    thread = threading.Thread(target=_worker, args=(run, params), daemon=True)
    thread.start()
    return assigned


def _require(run_id: str | None = None) -> _ActiveRun:
    run = _latest
    if run is None:
        raise UnknownRun("No research run to watch.")
    if run_id and run.run_id != run_id:
        raise UnknownRun(f"Unknown run_id={run_id}.")
    return run


def follow(run_id: str | None = None) -> Iterator[dict[str, Any]]:
    return _iter_run(_require(run_id))


def _iter_run(run: _ActiveRun) -> Iterator[dict[str, Any]]:
    mailbox: Queue = Queue(maxsize=_SUBSCRIBER_MAX)
    with run.lock:
        buffered = list(run.chunks)
        finished = run.status in {DONE, ERROR}
        run.subscribers.append(mailbox)

    for chunk in buffered:
        yield chunk
    if finished:
        return

    while True:
        try:
            item = mailbox.get(timeout=120)
        except Empty:
            return
        if item is _SENTINEL:
            return
        yield item


def _fanout(run: _ActiveRun, item: Any) -> None:
    for mailbox in list(run.subscribers):
        try:
            mailbox.put_nowait(item)
        except Full:
            continue


def _publish(run: _ActiveRun, chunk: dict[str, Any]) -> None:
    kind = chunk.get("kind")
    with run.lock:
        run.chunks.append(chunk)
        if kind == "event":
            run.events.append(chunk.get("event") or {})
        elif kind == "result":
            run.result = chunk.get("result")
            run.status = DONE
        elif kind == "error":
            run.error = str(chunk.get("reason") or "Research run failed.")
            run.status = ERROR
        closing = kind in {"result", "error"}
        _fanout(run, chunk)
        if closing:
            _fanout(run, _SENTINEL)


def _worker(run: _ActiveRun, params: dict[str, Any]) -> None:
    try:
        for chunk in stream_agent(**params):
            _publish(run, chunk)
        with run.lock:
            if run.status == RUNNING:
                run.status = DONE
                _fanout(run, _SENTINEL)
    except Exception as exc:
        _publish(run, {"kind": "error", "reason": str(exc)})
