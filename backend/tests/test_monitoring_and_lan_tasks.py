import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.main import app, seed_initial_data
from app.db.session import init_db, AsyncSessionLocal, engine
from app.models.endpoint import Endpoint
from app.models.incident import Incident
from app.models.monitoring import EndpointTelemetrySnapshot, AgentTask, AgentDecisionLog
from app.models.sync import EndpointSyncEvent


@pytest.fixture(autouse=True)
async def setup_db():
    await engine.dispose()
    await init_db()
    await seed_initial_data()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_monitoring_lan_tasks_and_decision_logs():
    test_uuid = f"test-lan-node-{uuid.uuid4().hex[:8]}"
    sync_ev_uuid = f"ev-{uuid.uuid4().hex[:12]}"

    degraded_telemetry = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up", "mac_address": "AA:11:22:33:44:55"},
        "adapters_list": [{"name": "Wi-Fi 2", "description": "Intel Wi-Fi", "status": "Up", "is_virtual": False}],
        "ip_config": {
            "adapter_name": "Wi-Fi 2",
            "ipv4_address": "192.168.1.99",
            "default_gateway": "192.168.1.1",
            "dhcp_enabled": False,
            "dns_dhcp_enabled": False,
            "static_dns_configured": True,
            "dns_servers": ["8.8.8.8"],
        },
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0, "avg_latency_ms": 4, "target_gateway": "192.168.1.1"},
        "internet_ping": {"reachable": True, "packet_loss_pct": 0, "avg_latency_ms": 25, "target_ip": "8.8.8.8"},
        "dns_test": {"resolved": True, "dns_dhcp_enabled": False, "dns_servers": ["8.8.8.8"]},
        "firewall": {"Domain": True, "Private": True, "Public": True},
        "services": {
            "Spooler": {"status": "Running"},
            "Dhcp": {"status": "Running"},
            "Dnscache": {"status": "Running"},
            "WlanSvc": {"status": "Running"},
        },
    }

    healthy_telemetry = {
        **degraded_telemetry,
        "ip_config": {
            "adapter_name": "Wi-Fi 2",
            "ipv4_address": "10.63.1.201",
            "default_gateway": "10.63.0.1",
            "dhcp_enabled": True,
            "dns_dhcp_enabled": True,
            "static_dns_configured": False,
            "dns_servers": ["10.63.0.1"],
        },
        "dns_test": {"resolved": True, "dns_dhcp_enabled": True, "dns_servers": ["10.63.0.1"]},
    }

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Authenticate technician
            login_res = await client.post("/api/auth/login", json={"email": "tech@college.edu", "password": "Tech@123"})
            assert login_res.status_code == 200
            headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

            # 2. Check LAN join network info
            net_res = await client.get("/api/agents/network-info", headers=headers)
            assert net_res.status_code == 200
            assert "join_command" in net_res.json()

            # 3. Enroll test LAN agent
            en_res = await client.post("/api/agents/enroll", json={
                "agent_uuid": test_uuid,
                "hostname": "LAB-PEER-WIN11",
                "os_name": "Windows",
                "os_version": "Windows 11",
                "agent_version": "1.0.0",
                "ip_address": "192.168.1.99",
                "adapter_name": "Wi-Fi 2",
                "telemetry": degraded_telemetry,
            })
            assert en_res.status_code == 200

            # 4. Send degraded heartbeat -> watchdog detects anomaly transition & records decision log
            hb1 = await client.post("/api/agents/heartbeat", json={
                "agent_uuid": test_uuid,
                "ip_address": "192.168.1.99",
                "telemetry": degraded_telemetry,
            })
            assert hb1.status_code == 200

            # 5. Disallowed tool rejected by policy (400)
            bad_task = await client.post(
                f"/api/agents/{test_uuid}/tasks",
                headers=headers,
                json={"tool_id": "format_c_drive", "reason": "Malicious test"},
            )
            assert bad_task.status_code == 400

            # 6. Disallowed service rejected by policy (400)
            bad_srv = await client.post(
                f"/api/agents/{test_uuid}/tasks",
                headers=headers,
                json={"tool_id": "restart_approved_service", "arguments": {"service_name": "WindowsUpdate"}},
            )
            assert bad_srv.status_code == 400

            # 7. Dispatch allowlisted renew_dhcp task to LAN peer
            t_res = await client.post(
                f"/api/agents/{test_uuid}/tasks",
                headers=headers,
                json={"tool_id": "renew_dhcp", "reason": "Convert manual static IP to campus DHCP"},
            )
            assert t_res.status_code == 200
            task_uuid = t_res.json()["task_uuid"]
            assert t_res.json()["status"] == "PENDING"

            # 8. Peer daemon fast-polls pending tasks
            pend_res = await client.get(f"/api/agents/{test_uuid}/tasks/pending")
            assert pend_res.status_code == 200
            pending = pend_res.json()["tasks"]
            assert any(p["task_uuid"] == task_uuid for p in pending)

            # Verify GET /api/agents/tasks/{task_uuid} reflects DISPATCHED
            st_res = await client.get(f"/api/agents/tasks/{task_uuid}", headers=headers)
            assert st_res.status_code == 200
            assert st_res.json()["status"] == "DISPATCHED"

            # 9. Peer submits result with healthy postcondition + explanation
            rep_res = await client.post(
                f"/api/agents/{test_uuid}/tasks/{task_uuid}/result",
                json={
                    "status": "COMPLETED",
                    "result_status": "FIXED",
                    "verification_status": "VERIFIED_RESOLVED",
                    "output_text": "DHCP restored cleanly on Wi-Fi 2 (10.63.1.201)",
                    "why_explanation": "Static IP interfered with campus DHCP; switched to automatic lease and verified.",
                    "observed_state": "192.168.1.99 Static -> 10.63.1.201 DHCP",
                    "expected_state": "Valid DHCP lease",
                    "telemetry": healthy_telemetry,
                    "executed_actions": [{"tool_id": "renew_dhcp", "success": True}],
                },
            )
            assert rep_res.status_code == 200
            assert rep_res.json()["status"] == "COMPLETED"

            # 10. Offline sync event with decision_trace creates decision log
            sync_res = await client.post(
                f"/api/agents/{test_uuid}/sync",
                json={
                    "agent_uuid": test_uuid,
                    "events": [{
                        "event_uuid": sync_ev_uuid,
                        "event_type": "OFFLINE_REMEDIATION_SUCCESS",
                        "created_at_local": datetime.now(timezone.utc).isoformat(),
                        "payload": {
                            "detected_issue": "Manual static DNS",
                            "rule_matched": "KB-NET-012",
                            "recommended_action": "flush_dns_cache",
                            "decision_trace": {
                                "decision_type": "AUTO_REMEDIATED",
                                "rule_or_model": "KB-NET-012",
                                "action_taken": "flush_dns_cache",
                                "why_explanation": "Cleared hardcoded 8.8.8.8 back to automatic campus DNS while offline.",
                                "observed_state": "DNS=Static(8.8.8.8)",
                                "expected_state": "Automatic DHCP DNS",
                                "confidence": 0.97,
                            },
                        },
                    }],
                },
            )
            assert sync_res.status_code == 200
            assert sync_ev_uuid in sync_res.json()["accepted_uuids"]

            # 11. Broadcast to selected peer
            bc_res = await client.post(
                "/api/agents/broadcast-task",
                headers=headers,
                json={"tool_id": "collect_network_status", "agent_uuids": [test_uuid], "reason": "Fleet check"},
            )
            assert bc_res.status_code == 200
            assert bc_res.json()["dispatched_count"] == 1

            # 12. Test /api/dashboard/collect-probe without agent_uuid (multiple endpoints present)
            from unittest.mock import patch
            with patch("socket.gethostname", return_value="LAB-PEER-WIN11"):
                with patch("app.api.dashboard.windows_net.collect_live_windows_evidence", return_value=healthy_telemetry):
                    probe_res = await client.post("/api/dashboard/collect-probe", headers=headers, json={"mode": "direct_server"})
                    assert probe_res.status_code == 200
                    assert probe_res.json()["mode"] == "DIRECT_COLLECTED"
                    assert probe_res.json()["agent_uuid"] == test_uuid

            # 13. Verify unified /api/dashboard/monitor output
            mon_res = await client.get(f"/api/dashboard/monitor?agent_uuid={test_uuid}&limit=20", headers=headers)
            assert mon_res.status_code == 200
            mon = mon_res.json()
            assert mon["selected_agent_uuid"] == test_uuid
            assert mon["latest_metrics"]["ip_address"] == "10.63.1.201"
            assert mon["latest_metrics"]["health_score"] == 100
            assert len(mon["time_series"]) >= 3
            assert any("switched to automatic lease" in d["why_explanation"].lower() for d in mon["decision_logs"])
            assert any("cleared hardcoded 8.8.8.8" in d["why_explanation"].lower() for d in mon["decision_logs"])
            assert any(t["task_uuid"] == task_uuid for t in mon["recent_tasks"])
    finally:
        # Clean up synthetic test records from PostgreSQL so user dashboard stays clean
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AgentDecisionLog).where(AgentDecisionLog.agent_uuid == test_uuid))
            await session.execute(delete(AgentDecisionLog).where(AgentDecisionLog.hostname == "LAB-PEER-WIN11"))
            await session.execute(delete(AgentTask).where(AgentTask.agent_uuid == test_uuid))
            await session.execute(delete(EndpointTelemetrySnapshot).where(EndpointTelemetrySnapshot.agent_uuid == test_uuid))
            await session.execute(delete(EndpointSyncEvent).where(EndpointSyncEvent.event_uuid == sync_ev_uuid))
            await session.execute(delete(Incident).where(Incident.sync_idempotency_key == sync_ev_uuid))
            await session.execute(delete(Endpoint).where(Endpoint.agent_uuid == test_uuid))
            await session.commit()
