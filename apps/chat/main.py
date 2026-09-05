from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Ledger402 chat")


class Health(BaseModel):
    status: str
    service: str


@app.get("/health")
def health() -> Health:
    return Health(status="ok", service="chat")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
