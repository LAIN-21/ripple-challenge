from __future__ import annotations

import uuid
from typing import Any

import requests

from ledger402 import audit, decision, payment, policy, providers

SUPPORTED_TASK = "port_congestion"
DEFAULT_QUESTION = "Assess whether Port X is becoming congested."


def is_port_congestion_question(question: str) -> bool:
    text = question.lower()
    if "port" not in text:
        return False
    return any(token in text for token in ("congest", "berth", "vessel", "queue", "yard"))


def initial_analysis(free_data: dict[str, Any]) -> dict[str, Any]:
    hours = int(free_data.get("freshness_hours") or 0)
    return {
        "congestion_risk": "MODERATE / UNCLEAR",
        "confidence": 0.58,
        "summary": (
            f"Public evidence is {hours} hours old and quality is moderate. "
            "Congestion is unclear from stale berth and queue statistics."
        ),
        "synthetic": True,
    }


def final_analysis(premium_data: dict[str, Any]) -> dict[str, Any]:
    yard = int(round(float(premium_data.get("yard_utilization") or 0) * 100))
    anchored = int(round(float(premium_data.get("anchored_vessels_delta") or 0) * 100))
    density = int(round(float(premium_data.get("container_density_delta") or 0) * 100))
    return {
        "congestion_risk": "HIGH",
        "confidence": 0.87,
        "evidence": [
            f"Yard utilization: {yard}%",
            f"Anchored vessel activity: +{anchored}%",
            f"Container density: +{density}%",
        ],
        "synthetic": True,
    }


def _fetch_json(url: str, timeout: float = 15.0) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def run_research(
    *,
    question: str,
    budget_drops: int,
    task_type: str = SUPPORTED_TASK,
    run_id: str | None = None,
) -> dict[str, Any]:
    if task_type != SUPPORTED_TASK:
        return {
            "error": "unsupported_task",
            "status_code": 400,
            "reason": f"Morning MVP only supports task_type={SUPPORTED_TASK!r}.",
        }
    if not is_port_congestion_question(question):
        return {
            "error": "unsupported_question",
            "status_code": 400,
            "reason": (
                "This MVP only answers port-congestion questions. "
                "It will not map unrelated questions onto Port X evidence."
            ),
        }

    run_id = run_id or str(uuid.uuid4())
    log: list[dict[str, Any]] = audit.new_log()
    remaining = int(budget_drops)
    spent = 0

    compatible = providers.providers_for_category(SUPPORTED_TASK)
    free_meta = next((p for p in compatible if not p.get("payment_required")), None)
    premium_meta = next((p for p in compatible if p.get("payment_required")), None)
    considered = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "price_drops": p.get("price_drops"),
            "payment_required": p.get("payment_required"),
        }
        for p in compatible
    ]

    audit.add(log, "RESEARCH_REQUEST_UNDERSTOOD", question=question, task_type=task_type)

    if free_meta is None:
        return {
            "run_id": run_id,
            "question": question,
            "error": "no_free_provider",
            "status_code": 503,
            "event_log": log,
        }

    free_url = providers.resolve_url(free_meta)
    try:
        free_data = _fetch_json(free_url)
        audit.add(log, "PUBLIC_SOURCE_QUERIED", url=free_url, synthetic=True)
    except Exception as exc:
        return {
            "run_id": run_id,
            "question": question,
            "error": "free_provider_unavailable",
            "reason": str(exc),
            "status_code": 503,
            "event_log": log,
        }

    initial = initial_analysis(free_data)
    result: dict[str, Any] = {
        "run_id": run_id,
        "question": question,
        "task_type": task_type,
        "initial_result": initial,
        "initial_confidence": initial["confidence"],
        "providers_considered": considered,
        "decision": "SKIP",
        "reason": "No premium provider evaluated.",
        "payment_status": "NOT_ATTEMPTED",
        "transaction_hash": None,
        "network_fee_drops": None,
        "premium_evidence": None,
        "final_result": initial,
        "final_confidence": initial["confidence"],
        "spent_drops": 0,
        "remaining_budget_drops": remaining,
        "premium_purchase": "NOT_ATTEMPTED",
        "fallback": None,
        "event_log": log,
        "synthetic": True,
    }

    if premium_meta is None:
        result["reason"] = "No compatible premium provider in registry."
        result["fallback"] = "PUBLIC_ONLY"
        return result

    eval_result = decision.evaluate_purchase(
        premium_meta,
        current_confidence=initial["confidence"],
        current_evidence=free_data,
        remaining_budget_drops=remaining,
    )
    result["decision"] = eval_result["decision"]
    result["reason"] = eval_result["reason"]
    result["utility"] = eval_result["utility"]
    audit.add(log, "PROVIDER_EVALUATED", **eval_result)

    if eval_result["decision"] != "BUY":
        result["fallback"] = "PUBLIC_ONLY"
        result["premium_purchase"] = "SKIPPED"
        return result

    policy_result = policy.check(premium_meta, remaining_budget_drops=remaining)
    if not policy_result["allowed"]:
        result["decision"] = "SKIP"
        result["reason"] = policy_result["reason"]
        result["fallback"] = "PUBLIC_ONLY"
        result["premium_purchase"] = "POLICY_REJECTED"
        return result

    audit.add(log, "PURCHASE_APPROVED", reason=policy_result["reason"])

    try:
        payment.require_wallet_env()
    except RuntimeError as exc:
        result["payment_status"] = payment.CONFIG_ERROR
        result["premium_purchase"] = payment.CONFIG_ERROR
        result["fallback"] = "PUBLIC_ONLY"
        result["reason"] = str(exc)
        return result

    try:
        premium_url = providers.resolve_url(premium_meta)
        purchase = payment.purchase_premium(
            url=premium_url,
            run_id=run_id,
            provider_id=str(premium_meta["id"]),
            expected_drops=int(premium_meta.get("price_drops") or 0),
            remaining_budget_drops=remaining,
            log=log,
        )
    except RuntimeError as exc:
        result["payment_status"] = payment.CONFIG_ERROR
        result["premium_purchase"] = payment.CONFIG_ERROR
        result["fallback"] = "PUBLIC_ONLY"
        result["reason"] = str(exc)
        return result
    except Exception as exc:
        result["payment_status"] = payment.UNKNOWN
        result["premium_purchase"] = payment.UNKNOWN
        result["fallback"] = "PUBLIC_ONLY"
        result["reason"] = f"XRPL payment failed: {exc}"
        return result

    result["payment_status"] = purchase.state
    result["premium_purchase"] = purchase.state
    result["transaction_hash"] = purchase.tx_hash
    result["network_fee_drops"] = purchase.network_fee_drops

    if purchase.state == payment.SUCCESS and isinstance(purchase.body, dict):
        spent = int(premium_meta.get("price_drops") or 0)
        remaining = remaining - spent
        final = final_analysis(purchase.body)
        result["premium_evidence"] = purchase.body
        result["final_result"] = final
        result["final_confidence"] = final["confidence"]
        result["spent_drops"] = spent
        result["remaining_budget_drops"] = remaining
        result["reason"] = eval_result["reason"]
        return result

    result["fallback"] = "PUBLIC_ONLY"
    result["reason"] = purchase.error or "Premium procurement did not succeed."
    return result
