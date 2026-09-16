"""FastAPI surveillance server, WebSocket real-time event bus, and REST API."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from aegiswatch.feed.simulator import MarketFeedSimulator
from aegiswatch.server.dossier import RegulatoryDossierGenerator


class AttackRequest(BaseModel):
    type: str = Field(..., description="Attack type: SPOOFING, LAYERING, QUOTE_STUFFING, WASH_TRADING, MOMENTUM_IGNITION")
    params: Dict[str, Any] = Field(default_factory=dict)


# Global simulator instance
simulator = MarketFeedSimulator(symbol="NVDA", base_price=180.00, tick_interval_ms=50.0)
active_websockets: Set[WebSocket] = set()


async def broadcast_market_packet(packet: Dict[str, Any]) -> None:
    """Broadcast market state tick to all active WebSocket clients."""
    if not active_websockets:
        return
    msg = json.dumps(packet)
    disconnected = set()
    for ws in active_websockets:
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.add(ws)
    for ws in disconnected:
        active_websockets.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: register broadcast listener and launch simulator
    simulator.subscribe(broadcast_market_packet)
    await simulator.start()
    yield
    # Shutdown
    await simulator.stop()
    simulator.unsubscribe(broadcast_market_packet)


app = FastAPI(
    title="AegisWatch Surveillance Engine",
    description="Microsecond Limit Order Book Market Abuse Surveillance & Anomaly Engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    active_websockets.add(websocket)
    try:
        # Immediately send current state on connect
        initial_packet = simulator._process_and_package_state()
        await websocket.send_text(json.dumps(initial_packet))

        # Keep connection open and listen for optional ping/client commands
        while True:
            data = await websocket.receive_text()
            # Optional client ping handler
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
    except Exception:
        active_websockets.discard(websocket)


@app.get("/api/status")
async def get_status():
    stats = simulator.pipeline.get_stats()
    return {
        "status": "ONLINE",
        "symbol": simulator.symbol,
        "is_running": simulator.is_running,
        "mid_price": simulator.book.get_mid_price(),
        "spread": simulator.book.get_spread(),
        "total_alerts": len(simulator.pipeline.alert_history),
        "performance": stats,
    }


@app.get("/api/alerts")
async def get_alerts(limit: int = 50):
    return simulator.pipeline.get_recent_alerts(limit=limit)


@app.get("/api/dossier/{alert_id}")
async def get_dossier(alert_id: str):
    alert = simulator.pipeline.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found in active surveillance memory.")
    dossier = RegulatoryDossierGenerator.generate_dossier(alert, simulator.book)
    return dossier


@app.post("/api/attack")
async def inject_attack(req: AttackRequest):
    attack_type = req.type.upper()
    params = req.params or {}

    if attack_type == "SPOOFING":
        res = await simulator.inject_spoofing(
            side=params.get("side", "BUY"),
            volume=int(params.get("volume", 1200)),
            count=int(params.get("count", 3)),
            cancel_delay_ms=float(params.get("cancel_delay_ms", 30.0)),
        )
    elif attack_type == "LAYERING":
        res = await simulator.inject_layering(
            side=params.get("side", "SELL"),
            levels=int(params.get("levels", 4)),
            volume=int(params.get("volume", 800)),
        )
    elif attack_type == "QUOTE_STUFFING":
        res = await simulator.inject_quote_stuffing(
            burst_count=int(params.get("burst_count", 50)),
        )
    elif attack_type == "WASH_TRADING":
        res = await simulator.inject_wash_trading(
            volume=int(params.get("volume", 500)),
            trades_count=int(params.get("trades_count", 3)),
        )
    elif attack_type == "MOMENTUM_IGNITION":
        res = await simulator.inject_momentum_ignition(
            direction=params.get("direction", "BULLISH"),
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown attack scenario '{req.type}'. Supported: SPOOFING, LAYERING, QUOTE_STUFFING, WASH_TRADING, MOMENTUM_IGNITION",
        )

    return {"status": "ATTACK_TRIGGERED", "details": res}


@app.post("/api/reset")
async def reset_book():
    simulator._initialize_book()
    simulator.pipeline.alert_history.clear()
    simulator.pipeline.alert_map.clear()
    return {"status": "RESET_COMPLETE", "symbol": simulator.symbol}


# Mount static web dashboard
web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    async def serve_index():
        index_path = os.path.join(web_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse({"status": "AegisWatch API Online", "web_ui": "Web assets pending"})
