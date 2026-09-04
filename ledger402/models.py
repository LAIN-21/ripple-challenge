from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    run_id: str | None = None
    task_type: str = "port_congestion"
    question: str = "Assess whether Port X is becoming congested."
    budget_drops: int = Field(default=5000, ge=0)


class AuditEvent(BaseModel):
    type: str
    detail: dict[str, Any] = Field(default_factory=dict)
