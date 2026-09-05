from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    """One research objective for the agent.

    `target_confidence` is the lever that makes the loop visible: at 0.85 the agent buys
    the satellite feed alone; raise it and the same agent buys a second feed.
    """

    run_id: str | None = None
    task_type: str | None = None
    question: str = "Assess whether Port of Singapore (PSA) is facing critical yard and terminal congestion."
    budget_drops: int = Field(default=5000, ge=0)
    target_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    max_purchases: int | None = Field(default=None, ge=0, le=10)
    delivery_tier: str | None = Field(default="tier_1")
    replay: bool = False


class AuditEvent(BaseModel):
    type: str
    at: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
