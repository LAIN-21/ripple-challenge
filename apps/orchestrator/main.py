from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ledger402 import REPO_ROOT
from ledger402.agent import run_research
from ledger402.models import ResearchRequest

load_dotenv(REPO_ROOT / ".env")

app = FastAPI(title="Ledger402 orchestrator")


class Health(BaseModel):
    status: str
    service: str


@app.get("/health")
def health() -> Health:
    return Health(status="ok", service="orchestrator")


@app.post("/research")
def research(body: ResearchRequest):
    result = run_research(
        question=body.question,
        budget_drops=body.budget_drops,
        task_type=body.task_type,
        run_id=body.run_id,
    )
    status = int(result.get("status_code") or 200)
    if status >= 400:
        raise HTTPException(status_code=status, detail=result)
    return result
