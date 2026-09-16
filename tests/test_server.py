"""Unit tests for FastAPI REST API endpoints and dossier generation."""

import pytest
from httpx import ASGITransport, AsyncClient

from aegiswatch.server.app import app, simulator


@pytest.mark.anyio
async def test_server_status_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ONLINE"
        assert data["symbol"] == "NVDA"
        assert "performance" in data


@pytest.mark.anyio
async def test_attack_injection_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Inject Spoofing
        res = await client.post(
            "/api/attack",
            json={"type": "SPOOFING", "params": {"side": "BUY", "volume": 1000, "count": 2, "cancel_delay_ms": 10}},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ATTACK_TRIGGERED"
        assert body["details"]["scenario"] == "SPOOFING"


@pytest.mark.anyio
async def test_regulatory_dossier_generation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger wash trade to produce an alert
        await client.post(
            "/api/attack",
            json={"type": "WASH_TRADING", "params": {"volume": 500, "trades_count": 2}},
        )

        alerts_res = await client.get("/api/alerts")
        assert alerts_res.status_code == 200
        alerts = alerts_res.json()

        if alerts:
            alert_id = alerts[0]["alert_id"]
            dossier_res = await client.get(f"/api/dossier/{alert_id}")
            assert dossier_res.status_code == 200
            dossier = dossier_res.json()
            assert "case_number" in dossier
            assert "statutory_violations" in dossier
            assert "evidentiary_data" in dossier
            assert "enforcement_recommendation" in dossier


@pytest.mark.anyio
async def test_serve_dashboard_index():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
        assert res.status_code == 200
        assert "AegisWatch" in res.text

