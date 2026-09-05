"""Compatibility shim. Paid 402 routes now live on the unified gateway (`server:app`)."""

from server import app

__all__ = ["app"]
