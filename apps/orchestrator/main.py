from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ledger402 import REPO_ROOT, llm, tasks
from ledger402 import network as xrpl_network
from ledger402.graph import DEFAULT_BUDGET_DROPS, run_agent, stream_agent
from ledger402.models import ResearchRequest

load_dotenv(REPO_ROOT / ".env")

app = FastAPI(title="Ledger402 orchestrator")

LIVE_PAGE = Path(__file__).resolve().parents[1] / "ui" / "live.html"


class Health(BaseModel):
    status: str
    service: str


@app.get("/health")
def health() -> Health:
    return Health(status="ok", service="orchestrator")


@app.get("/capabilities")
def capabilities() -> dict:
    """What the agent can currently answer, and how it is configured.

    Lets the UI show the honest picture without hardcoding it: which task types are
    supported, and whether the LLM path or the deterministic fallback is active.
    """
    return {
        "supported_task_types": list(tasks.SUPPORTED_TASK_TYPES),
        "llm_enabled": llm.is_enabled(),
        "llm_provider": llm.provider_name() or None,
        "llm_model": llm.model_name() if llm.is_enabled() else None,
        "llm_role": "question classification and report writing only; never spending",
        "network": xrpl_network.current_status(),
    }


@app.get("/live", response_class=HTMLResponse)
def live_page() -> HTMLResponse:
    """The step-by-step agent animation.

    Served from the orchestrator so it shares an origin with the SSE stream: no CORS
    configuration, and no extra process to start for the demo.
    """
    if not LIVE_PAGE.exists():  # pragma: no cover - packaging guard
        raise HTTPException(status_code=404, detail="live.html is missing")
    return HTMLResponse(LIVE_PAGE.read_text(encoding="utf-8"))


@app.get("/research/stream")
def research_stream(
    question: str = Query(default="Assess whether Port X is becoming congested."),
    budget_drops: int = Query(default=DEFAULT_BUDGET_DROPS, ge=0),
    target_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    max_purchases: int | None = Query(default=None, ge=0, le=10),
    task_type: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
) -> StreamingResponse:
    """Server-sent events: one message per audit entry, then the final result.

    GET rather than POST so the browser's native EventSource can consume it directly.
    """

    def events() -> Iterator[str]:
        for chunk in stream_agent(
            question=question,
            budget_drops=budget_drops,
            task_type=task_type,
            run_id=run_id,
            target_confidence=target_confidence,
            max_purchases=max_purchases,
        ):
            yield f"data: {json.dumps(chunk, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Keep proxies from buffering the stream into one delivery at the end.
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/research")
def research(body: ResearchRequest):
    result = run_agent(
        question=body.question,
        budget_drops=body.budget_drops,
        task_type=body.task_type,
        run_id=body.run_id,
        target_confidence=body.target_confidence,
        max_purchases=body.max_purchases,
    )
    status = int(result.get("status_code") or 200)
    if status >= 400:
        raise HTTPException(status_code=status, detail=result)
    return result
