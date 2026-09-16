"""Command line entrypoint for starting the AegisWatch surveillance system."""

from __future__ import annotations

import argparse
import sys
import uvicorn


def main():
    parser = argparse.ArgumentParser(
        description="AegisWatch — Microsecond Limit Order Book Market Abuse Surveillance Engine"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve HUD and API (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    banner = f"""
================================================================================
   🛡️  AEGISWATCH v1.0.0 — NASDAQ MARKET SURVEILLANCE ENGINE
   Real-Time Limit Order Book (LOB) Abuse & Microstructure Anomaly Watchdog
================================================================================
   • Surveillance HUD : http://{args.host}:{args.port}
   • Interactive API  : http://{args.host}:{args.port}/docs
   • WebSocket Stream : ws://{args.host}:{args.port}/ws/stream
   • Track / Sponsor  : AI in FinTech · NASDAQ (Synapse 1.0)
================================================================================
"""
    print(banner, flush=True)

    uvicorn.run(
        "aegiswatch.server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
