from __future__ import annotations

import copy
import os
from typing import Any

from providers_data import PROVIDERS_REGISTRY

from ledger402 import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"

DEFAULT_PROVIDER_URL = "http://localhost:8001"

# Nested SGSIN metrics → keys the confidence model already scores.
FLAT_SIGNAL_MAP = {
    "berth_occupancy_ratio": "berth_occupancy",
    "average_wait_hours": "average_wait_hours",
    "vessel_queue_count": "vessel_queue",
    "container_yard_utilization_ratio": "yard_utilization",
    "anchored_vessels_count": "anchored_vessels_delta",
    "container_density_index": "container_density_delta",
    "truck_turnaround_hours": "truck_activity_delta",
    "gate_dwell_hours": "gate_turnaround_minutes",
    "rail_and_intermodal_dwell_pct": "rail_dwell_hours",
}

B2B_META = {
    "public_port_stats": {
        "name": "Public Port Statistics",
        "base_url_env": "FREE_PROVIDER_URL",
        "payment_required": False,
        "expected_information_gain": 0.05,
        "signals": ["berth_occupancy", "average_wait_hours", "vessel_queue"],
    },
    "satellite_logistics_paid": {
        "name": "Satellite Logistics Intelligence",
        "base_url_env": "PREMIUM_PROVIDER_URL",
        "payment_required": True,
        "expected_information_gain": 0.35,
        "signals": [
            "yard_utilization",
            "anchored_vessels_delta",
            "container_density_delta",
            "truck_activity_delta",
        ],
    },
    "terminal_telemetry_paid": {
        "name": "Terminal Operations Telemetry",
        "base_url_env": "TELEMETRY_PROVIDER_URL",
        "payment_required": True,
        "expected_information_gain": 0.12,
        "signals": ["gate_turnaround_minutes", "rail_dwell_hours"],
    },
}


def load_json(name: str) -> Any:
    path = DATA_DIR / name
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def flatten_payload(provider_id: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Nested SGSIN body plus flat signal keys the ranking loop understands."""
    source = spec if spec is not None else PROVIDERS_REGISTRY.get(provider_id) or {}
    payload = copy.deepcopy(source.get("payload") or {})
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    flat: dict[str, Any] = dict(payload)
    for nested_key, signal in FLAT_SIGNAL_MAP.items():
        if nested_key in metrics:
            flat[signal] = metrics[nested_key]
    meta = B2B_META.get(provider_id, {})
    flat["provider_id"] = provider_id
    flat["provider_name"] = meta.get("name") or str(source.get("description") or provider_id)
    flat["freshness_hours"] = source.get("freshness_hours")
    flat["quality_score"] = source.get("quality_score")
    flat["synthetic"] = True
    if "port" not in flat:
        flat["port"] = payload.get("facility_name") or payload.get("port_code") or "SGSIN"
    return flat


def catalog_entry(provider_id: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    source = spec if spec is not None else PROVIDERS_REGISTRY[provider_id]
    meta = B2B_META.get(provider_id, {})
    path = str(source.get("endpoint") or source.get("path") or "")
    price = int(source.get("price_drops") or 0)
    return {
        "id": provider_id,
        "name": meta.get("name") or str(source.get("curator_label") or source.get("description") or provider_id),
        "category": str(source.get("category") or "port_congestion"),
        "base_url_env": meta.get("base_url_env") or source.get("base_url_env") or "PROVIDER_URL",
        "path": path,
        "payment_required": bool(meta.get("payment_required") if provider_id in B2B_META else price > 0),
        "price_drops": price,
        "freshness_hours": source.get("freshness_hours", 1),
        "quality_score": source.get("quality_score", 0.75),
        "expected_information_gain": float(
            source.get("expected_information_gain") or meta.get("expected_information_gain") or 0.08
        ),
        "signals": list(source.get("signals") or meta.get("signals") or []),
        "description": source.get("description"),
        "license": source.get("license"),
        "pay_to": source.get("pay_to") or os.getenv("XRPL_PAY_TO"),
        "curator_address": source.get("curator_address"),
        "settlement_mode": source.get("settlement_mode"),
    }


def load_registry() -> list[dict[str, Any]]:
    """Static B2B entries plus any datasets appended to PROVIDERS_REGISTRY at runtime."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider_id, spec in PROVIDERS_REGISTRY.items():
        entries.append(catalog_entry(provider_id, spec))
        seen.add(provider_id)
    try:
        from ledger402 import marketplace

        for provider_id, spec in marketplace.dynamic_registry().items():
            if provider_id not in seen:
                entries.append(catalog_entry(provider_id, spec))
    except Exception:
        pass
    return entries


def resolve_url(provider: dict[str, Any], environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    env_name = str(provider.get("base_url_env") or "PROVIDER_URL")
    base = (env.get(env_name) or env.get("PROVIDER_URL") or DEFAULT_PROVIDER_URL).rstrip("/")
    if not base:
        raise RuntimeError(f"Missing base URL env var {env_name}")
    path = str(provider.get("path") or "")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def providers_for_category(category: str) -> list[dict[str, Any]]:
    return [p for p in load_registry() if p.get("category") == category]


def get_provider(provider_id: str) -> dict[str, Any] | None:
    for item in load_registry():
        if item.get("id") == provider_id:
            return item
    return None
