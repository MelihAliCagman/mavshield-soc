#!/usr/bin/env python3
"""
FastAPI tabanlı SOC olay servisi.

detect/engine.py'den gelen güvenlik uyarılarını (Alert) toplar, bellekte
tutar, bağlı SOC panellerine WebSocket üzerinden canlı yayınlar ve AI
destekli (veya şablon tabanlı) özet rapor üretimi için bir uç nokta sunar.

Çalıştırma:
  uvicorn backend.app:app --reload --port 8000 --app-dir .
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend.ai_report import generate_report  # noqa: E402

MAX_EVENTS = 2000

app = FastAPI(title="İHA SOC Olay Servisi")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AlertIn(BaseModel):
    rule: str
    severity: str
    message: str
    ts: Optional[float] = None
    source: Optional[str] = None
    evidence: dict = {}


_events: List[dict] = []
_clients: List[WebSocket] = []


@app.post("/ingest")
async def ingest(alert: AlertIn):
    """detect/engine.py'nin uyarı gönderdiği uç nokta."""
    evt = alert.model_dump()
    if evt.get("ts") is None:
        evt["ts"] = time.time()
    _events.append(evt)
    if len(_events) > MAX_EVENTS:
        del _events[: len(_events) - MAX_EVENTS]

    dead = []
    for ws in _clients:
        try:
            await ws.send_json(evt)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.remove(ws)
    return {"ok": True}


@app.get("/events")
async def events(limit: int = 200):
    """Panelin ilk yüklemede (veya WebSocket'siz) çekebileceği REST uç noktası."""
    return _events[-limit:]


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    try:
        for evt in _events[-50:]:
            await ws.send_json(evt)
        while True:
            await ws.receive_text()  # istemciden gelen her şeyi yok say (keepalive)
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _clients:
            _clients.remove(ws)


@app.get("/report")
async def report(limit: int = 100):
    recent = _events[-limit:]
    text, source = generate_report(recent)
    return {"report": text, "generated_by": source, "event_count": len(recent)}


@app.get("/health")
async def health():
    return {"status": "ok", "events": len(_events), "clients": len(_clients)}
