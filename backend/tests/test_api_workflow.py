import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app, seed_initial_data
from app.db.session import init_db


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    await seed_initial_data()


@pytest.mark.asyncio
async def test_full_incident_remediation_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

        # 2. Login as technician
        login_res = await client.post("/api/auth/login", json={
            "email": "tech@college.edu",
            "password": "Tech@123"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Create incident
        create_res = await client.post("/api/incidents", headers=headers, json={
            "title": "My laptop is connected to college Wi-Fi, but I cannot access anything.",
            "description": "Connected to Campus-Student-WiFi with APIPA 169.254 address. Gateway unreachable.",
            "category": "NETWORK",
            "priority": "HIGH"
        })
        assert create_res.status_code == 200
        inc_data = create_res.json()
        incident_id = inc_data["id"]
        assert inc_data["status"] == "NEW"

        # 4. Trigger automated diagnosis
        diag_res = await client.post(
            f"/api/incidents/{incident_id}/diagnose",
            headers=headers,
            json={"use_ai": False}  # Use deterministic rules for integration test
        )
        assert diag_res.status_code == 200
        diag_data = diag_res.json()
        assert "renew_dhcp" in diag_data["recommended_tool_ids"]
        assert diag_data["status"] == "hypotheses"

        # 5. Create Remediation Plan
        plan_res = await client.post(
            f"/api/incidents/{incident_id}/remediation-plan",
            headers=headers,
            json={
                "tool_id": "renew_dhcp",
                "arguments": {"adapter_name": "Wi-Fi"},
                "reason": "Re-negotiate DHCP lease to replace APIPA link-local address."
            }
        )
        assert plan_res.status_code == 200
        plan_data = plan_res.json()
        plan_id = plan_data["id"]
        assert plan_data["risk_level"] == "R2"
        assert plan_data["approval_required"] == 1
        assert plan_data["status"] == "PENDING"

        # 6. Approve Plan (as technician)
        appr_res = await client.post(
            f"/api/remediation-plans/{plan_id}/approve",
            headers=headers,
            json={
                "decision": "APPROVED",
                "reason": "Technician verified DHCP scope and authorized client renewal."
            }
        )
        assert appr_res.status_code == 200
        assert appr_res.json()["decision"] == "APPROVED"

        # 7. Execute Plan and Verify Postcondition
        exec_res = await client.post(
            f"/api/remediation-plans/{plan_id}/execute",
            headers=headers,
            params={"is_mock": True, "simulate_verification_outcome": "VERIFIED_RESOLVED"}
        )
        assert exec_res.status_code == 200
        exec_data = exec_res.json()
        assert exec_data["execution_status"] == "SUCCESS"
        assert exec_data["verification"]["status"] == "VERIFIED_RESOLVED"

        # 8. Check that incident is now RESOLVED
        inc_check = await client.get(f"/api/incidents/{incident_id}", headers=headers)
        assert inc_check.status_code == 200
        assert inc_check.json()["status"] == "RESOLVED"
        assert "verified resolved" in inc_check.json()["resolution_summary"].lower()
