"""Question understanding: business question -> task type.

The morning MVP rejected anything that did not match a keyword rule. That is safe but not
agentic: the agent should *understand* the objective, then fail closed only when it
genuinely cannot serve it.

The LLM classifies; the deterministic rule is both the fallback and the guard. An LLM
answer for an unsupported task type is still rejected, so a prompt injection in the
question cannot talk the agent into serving evidence it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ledger402 import llm, tasks
from ledger402.tasks import SUPPORTED_TASK_TYPES, TaskSpec

SYSTEM_PROMPT = """\
You classify business research questions for an autonomous intelligence procurement agent.

Supported task types:
- port_congestion: assessing congestion, throughput, berth or yard pressure, vessel \
queues, or terminal delays at a seaport.

Return ONLY a JSON object:
{"task_type": "port_congestion" | "unsupported",
 "subject": "<the specific entity being asked about, e.g. a port name, or null>",
 "confidence": <0.0-1.0>,
 "rationale": "<one sentence>"}

Use "unsupported" for anything the listed task types do not cover. Never guess a
supported type to be helpful; an incorrect classification causes the agent to answer with
evidence about the wrong subject.
"""


@dataclass
class Classification:
    task_type: str
    subject: str | None
    confidence: float
    rationale: str
    method: str  # "llm" or "deterministic"
    supported: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "subject": self.subject,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "method": self.method,
            "supported": self.supported,
        }


UNSUPPORTED = "unsupported"


def _matches_keywords(question: str, spec: TaskSpec) -> bool:
    """The morning MVP's rule, kept as the fallback classifier."""
    text = question.lower()
    if not all(term in text for term in spec.required_terms):
        return False
    return any(term in text for term in spec.supporting_terms)


def _extract_subject(question: str) -> str | None:
    """Best-effort subject extraction without an LLM: the token after "port"."""
    words = question.replace(",", " ").replace(".", " ").split()
    for index, word in enumerate(words[:-1]):
        if word.lower().strip("?") == "port":
            candidate = words[index + 1].strip("?'\"")
            if candidate and candidate[0].isupper():
                return f"Port {candidate}"
    return None


def classify_deterministic(question: str) -> Classification:
    for task_type in SUPPORTED_TASK_TYPES:
        spec = tasks.get_task(task_type)
        if spec and _matches_keywords(question, spec):
            return Classification(
                task_type=task_type,
                subject=_extract_subject(question),
                confidence=0.7,
                rationale="Question matches the port-congestion keyword rule.",
                method="deterministic",
                supported=True,
            )
    return Classification(
        task_type=UNSUPPORTED,
        subject=None,
        confidence=0.7,
        rationale="Question does not match any supported task type.",
        method="deterministic",
        supported=False,
    )


def classify(question: str, declared_task_type: str | None = None) -> Classification:
    """Classify a question, preferring the LLM and falling back deterministically.

    `declared_task_type` is the caller's explicit request. It is honoured only if it is a
    supported type; an unsupported declaration is rejected without consulting the LLM.
    """
    if declared_task_type and declared_task_type != tasks.PORT_CONGESTION:
        if not tasks.is_supported(declared_task_type):
            return Classification(
                task_type=UNSUPPORTED,
                subject=None,
                confidence=1.0,
                rationale=(
                    f"Requested task_type {declared_task_type!r} is not supported. "
                    f"Supported: {', '.join(SUPPORTED_TASK_TYPES)}."
                ),
                method="deterministic",
                supported=False,
            )

    if not llm.is_enabled():
        return classify_deterministic(question)

    try:
        parsed = llm.complete_json(SYSTEM_PROMPT, f"Question: {question}")
    except llm.LLMUnavailable:
        return classify_deterministic(question)

    task_type = str(parsed.get("task_type") or UNSUPPORTED).strip()
    # The LLM cannot widen what the agent serves: an unrecognised type is unsupported.
    supported = tasks.is_supported(task_type)
    subject = parsed.get("subject")
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    return Classification(
        task_type=task_type if supported else UNSUPPORTED,
        subject=str(subject) if subject else _extract_subject(question),
        confidence=max(0.0, min(1.0, confidence)),
        rationale=str(parsed.get("rationale") or "").strip() or "Classified by LLM.",
        method="llm",
        supported=supported,
    )
