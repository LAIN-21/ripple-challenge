"""Task definitions: what a confident answer requires, per task type.

A task declares the *signals* an analyst would need to answer it, and how much each
signal matters. Providers are then judged on the signals they actually deliver, which
is what lets the agent decide whether a further purchase is worth making.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PORT_CONGESTION = "port_congestion"

# Credibility decays to zero over four days. Shared with decision.freshness_score.
FRESHNESS_HORIZON_HOURS = 96.0


@dataclass(frozen=True)
class TaskSpec:
    """One supported research task."""

    task_type: str
    label: str
    # Signal name -> weight. Weights sum to 1.0 across a fully covered task.
    signal_weights: dict[str, float]
    default_question: str
    # Keywords used by the deterministic classifier fallback.
    required_terms: tuple[str, ...]
    supporting_terms: tuple[str, ...]

    def weight(self, signal: str) -> float:
        return self.signal_weights.get(signal, 0.0)


PORT_CONGESTION_SPEC = TaskSpec(
    task_type=PORT_CONGESTION,
    label="Port congestion assessment",
    signal_weights={
        # Public statistics: broad but shallow.
        "berth_occupancy": 0.10,
        "average_wait_hours": 0.06,
        "vessel_queue": 0.09,
        # Satellite observation: the signals that actually resolve congestion.
        "yard_utilization": 0.25,
        "anchored_vessels_delta": 0.20,
        "container_density_delta": 0.12,
        "truck_activity_delta": 0.06,
        # Landside telemetry: the last mile of certainty.
        "gate_turnaround_minutes": 0.07,
        "rail_dwell_hours": 0.05,
    },
    default_question="Assess whether Port X is becoming congested.",
    required_terms=("port",),
    supporting_terms=("congest", "berth", "vessel", "queue", "yard", "terminal", "dwell"),
)

TASKS: dict[str, TaskSpec] = {PORT_CONGESTION: PORT_CONGESTION_SPEC}

SUPPORTED_TASK_TYPES = tuple(TASKS)


def get_task(task_type: str) -> TaskSpec | None:
    return TASKS.get(task_type)


def is_supported(task_type: str) -> bool:
    return task_type in TASKS


def signals_in(payload: dict[str, Any], spec: TaskSpec) -> set[str]:
    """Which of the task's signals this payload actually carries.

    Metadata keys (provider_id, freshness_hours, ...) are ignored: a source only gets
    credit for signals it really returned, with a usable numeric value.
    """
    found: set[str] = set()
    for signal in spec.signal_weights:
        value = payload.get(signal)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            found.add(signal)
    return found
