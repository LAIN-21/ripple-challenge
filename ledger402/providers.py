from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ledger402 import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"


def load_json(name: str) -> Any:
    path = DATA_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_registry() -> list[dict[str, Any]]:
    data = load_json("providers.json")
    if not isinstance(data, list):
        raise ValueError("providers.json must be a list")
    return data


def resolve_url(provider: dict[str, Any], environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    env_name = str(provider["base_url_env"])
    base = env.get(env_name, "").rstrip("/")
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
