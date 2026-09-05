"""Compatibility shim. The unified gateway is `server:app` on :8001."""

from server import app

__all__ = ["app"]
