"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiRequest, getCurrentUser } from "@/lib/api";
import TelemetryChart, { TelemetryPoint } from "@/components/TelemetryChart";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  Check,
  Clock,
  Copy,
  Cpu,
  Globe,
  HardDrive,
  History,
  Laptop,
  LogIn,
  Monitor,
  Network,
  Play,
  PlusCircle,
  Radio,
  RefreshCw,
  Search,
  Server,
  Shield,
  Terminal,
  Wifi,
  Wrench,
} from "lucide-react";

type ActiveTab = "overview" | "decisions" | "history";

const REMOTE_ACTIONS = [
  {
    tool_id: "diagnose_and_auto_remediate",
    label: "Full Diagnose, Auto-Fix & Verify",
    description: "Collects live telemetry, runs rules, safely fixes static IP/DNS/adapter/services, and verifies.",
  },
  {
    tool_id: "collect_network_status",
    label: "Live Network & Service Telemetry Probe",
    description: "Runs non-destructive Windows diagnostic probe and logs health reasoning.",
  },
  {
    tool_id: "renew_dhcp",
    label: "Switch Static IP -> DHCP & Renew Lease",
    description: "Re-enables automatic DHCP addressing on primary adapter and verifies valid IPv4 + gateway.",
  },
  {
    tool_id: "flush_dns_cache",
    label: "Reset Static DNS -> DHCP & Flush Cache",
    description: "Clears manual DNS entries back to automatic DHCP DNS, flushes cache, and verifies DNS lookup.",
  },
  {
    tool_id: "enable_adapter",
    label: "Enable Primary Network Adapter",
    description: "Enables disabled Wi-Fi/Ethernet adapter cleanly on target endpoint.",
  },
  {
    tool_id: "restart_approved_service",
    label: "Restart Approved Windows Service",
    description: "Safely restarts Dhcp, Dnscache, or Spooler service on the target system.",
  },
  {
    tool_id: "test_gateway",
    label: "Ping Default Gateway Probe",
    description: "Tests local router reachability, RTT latency, and packet loss.",
  },
  {
    tool_id: "test_dns",
    label: "Test Domain DNS Resolution",
    description: "Tests domain name lookup and active DNS configuration.",
  },
];

function formatClock(iso?: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getDecisionStyle(decisionType: string, outcome: string) {
  const dt = (decisionType || "").toUpperCase();
  const out = (outcome || "").toUpperCase();
  if (dt === "AUTO_REMEDIATED" || out === "FIXED" || out === "VERIFIED_RESOLVED" || out === "RESOLVED") {
    return {
      border: "border-l-emerald-500",
      badge: "bg-emerald-100 text-emerald-800 border-emerald-200",
    };
  }
  if (dt === "ESCALATED" || dt === "POLICY_BLOCKED" || out === "ESCALATED" || out === "REJECTED" || out === "FAILED" || out === "NOT_RESOLVED") {
    return {
      border: "border-l-rose-500",
      badge: "bg-rose-100 text-rose-800 border-rose-200",
    };
  }
  if (dt === "REMOTE_EXECUTED") {
    return {
      border: "border-l-sky-600",
      badge: "bg-sky-100 text-sky-800 border-sky-200",
    };
  }
  if (dt === "AI_HYPOTHESIS" || dt === "RULE_DIAGNOSIS") {
    return {
      border: "border-l-indigo-500",
      badge: "bg-indigo-100 text-indigo-800 border-indigo-200",
    };
  }
  if (out === "PROPOSED") {
    return {
      border: "border-l-amber-500",
      badge: "bg-amber-100 text-amber-800 border-amber-200",
    };
  }
  return {
    border: "border-l-slate-400",
    badge: "bg-slate-100 text-slate-700 border-slate-200",
  };
}

export default function DashboardPage() {
  const [monitor, setMonitor] = useState<any>(null);
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [livePolling, setLivePolling] = useState(true);
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");
  const [user, setUser] = useState<any>(null);

  // Command Center states
  const [cmdTarget, setCmdTarget] = useState<string>("");
  const [cmdTool, setCmdTool] = useState<string>("diagnose_and_auto_remediate");
  const [cmdServiceName, setCmdServiceName] = useState<string>("Dhcp");
  const [cmdReason, setCmdReason] = useState<string>("Operator health sweep from Central Monitoring Console");
  const [cmdDispatching, setCmdDispatching] = useState(false);
  const [cmdError, setCmdError] = useState<string | null>(null);
  const [trackedTasks, setTrackedTasks] = useState<any[]>([]);
  const [showJoinHelp, setShowJoinHelp] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState(false);
  const [collectingProbe, setCollectingProbe] = useState(false);

  // Filters for decision logs
  const [feedFilter, setFeedFilter] = useState<string>("ALL");
  const [decisionSearch, setDecisionSearch] = useState<string>("");
  const [actorFilter, setActorFilter] = useState<string>("ALL");
  const [expandedEvidenceId, setExpandedEvidenceId] = useState<number | null>(null);

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasLoadedRef = useRef<boolean>(false);

  useEffect(() => {
    setUser(getCurrentUser());
    if (typeof window !== "undefined") {
      const qs = new URLSearchParams(window.location.search);
      const ag = qs.get("agent");
      if (ag) setSelectedAgent(ag);
    }
  }, []);

  const fetchMonitor = useCallback(
    async (agentOverride?: string, silent: boolean = false) => {
      if (!silent) {
        setRefreshing(true);
      }
      setError("");
      setErrorStatus(null);
      try {
        const targetUuid = agentOverride !== undefined ? agentOverride : selectedAgent;
        const query = targetUuid ? `?agent_uuid=${encodeURIComponent(targetUuid)}&limit=40` : "?limit=40";
        const data = await apiRequest(`/dashboard/monitor${query}`);
        setMonitor(data);
        hasLoadedRef.current = true;
        if (!selectedAgent && data?.selected_agent_uuid) {
          setSelectedAgent(data.selected_agent_uuid);
        }
        setCmdTarget((prev) => prev || data?.selected_agent_uuid || "__ALL_ONLINE__");
      } catch (err: any) {
        if (!hasLoadedRef.current || !silent) {
          setError(err?.message || "Failed to load monitoring telemetry");
          setErrorStatus(err?.status ?? null);
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [selectedAgent]
  );

  // Initial load & when selectedAgent changes
  useEffect(() => {
    fetchMonitor(selectedAgent, hasLoadedRef.current);
  }, [selectedAgent, fetchMonitor]);

  // Live 5s polling loop
  useEffect(() => {
    if (!livePolling) return;
    const id = setInterval(() => {
      fetchMonitor(selectedAgent, true);
    }, 5000);
    return () => clearInterval(id);
  }, [livePolling, selectedAgent, fetchMonitor]);

  // Poll pending dispatched tasks every 1.2s until finished
  useEffect(() => {
    const hasPending = trackedTasks.some((t) => t.status === "PENDING" || t.status === "DISPATCHED");
    if (!hasPending) {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      return;
    }

    let attempts = 0;
    const interval = setInterval(async () => {
      attempts += 1;
      try {
        const updates = await Promise.all(
          trackedTasks.map(async (t) => {
            if (t.status === "COMPLETED" || t.status === "FAILED" || t.status === "REJECTED") {
              return t;
            }
            return await apiRequest(`/agents/tasks/${encodeURIComponent(t.task_uuid)}`);
          })
        );
        setTrackedTasks(updates);
        const nowDone = updates.every((t) => t.status === "COMPLETED" || t.status === "FAILED" || t.status === "REJECTED");
        if (nowDone || attempts >= 22) {
          clearInterval(interval);
          fetchMonitor(selectedAgent, true);
        }
      } catch {
        // Ignore transient poll errors
      }
    }, 1200);
    pollTimerRef.current = interval;
    return () => clearInterval(interval);
  }, [trackedTasks, selectedAgent, fetchMonitor]);

  const handleAgentSelect = (uuid: string) => {
    setSelectedAgent(uuid);
    setCmdTarget(uuid || "__ALL_ONLINE__");
  };

  const handleCollectProbe = async () => {
    setCollectingProbe(true);
    setCmdError(null);
    try {
      const res = await apiRequest("/dashboard/collect-probe", {
        method: "POST",
        timeoutMs: 25000,
        body: JSON.stringify({
          agent_uuid: selectedAgent || null,
          mode: "auto",
        }),
      });
      if (res?.mode === "REMOTE_DISPATCHED" && res?.task) {
        setTrackedTasks([res.task]);
      } else {
        await fetchMonitor(selectedAgent, true);
      }
    } catch (err: any) {
      setCmdError(err?.message || "Failed to collect live sample.");
    } finally {
      setCollectingProbe(false);
    }
  };

  const handleExecuteCommand = async () => {
    setCmdDispatching(true);
    setCmdError(null);
    try {
      const args: Record<string, any> = {};
      if (cmdTool === "restart_approved_service") {
        args.service_name = cmdServiceName;
      }

      if (cmdTarget === "__ALL_ONLINE__" || !cmdTarget) {
        const res = await apiRequest("/agents/broadcast-task", {
          method: "POST",
          body: JSON.stringify({
            tool_id: cmdTool,
            arguments: args,
            reason: cmdReason || "Fleet LAN broadcast from Dashboard",
          }),
        });
        setTrackedTasks(res?.tasks || []);
      } else {
        const task = await apiRequest(`/agents/${encodeURIComponent(cmdTarget)}/tasks`, {
          method: "POST",
          body: JSON.stringify({
            tool_id: cmdTool,
            arguments: args,
            reason: cmdReason || "Remote command from Dashboard",
          }),
        });
        setTrackedTasks([task]);
      }
      await fetchMonitor(selectedAgent, true);
    } catch (err: any) {
      setCmdError(err?.message || "Failed to dispatch task to LAN agent.");
    } finally {
      setCmdDispatching(false);
    }
  };

  const handleCopyJoinCommand = async () => {
    const cmd = monitor?.server_status?.join_command;
    if (!cmd || typeof navigator === "undefined") return;
    try {
      await navigator.clipboard.writeText(cmd);
      setCopiedCmd(true);
      setTimeout(() => setCopiedCmd(false), 2000);
    } catch {
      // Clipboard blocked
    }
  };

  const endpoints: any[] = useMemo(() => monitor?.endpoints || [], [monitor]);
  const activeEndpoint = useMemo(
    () => endpoints.find((e) => e.agent_uuid === selectedAgent) || endpoints[0] || null,
    [endpoints, selectedAgent]
  );

  const serverStatus = monitor?.server_status || {};
  const overview = monitor?.overview || {};
  const latestTelemetry = monitor?.latest_telemetry || {};
  const latestMetrics = monitor?.latest_metrics || activeEndpoint?.metrics || null;
  const latestProvenance = monitor?.latest_provenance || {};
  const timeSeries: TelemetryPoint[] = monitor?.time_series || [];
  const decisionLogs: any[] = monitor?.decision_logs || [];
  const recentTasks: any[] = monitor?.recent_tasks || [];

  const filteredRightFeed = useMemo(() => {
    if (feedFilter === "ACTIONS") {
      return decisionLogs.filter((d) =>
        ["AUTO_REMEDIATED", "REMOTE_EXECUTED"].includes((d.decision_type || "").toUpperCase())
      );
    }
    if (feedFilter === "AI_RULES") {
      return decisionLogs.filter((d) =>
        ["AI_HYPOTHESIS", "RULE_DIAGNOSIS"].includes((d.decision_type || "").toUpperCase())
      );
    }
    if (feedFilter === "ESCALATIONS") {
      return decisionLogs.filter((d) =>
        ["ESCALATED", "POLICY_BLOCKED"].includes((d.decision_type || "").toUpperCase())
      );
    }
    return decisionLogs;
  }, [decisionLogs, feedFilter]);

  const fullFilteredLogs = useMemo(() => {
    return decisionLogs.filter((d) => {
      if (actorFilter !== "ALL" && (d.actor_source || "").toUpperCase() !== actorFilter) {
        return false;
      }
      if (decisionSearch.trim()) {
        const q = decisionSearch.toLowerCase();
        const hay = `${d.hostname || ""} ${d.action_taken || ""} ${d.rule_or_model || ""} ${d.why_explanation || ""} ${d.observed_state || ""}`.toLowerCase();
        return hay.includes(q);
      }
      return true;
    });
  }, [decisionLogs, actorFilter, decisionSearch]);

  if (loading && !monitor) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[420px] space-y-3">
        <div className="animate-spin rounded-full h-9 w-9 border-b-2 border-sky-600"></div>
        <div className="text-xs text-slate-500 font-medium">Loading live network &amp; endpoint telemetry...</div>
      </div>
    );
  }

  if (error && !monitor) {
    return (
      <div className="max-w-lg mx-auto bg-white p-8 rounded-xl border border-slate-200 shadow-sm text-center space-y-3">
        <AlertCircle className="w-8 h-8 text-rose-500 mx-auto" />
        <h2 className="text-base font-bold text-slate-900">Unable to load Monitoring Dashboard</h2>
        <p className="text-xs text-rose-600">{error}</p>
        <div className="flex justify-center gap-2 pt-1">
          <button
            onClick={() => fetchMonitor(selectedAgent, false)}
            className="px-4 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold"
          >
            Retry
          </button>
          {errorStatus === 401 && (
            <Link
              href="/login"
              className="inline-flex items-center px-4 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold"
            >
              <LogIn className="w-3.5 h-3.5 mr-1.5" />
              Sign In
            </Link>
          )}
        </div>
      </div>
    );
  }

  const onlineEndpoints = endpoints.filter((e) => e.status === "ONLINE" && !e.stale);
  const healthScore = latestMetrics?.health_score ?? 100;
  const servicesMap: Record<string, any> = latestTelemetry?.services || {};
  const serviceOrder = ["Dhcp", "Dnscache", "Spooler", "WlanSvc"];
  const adaptersList: any[] = latestTelemetry?.adapters_list || [];
  const firewallMap: Record<string, boolean> = latestTelemetry?.firewall || {};
  const dnsServers: string[] = latestTelemetry?.ip_config?.dns_servers || latestTelemetry?.dns_test?.dns_servers || [];
  const openTickets = (overview.new_incidents || 0) + (overview.in_progress || 0);
  const canExecuteCommands = user?.role === "technician" || user?.role === "admin";
  const selectedToolMeta = REMOTE_ACTIONS.find((a) => a.tool_id === cmdTool);

  return (
    <div className="space-y-6">
      {/* SECTION 1: TOP COMMAND & FLEET HEALTH BAR (Ref 1 Top) */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-sky-600 text-white flex items-center justify-center shadow-sm shrink-0">
              <Network className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900 tracking-tight">
                AISD Network &amp; Endpoint Intelligence
              </h1>
              <p className="text-xs text-slate-500">
                Real-time multi-system LAN telemetry, autonomous remediation execution, and AI/rule decision logs
              </p>
            </div>
          </div>

          <Link
            href="/incidents/new"
            className="inline-flex items-center px-3.5 py-2 bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold rounded-lg shadow-sm transition whitespace-nowrap"
          >
            <PlusCircle className="w-3.5 h-3.5 mr-1.5" />
            New Incident
          </Link>
        </div>

        {/* Selector + Health Pills + Live Polling Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-100">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex items-center gap-1.5">
              <Laptop className="w-4 h-4 text-slate-400" />
              <select
                aria-label="Target Endpoint System"
                value={selectedAgent}
                onChange={(e) => handleAgentSelect(e.target.value)}
                className="text-xs font-semibold text-slate-800 bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-sky-500"
              >
                {endpoints.length === 0 ? (
                  <option value="">No enrolled systems yet (Collect Probe to auto-register)</option>
                ) : (
                  endpoints.map((ep) => (
                    <option key={ep.agent_uuid} value={ep.agent_uuid}>
                      {ep.hostname} &bull; {ep.ip_address || "IP unknown"} [
                      {ep.status === "ONLINE" && !ep.stale ? "ONLINE" : ep.stale ? "STALE" : ep.status}]
                    </option>
                  ))
                )}
              </select>
            </div>

            {latestMetrics && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-100 text-slate-700 border border-slate-200">
                <Wifi className="w-3 h-3 text-sky-600" />
                {latestMetrics.adapter_name || "Adapter"} &bull;{" "}
                {latestMetrics.dhcp_enabled === false ? "STATIC IP" : "DHCP AUTO"}
              </span>
            )}

            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              API: {serverStatus.api || "HEALTHY"}
            </span>

            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
              <HardDrive className="w-3 h-3" />
              DB: {serverStatus.database || "CONNECTED"}
            </span>

            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${
                serverStatus.ollama_reachable
                  ? "bg-indigo-50 text-indigo-700 border-indigo-200"
                  : "bg-amber-50 text-amber-800 border-amber-200"
              }`}
              title={
                serverStatus.ollama_reachable
                  ? `Ollama ${serverStatus.ollama_model} connected`
                  : "Ollama unreachable - deterministic local rule fallback active"
              }
            >
              <Cpu className="w-3 h-3" />
              LLM: {serverStatus.ollama_model || "llama3.1:8b"}
              {serverStatus.ollama_reachable ? "" : " (Fallback)"}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setLivePolling((p) => !p)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
                livePolling
                  ? "bg-sky-600 text-white border-sky-600 shadow-sm"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
            >
              <Radio className={`w-3.5 h-3.5 ${livePolling ? "animate-pulse" : ""}`} />
              {livePolling ? "Live Polling (5s)" : "Polling Paused"}
            </button>

            <button
              type="button"
              onClick={() => fetchMonitor(selectedAgent, false)}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 disabled:opacity-60 transition"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>

            {canExecuteCommands && (
              <button
                type="button"
                onClick={handleCollectProbe}
                disabled={collectingProbe}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white disabled:opacity-60 transition"
              >
                <Activity className={`w-3.5 h-3.5 ${collectingProbe ? "animate-spin" : ""}`} />
                {collectingProbe ? "Probing..." : "Collect Sample"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* SECTION 2: REMOTE & SAME-NETWORK LAN COMMAND ENGINE (Ref 1 Mid Card) */}
      <div className="bg-white rounded-xl border border-slate-200 border-l-4 border-l-sky-600 shadow-sm p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-sky-600" />
            <h2 className="text-sm font-bold text-slate-900">
              Remote &amp; Same-Network LAN Execution Console
            </h2>
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-sky-50 text-sky-700 border border-sky-200">
              Same-Network 3s Fast Poll
            </span>
          </div>

          <button
            type="button"
            onClick={() => setShowJoinHelp((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-sky-700 hover:text-sky-800 bg-sky-50 hover:bg-sky-100 px-3 py-1.5 rounded-lg border border-sky-200 transition"
          >
            <Server className="w-3.5 h-3.5" />
            {showJoinHelp ? "Hide LAN Join Setup" : `Connect Other PCs on LAN (${serverStatus.primary_lan_ip || "LAN"})`}
          </button>
        </div>

        {/* LAN Join Help Drawer */}
        {showJoinHelp && (
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3.5 space-y-2 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-bold text-slate-800">
                Add any Windows system on this Wi-Fi / campus subnet to the live fleet:
              </div>
              <div className="text-[11px] text-slate-500">
                Server LAN IP(s):{" "}
                <span className="font-mono font-semibold text-slate-800">
                  {(serverStatus.lan_ips || [serverStatus.primary_lan_ip]).filter(Boolean).join(", ")}
                </span>{" "}
                &bull; Port <span className="font-mono font-semibold">{serverStatus.backend_port || 8000}</span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <code className="flex-1 min-w-[260px] bg-white border border-slate-200 rounded px-3 py-1.5 font-mono text-[11px] text-slate-800">
                {serverStatus.join_command || "python agent.py --server http://<SERVER_LAN_IP>:8000 daemon"}
              </code>
              <button
                type="button"
                onClick={handleCopyJoinCommand}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-semibold text-[11px]"
              >
                {copiedCmd ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                {copiedCmd ? "Copied" : "Copy Command"}
              </button>
            </div>
            <p className="text-[11px] text-slate-500">
              On another Windows PC on the same LAN, copy <code className="font-mono bg-white px-1 rounded">endpoint-agent/</code>, run{" "}
              <code className="font-mono bg-white px-1 rounded">JOIN_LAN_AGENT.bat</code> as Administrator (or the command above), and allow port{" "}
              <code className="font-mono bg-white px-1 rounded">8000</code> in Windows Defender Firewall on this central server.
            </p>
          </div>
        )}

        {/* 3-Column Execution Controls */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3.5">
          <div className="md:col-span-4 space-y-1">
            <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Target System(s) on Network
            </label>
            <select
              value={cmdTarget}
              onChange={(e) => setCmdTarget(e.target.value)}
              className="w-full text-xs font-medium text-slate-800 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              <option value="__ALL_ONLINE__">
                All Online Systems on Same Network ({onlineEndpoints.length} online)
              </option>
              {endpoints.map((ep) => (
                <option key={ep.agent_uuid} value={ep.agent_uuid}>
                  {ep.hostname} ({ep.ip_address || "IP N/A"}) —{" "}
                  {ep.status === "ONLINE" && !ep.stale ? "ONLINE" : ep.stale ? "STALE" : ep.status}
                </option>
              ))}
            </select>
          </div>

          <div className={`${cmdTool === "restart_approved_service" ? "md:col-span-3" : "md:col-span-4"} space-y-1`}>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Allowlisted Task / Remediation
            </label>
            <select
              value={cmdTool}
              onChange={(e) => setCmdTool(e.target.value)}
              className="w-full text-xs font-medium text-slate-800 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              {REMOTE_ACTIONS.map((a) => (
                <option key={a.tool_id} value={a.tool_id}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>

          {cmdTool === "restart_approved_service" && (
            <div className="md:col-span-2 space-y-1">
              <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500">
                Service
              </label>
              <select
                value={cmdServiceName}
                onChange={(e) => setCmdServiceName(e.target.value)}
                className="w-full text-xs font-medium text-slate-800 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-sky-500"
              >
                <option value="Dhcp">Dhcp (DHCP Client)</option>
                <option value="Dnscache">Dnscache (DNS Client)</option>
                <option value="Spooler">Spooler (Print Spooler)</option>
              </select>
            </div>
          )}

          <div className={`${cmdTool === "restart_approved_service" ? "md:col-span-3" : "md:col-span-4"} space-y-1`}>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Reason / Decision Context
            </label>
            <input
              type="text"
              value={cmdReason}
              onChange={(e) => setCmdReason(e.target.value)}
              placeholder="e.g., Fix static DNS or verify DHCP lease across lab"
              className="w-full text-xs text-slate-800 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[11px] text-slate-500">
            <span className="font-semibold text-slate-700">Policy Scope:</span> {selectedToolMeta?.description}
          </p>

          {!canExecuteCommands && (
            <span className="text-[11px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded">
              Technician or Admin sign-in required for remote execution
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={handleExecuteCommand}
          disabled={cmdDispatching || !canExecuteCommands || endpoints.length === 0}
          className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-700 disabled:bg-slate-300 disabled:text-slate-500 text-white text-xs font-bold shadow-sm transition"
        >
          <Play className="w-3.5 h-3.5" />
          {cmdDispatching
            ? "Dispatching Task to Target System(s)..."
            : cmdTarget === "__ALL_ONLINE__"
            ? `Execute '${cmdTool}' on All Online LAN Systems (${onlineEndpoints.length})`
            : `Execute '${cmdTool}' on Selected LAN System`}
        </button>

        {cmdError && (
          <div className="bg-rose-50 border border-rose-200 rounded-lg px-3.5 py-2 text-xs text-rose-700 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{cmdError}</span>
          </div>
        )}

        {/* Inline Live Dispatched Task Tracker */}
        {trackedTasks.length > 0 && (
          <div className="space-y-2 pt-1">
            {trackedTasks.map((t) => (
              <div
                key={t.task_uuid}
                className={`rounded-lg border p-3 text-xs space-y-1.5 ${
                  t.status === "COMPLETED"
                    ? "bg-emerald-50/60 border-emerald-200"
                    : t.status === "FAILED" || t.status === "REJECTED"
                    ? "bg-rose-50/60 border-rose-200"
                    : "bg-sky-50/60 border-sky-200"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-slate-900">{t.target_hostname}</span>
                    <span className="font-mono text-[11px] bg-white px-2 py-0.5 rounded border border-slate-200 text-slate-700">
                      {t.tool_id}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        t.status === "COMPLETED"
                          ? "bg-emerald-100 text-emerald-800"
                          : t.status === "FAILED"
                          ? "bg-rose-100 text-rose-800"
                          : "bg-amber-100 text-amber-800 animate-pulse"
                      }`}
                    >
                      {t.status}
                      {t.verification_status ? ` • ${t.verification_status}` : ""}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-500">{t.task_uuid}</span>
                </div>

                {t.result?.why_explanation && (
                  <p className="text-slate-700">
                    <span className="font-bold text-slate-900">Why &amp; Outcome: </span>
                    {t.result.why_explanation}
                  </p>
                )}
                {(t.output_text || t.error_text) && (
                  <pre className="bg-white/90 border border-slate-200 rounded p-2 text-[11px] font-mono text-slate-700 max-h-28 overflow-auto whitespace-pre-wrap">
                    {t.error_text || t.output_text}
                  </pre>
                )}
                {(t.status === "PENDING" || t.status === "DISPATCHED") && (
                  <p className="text-[11px] text-sky-700">
                    Waiting for {t.target_hostname} daemon (polls every 3s) to execute &amp; return verification...
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* SECTION 3: 3-TAB SUB-NAVIGATION (Ref 2 Top) */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex items-center bg-white p-1 rounded-xl border border-slate-200 shadow-sm text-xs font-semibold">
          <button
            type="button"
            onClick={() => setActiveTab("overview")}
            className={`px-4 py-2 rounded-lg transition flex items-center gap-1.5 ${
              activeTab === "overview" ? "bg-sky-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            Telemetry Overview
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("decisions")}
            className={`px-4 py-2 rounded-lg transition flex items-center gap-1.5 ${
              activeTab === "decisions" ? "bg-sky-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            Decision Reasoning &amp; Logs
            <span
              className={`px-1.5 py-0.5 rounded-full text-[10px] ${
                activeTab === "decisions" ? "bg-sky-500 text-white" : "bg-slate-100 text-slate-700"
              }`}
            >
              {decisionLogs.length}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("history")}
            className={`px-4 py-2 rounded-lg transition flex items-center gap-1.5 ${
              activeTab === "history" ? "bg-sky-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <History className="w-3.5 h-3.5" />
            Incidents &amp; Telemetry History
          </button>
        </div>

        <Link href="/incidents" className="text-xs text-sky-600 hover:text-sky-700 font-semibold flex items-center">
          Open Incident Queue ({openTickets} Open) <ArrowUpRight className="w-3.5 h-3.5 ml-1" />
        </Link>
      </div>

      {/* TAB 1: TELEMETRY OVERVIEW (Refs 2 & 3) */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* 6 KPI CARDS */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3.5">
            {/* KPI 1: Health & IPv4 */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase">
                <span>Health &amp; IPv4</span>
                <Wifi className={`w-4 h-4 ${healthScore >= 80 ? "text-emerald-500" : healthScore >= 50 ? "text-amber-500" : "text-rose-500"}`} />
              </div>
              <div className="flex items-baseline gap-1">
                <span
                  className={`text-2xl font-bold ${
                    healthScore >= 80 ? "text-emerald-600" : healthScore >= 50 ? "text-amber-600" : "text-rose-600"
                  }`}
                >
                  {latestMetrics ? `${healthScore}%` : "--"}
                </span>
                <span className="text-[11px] text-slate-400 font-medium">score</span>
              </div>
              <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    healthScore >= 80 ? "bg-emerald-500" : healthScore >= 50 ? "bg-amber-500" : "bg-rose-500"
                  }`}
                  style={{ width: `${latestMetrics ? healthScore : 0}%` }}
                />
              </div>
              <div className="text-[11px] font-mono text-slate-600 truncate">
                {latestMetrics?.ip_address || activeEndpoint?.ip_address || "No IP"} &bull;{" "}
                <span className={latestMetrics?.dhcp_enabled === false ? "text-rose-600 font-bold" : "text-emerald-700 font-semibold"}>
                  {latestMetrics?.dhcp_enabled === false ? "Static IP" : "DHCP"}
                </span>
              </div>
            </div>

            {/* KPI 2: Gateway RTT */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase">
                <span>Gateway RTT</span>
                <Network className="w-4 h-4 text-sky-600" />
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-bold text-slate-900">
                  {latestMetrics?.gateway_latency_ms != null
                    ? `${latestMetrics.gateway_latency_ms}`
                    : latestMetrics?.gateway_reachable === false
                    ? "FAIL"
                    : "--"}
                </span>
                {latestMetrics?.gateway_latency_ms != null && (
                  <span className="text-xs text-slate-500 font-semibold">ms</span>
                )}
              </div>
              <div className="text-[11px] text-slate-500 truncate">
                GW: <span className="font-mono text-slate-700">{latestMetrics?.gateway_ip || "None"}</span>
              </div>
              <div className="text-[11px] text-slate-400">
                Loss: <span className="font-semibold text-slate-700">{latestMetrics?.gateway_loss_pct ?? 0}%</span>
              </div>
            </div>

            {/* KPI 3: Internet WAN RTT */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase">
                <span>Internet WAN</span>
                <Globe className="w-4 h-4 text-indigo-600" />
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-bold text-slate-900">
                  {latestMetrics?.internet_latency_ms != null
                    ? `${latestMetrics.internet_latency_ms}`
                    : latestMetrics?.internet_reachable === false
                    ? "DOWN"
                    : "--"}
                </span>
                {latestMetrics?.internet_latency_ms != null && (
                  <span className="text-xs text-slate-500 font-semibold">ms</span>
                )}
              </div>
              <div className="text-[11px] text-slate-500">Target: <span className="font-mono">8.8.8.8</span></div>
              <div className="text-[11px] text-slate-400">
                Loss: <span className="font-semibold text-slate-700">{latestMetrics?.internet_loss_pct ?? 0}%</span>
              </div>
            </div>

            {/* KPI 4: DNS Mode & Lookup */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase">
                <span>DNS Mode</span>
                <Shield
                  className={`w-4 h-4 ${
                    latestMetrics?.static_dns_configured ? "text-amber-500" : "text-emerald-500"
                  }`}
                />
              </div>
              <div
                className={`text-xl font-bold ${
                  !latestMetrics
                    ? "text-slate-900"
                    : latestMetrics.static_dns_configured
                    ? "text-amber-600"
                    : latestMetrics.dns_resolved === false
                    ? "text-rose-600"
                    : "text-emerald-600"
                }`}
              >
                {!latestMetrics
                  ? "--"
                  : latestMetrics.static_dns_configured
                  ? "Manual DNS"
                  : latestMetrics.dns_resolved
                  ? "DHCP OK"
                  : "DNS Fail"}
              </div>
              <div className="text-[11px] font-mono text-slate-500 truncate" title={dnsServers.join(", ")}>
                {dnsServers.length > 0 ? dnsServers.join(", ") : "Auto resolver"}
              </div>
              <div className="text-[11px] text-slate-400">
                Lookup: <span className="font-semibold text-slate-700">{latestMetrics?.dns_resolved ? "Resolved" : "Unverified"}</span>
              </div>
            </div>

            {/* KPI 5: Core Windows Services */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase">
                <span>Win Services</span>
                <Wrench className="w-4 h-4 text-sky-600" />
              </div>
              <div className="text-2xl font-bold text-slate-900">
                {latestMetrics ? `${latestMetrics.services_running_count}/${latestMetrics.services_total_count}` : "--"}
              </div>
              <div className="flex flex-wrap gap-1">
                {serviceOrder.map((srv) => {
                  const st = String(servicesMap?.[srv]?.status || "").toLowerCase();
                  const up = st === "running";
                  return (
                    <span
                      key={srv}
                      className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                        !latestMetrics
                          ? "bg-slate-100 text-slate-500"
                          : up
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                          : "bg-rose-50 text-rose-700 border border-rose-200"
                      }`}
                    >
                      {srv}
                    </span>
                  );
                })}
              </div>
            </div>

            {/* KPI 6: Provenance & Fleet */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-2">
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase">
                <span>Telemetry Feed</span>
                <Clock className="w-4 h-4 text-slate-500" />
              </div>
              <div className="text-sm font-bold text-slate-900 truncate">
                {latestProvenance?.source_mode || "WAITING"}
              </div>
              <div className="text-[11px] text-slate-500">
                Updated: <span className="font-medium text-slate-700">{formatClock(latestProvenance?.recorded_at)}</span>
              </div>
              <div className="text-[11px] text-indigo-600 font-semibold">
                {onlineEndpoints.length}/{endpoints.length} LAN Online
              </div>
            </div>
          </div>

          {/* TIME-SERIES TELEMETRY CHART */}
          <TelemetryChart
            data={timeSeries}
            onCollectSample={canExecuteCommands ? handleCollectProbe : undefined}
            collecting={collectingProbe}
          />

          {/* BOTTOM SPLIT ROW (Ref 3) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* LEFT PANEL: Network Topology, Interfaces & Operations Summary */}
            <div className="lg:col-span-5 bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-5 flex flex-col justify-between">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Monitor className="w-4 h-4 text-sky-600" />
                    <h2 className="text-sm font-bold text-slate-900">
                      Network Topology &amp; Operations Summary
                    </h2>
                  </div>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${
                      activeEndpoint?.status === "ONLINE" && !activeEndpoint?.stale
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : "bg-amber-50 text-amber-800 border-amber-200"
                    }`}
                  >
                    {activeEndpoint?.hostname || "Local Host"}
                  </span>
                </div>

                {/* Big Hero Endpoint Readout */}
                <div className="bg-slate-50 rounded-lg border border-slate-200 p-3.5 space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="text-2xl font-bold text-slate-900 font-mono">
                      {latestMetrics?.ip_address || activeEndpoint?.ip_address || "0.0.0.0"}
                    </div>
                    <span className="text-xs font-semibold text-slate-500">
                      {activeEndpoint?.os_name} {activeEndpoint?.os_version}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-600">
                    Adapter: <span className="font-semibold text-slate-800">{latestMetrics?.adapter_name || activeEndpoint?.adapter_name || "N/A"}</span> &bull;{" "}
                    MAC: <span className="font-mono text-slate-700">{activeEndpoint?.mac_address || latestTelemetry?.network_adapter?.mac_address || "N/A"}</span>
                  </div>
                </div>

                {/* Adapters List */}
                <div className="space-y-2">
                  <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    Windows Network Interfaces
                  </div>
                  <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                    {adaptersList.length === 0 ? (
                      <div className="text-xs text-slate-400">Run probe to inspect host adapters.</div>
                    ) : (
                      adaptersList
                        .filter((a) => !a.is_virtual || String(a.status).toLowerCase() === "up")
                        .slice(0, 6)
                        .map((a, idx) => (
                          <div
                            key={`${a.name}-${idx}`}
                            className="flex items-center justify-between text-xs bg-slate-50/70 border border-slate-100 rounded-lg px-2.5 py-1.5"
                          >
                            <div className="min-w-0 pr-2">
                              <div className="font-semibold text-slate-800 truncate">{a.name}</div>
                              <div className="text-[10px] text-slate-400 truncate">{a.description}</div>
                            </div>
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold shrink-0 ${
                                String(a.status).toLowerCase() === "up"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : "bg-slate-200 text-slate-600"
                              }`}
                            >
                              {a.status}
                            </span>
                          </div>
                        ))
                    )}
                  </div>
                </div>

                {/* Firewall Profiles */}
                {Object.keys(firewallMap).length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                      Firewall:
                    </span>
                    {Object.entries(firewallMap).map(([prof, enabled]) => (
                      <span
                        key={prof}
                        className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                          enabled
                            ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                            : "bg-amber-50 text-amber-800 border-amber-200"
                        }`}
                      >
                        {prof}: {enabled ? "ON" : "OFF"}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* 3 Sub-KPI Boxes (Ref 3 Bottom Left) */}
              <div className="grid grid-cols-3 gap-2.5 pt-3 border-t border-slate-100">
                <div className="bg-slate-50 rounded-lg border border-slate-200 p-3">
                  <div className="text-[10px] font-semibold text-slate-500">Total Tickets</div>
                  <div className="text-lg font-bold text-sky-600 mt-0.5">{overview.total_incidents || 0}</div>
                  <div className="text-[10px] text-slate-400">{openTickets} active</div>
                </div>
                <div className="bg-slate-50 rounded-lg border border-slate-200 p-3">
                  <div className="text-[10px] font-semibold text-slate-500">Verified Fix Rate</div>
                  <div className="text-lg font-bold text-emerald-600 mt-0.5">
                    {overview.verified_remediation_rate_pct ?? 100}%
                  </div>
                  <div className="text-[10px] text-slate-400">{overview.resolved_incidents || 0} resolved</div>
                </div>
                <div className="bg-slate-50 rounded-lg border border-slate-200 p-3">
                  <div className="text-[10px] font-semibold text-slate-500">LAN Fleet</div>
                  <div className="text-lg font-bold text-indigo-600 mt-0.5">
                    {onlineEndpoints.length}/{endpoints.length}
                  </div>
                  <div className="text-[10px] text-slate-400">polling @ 3s</div>
                </div>
              </div>
            </div>

            {/* RIGHT PANEL: Agent Decision Logs & Anomaly Reasoning Feed (Ref 3 Right) */}
            <div className="lg:col-span-7 bg-white rounded-xl border border-slate-200 shadow-sm p-5 flex flex-col">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-emerald-600" />
                  <h2 className="text-sm font-bold text-slate-900">
                    Agent Decision Logs &amp; Anomaly Reasoning Feed
                  </h2>
                </div>

                <div className="flex items-center gap-2">
                  <div className="inline-flex bg-slate-100 p-0.5 rounded-lg border border-slate-200 text-[11px] font-semibold">
                    {[
                      { k: "ALL", label: "All" },
                      { k: "ACTIONS", label: "Actions" },
                      { k: "AI_RULES", label: "AI/Rules" },
                      { k: "ESCALATIONS", label: "Escalations" },
                    ].map((f) => (
                      <button
                        key={f.k}
                        type="button"
                        onClick={() => setFeedFilter(f.k)}
                        className={`px-2.5 py-1 rounded-md transition ${
                          feedFilter === f.k ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                        }`}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>
                  <span className="px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-50 text-amber-800 border border-amber-200 whitespace-nowrap">
                    {filteredRightFeed.length} LOGS
                  </span>
                </div>
              </div>

              <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                {filteredRightFeed.length === 0 ? (
                  <div className="py-16 text-center text-xs text-slate-400 border border-dashed border-slate-200 rounded-lg">
                    No agent decision logs recorded yet for this filter. Execute a probe, run AI diagnosis, or trigger a LAN task to view reasoning traces.
                  </div>
                ) : (
                  filteredRightFeed.map((log) => {
                    const st = getDecisionStyle(log.decision_type, log.outcome);
                    return (
                      <div
                        key={log.log_uuid || log.id}
                        className={`bg-slate-50/70 hover:bg-white rounded-lg border border-slate-200 border-l-4 ${st.border} p-3.5 transition space-y-1.5`}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono font-bold text-xs text-slate-900">
                              {log.action_taken || log.rule_or_model || "decision"}
                            </span>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold border uppercase ${st.badge}`}>
                              {log.decision_type}
                            </span>
                            {log.hostname && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-white border border-slate-200 text-slate-600">
                                {log.hostname}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-slate-400 font-medium whitespace-nowrap">
                            {formatDateTime(log.created_at)}
                          </span>
                        </div>

                        <p className="text-xs text-slate-700 leading-relaxed">
                          <span className="font-bold text-slate-900">Why agent decided this: </span>
                          {log.why_explanation}
                        </p>

                        <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[11px] text-slate-500">
                          <div className="truncate max-w-full sm:max-w-[72%]" title={`${log.observed_state || ""} | ${log.expected_state || ""}`}>
                            <span className="font-semibold text-slate-600">Observed:</span>{" "}
                            {log.observed_state || "N/A"}
                            {log.expected_state && (
                              <>
                                {" "}| <span className="font-semibold text-slate-600">Expected:</span> {log.expected_state}
                              </>
                            )}
                          </div>
                          <span className="text-[10px] font-mono bg-white border border-slate-200 px-2 py-0.5 rounded text-slate-600 shrink-0">
                            {log.actor_source}
                            {log.confidence != null ? ` • ${Math.round(log.confidence * 100)}%` : ""}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: FULL DECISION REASONING LOGS & LAN TASK QUEUE */}
      {activeTab === "decisions" && (
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-bold text-slate-900">
                  Full Agent Decision Audit &amp; Explainability Explorer
                </h2>
                <p className="text-xs text-slate-500">
                  Every autonomous remediation, Ollama llama3.1:8b hypothesis, deterministic rule evaluation, and remote LAN task decision
                </p>
              </div>
              <div className="relative w-full sm:w-64">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={decisionSearch}
                  onChange={(e) => setDecisionSearch(e.target.value)}
                  placeholder="Search hostname, tool, or reason..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {["ALL", "ONLINE_AGENT", "OFFLINE_AGENT", "OLLAMA_AI", "RULE_ENGINE", "REMEDIATION_ENGINE", "POLICY_ENGINE"].map(
                (src) => (
                  <button
                    key={src}
                    type="button"
                    onClick={() => setActorFilter(src)}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-semibold border transition ${
                      actorFilter === src
                        ? "bg-sky-600 text-white border-sky-600"
                        : "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100"
                    }`}
                  >
                    {src}
                  </button>
                )
              )}
            </div>

            <div className="space-y-3">
              {fullFilteredLogs.length === 0 ? (
                <div className="py-12 text-center text-xs text-slate-400">
                  No matching decision records found.
                </div>
              ) : (
                fullFilteredLogs.map((log) => {
                  const st = getDecisionStyle(log.decision_type, log.outcome);
                  const isOpen = expandedEvidenceId === log.id;
                  return (
                    <div
                      key={log.log_uuid || log.id}
                      className={`rounded-xl border border-slate-200 border-l-4 ${st.border} bg-white p-4 space-y-2`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono font-bold text-xs text-slate-900">
                            {log.action_taken || log.rule_or_model || "system_event"}
                          </span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold border uppercase ${st.badge}`}>
                            {log.decision_type} ({log.outcome})
                          </span>
                          <span className="text-[10px] font-mono bg-slate-100 text-slate-700 px-2 py-0.5 rounded">
                            {log.actor_source}
                          </span>
                          {log.hostname && (
                            <span className="text-[11px] font-semibold text-sky-700">{log.hostname}</span>
                          )}
                        </div>
                        <span className="text-[11px] text-slate-400">{formatDateTime(log.created_at)}</span>
                      </div>

                      <p className="text-xs text-slate-700 leading-relaxed">
                        <span className="font-bold text-slate-900">Why agent took this decision: </span>
                        {log.why_explanation}
                      </p>

                      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500 pt-1 border-t border-slate-100">
                        <div>
                          <span className="font-semibold text-slate-700">Observed:</span> {log.observed_state || "N/A"}{" "}
                          &bull; <span className="font-semibold text-slate-700">Expected:</span>{" "}
                          {log.expected_state || "N/A"}
                        </div>
                        <button
                          type="button"
                          onClick={() => setExpandedEvidenceId(isOpen ? null : log.id)}
                          className="text-sky-600 hover:text-sky-700 font-semibold"
                        >
                          {isOpen ? "Hide Evidence JSON" : "Inspect Evidence"}
                        </button>
                      </div>

                      {isOpen && (
                        <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-[11px] font-mono text-slate-700 overflow-x-auto">
                          {JSON.stringify(
                            { rule_or_model: log.rule_or_model, confidence: log.confidence, evidence: log.evidence },
                            null,
                            2
                          )}
                        </pre>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* REMOTE LAN TASK EXECUTION QUEUE TABLE */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                Recent LAN Remote Execution Queue ({recentTasks.length})
              </h3>
              <span className="text-[11px] text-slate-400">Updated live as targets reply</span>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-xs">
                <thead className="bg-slate-50 text-slate-500 uppercase text-[10px] font-bold">
                  <tr>
                    <th className="px-3 py-2 text-left">Target Host</th>
                    <th className="px-3 py-2 text-left">Command</th>
                    <th className="px-3 py-2 text-left">Reason / Trigger</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-left">Verification</th>
                    <th className="px-3 py-2 text-left">Requested</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {recentTasks.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-3 py-8 text-center text-slate-400">
                        No remote tasks dispatched yet. Use the LAN Execution Console above to execute tasks on connected systems.
                      </td>
                    </tr>
                  ) : (
                    recentTasks.map((t) => (
                      <tr key={t.task_uuid} className="hover:bg-slate-50">
                        <td className="px-3 py-2.5 font-semibold text-slate-900">{t.target_hostname}</td>
                        <td className="px-3 py-2.5 font-mono text-sky-700">{t.tool_id}</td>
                        <td className="px-3 py-2.5 text-slate-600 max-w-xs truncate" title={t.reason}>
                          {t.reason || "Manual trigger"}
                        </td>
                        <td className="px-3 py-2.5">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              t.status === "COMPLETED"
                                ? "bg-emerald-100 text-emerald-800"
                                : t.status === "FAILED"
                                ? "bg-rose-100 text-rose-800"
                                : "bg-amber-100 text-amber-800"
                            }`}
                          >
                            {t.status}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-slate-700 font-medium">{t.verification_status || "Pending"}</td>
                        <td className="px-3 py-2.5 text-slate-400 whitespace-nowrap">{formatDateTime(t.created_at)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: INCIDENTS & HISTORICAL TELEMETRY RECORDS (Ref 2 Tab 3 + Existing Breakdown) */}
      {activeTab === "history" && (
        <div className="space-y-6">
          {/* Historical Telemetry Snapshots Table */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-slate-900">
                  Historical Telemetry Records ({activeEndpoint?.hostname || "Fleet"})
                </h2>
                <p className="text-xs text-slate-500">Chronological endpoint snapshots stored in PostgreSQL</p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-xs">
                <thead className="bg-slate-50 text-slate-500 uppercase text-[10px] font-bold">
                  <tr>
                    <th className="px-3 py-2 text-left">Timestamp</th>
                    <th className="px-3 py-2 text-left">Host / IPv4</th>
                    <th className="px-3 py-2 text-left">Adapter</th>
                    <th className="px-3 py-2 text-left">IP Mode</th>
                    <th className="px-3 py-2 text-left">DNS Mode</th>
                    <th className="px-3 py-2 text-left">GW RTT</th>
                    <th className="px-3 py-2 text-left">WAN RTT</th>
                    <th className="px-3 py-2 text-left">Services</th>
                    <th className="px-3 py-2 text-left">Health</th>
                    <th className="px-3 py-2 text-left">Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {timeSeries.length === 0 ? (
                    <tr>
                      <td colSpan={10} className="px-3 py-8 text-center text-slate-400">
                        No historical samples recorded yet.
                      </td>
                    </tr>
                  ) : (
                    [...timeSeries].reverse().map((s) => (
                      <tr key={s.id} className="hover:bg-slate-50">
                        <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{formatClock(s.recorded_at)}</td>
                        <td className="px-3 py-2 font-mono text-slate-800">{s.ip_address || "None"}</td>
                        <td className="px-3 py-2 text-slate-700">{s.adapter_name || "N/A"}</td>
                        <td className="px-3 py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              s.dhcp_enabled === false ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"
                            }`}
                          >
                            {s.dhcp_enabled === false ? "STATIC" : "DHCP"}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              s.dns_dhcp_enabled === false
                                ? "bg-amber-100 text-amber-800"
                                : "bg-emerald-100 text-emerald-700"
                            }`}
                          >
                            {s.dns_dhcp_enabled === false ? "STATIC" : "DHCP"}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-slate-700">
                          {s.gateway_latency_ms != null ? `${s.gateway_latency_ms}ms` : "Fail"}
                        </td>
                        <td className="px-3 py-2 text-slate-700">
                          {s.internet_latency_ms != null ? `${s.internet_latency_ms}ms` : "Fail"}
                        </td>
                        <td className="px-3 py-2 text-slate-700">
                          {s.services_running_count}/{s.services_total_count}
                        </td>
                        <td className="px-3 py-2 font-bold text-slate-900">{s.health_score}%</td>
                        <td className="px-3 py-2 font-mono text-[10px] text-slate-500">{s.source_mode}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Original Operations Breakdown + Audit Feed preserved */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-6 md:col-span-1">
              <div>
                <h2 className="text-sm font-bold text-slate-800 uppercase tracking-wider mb-3">Incidents By Category</h2>
                <div className="space-y-2">
                  {Object.entries(monitor?.by_category || {}).map(([cat, count]: any) => (
                    <div
                      key={cat}
                      className="flex justify-between items-center text-xs py-1.5 border-b border-slate-100 last:border-0"
                    >
                      <span className="font-semibold text-slate-700">{cat}</span>
                      <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-800 font-bold">{count}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h2 className="text-sm font-bold text-slate-800 uppercase tracking-wider mb-3">By Priority</h2>
                <div className="space-y-2">
                  {Object.entries(monitor?.by_priority || {}).map(([pri, count]: any) => (
                    <div
                      key={pri}
                      className="flex justify-between items-center text-xs py-1.5 border-b border-slate-100 last:border-0"
                    >
                      <span className="font-semibold text-slate-700">{pri}</span>
                      <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-800 font-bold">{count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm md:col-span-2 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold text-slate-800 uppercase tracking-wider flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-sky-600" />
                  <span>Real-Time Audit &amp; Event Log</span>
                </h2>
                <Link href="/incidents" className="text-xs text-sky-600 hover:text-sky-700 font-semibold flex items-center">
                  View All Incidents <ArrowUpRight className="w-3.5 h-3.5 ml-1" />
                </Link>
              </div>

              <div className="divide-y divide-slate-100 text-xs">
                {(monitor?.recent_audits || []).map((ev: any) => (
                  <div key={ev.id} className="py-2.5 flex items-start justify-between">
                    <div className="space-y-0.5">
                      <div className="flex items-center space-x-2">
                        <span className="font-bold text-slate-900">{ev.event_type}</span>
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-600 uppercase font-semibold">
                          {ev.actor_type}
                        </span>
                      </div>
                      <div className="text-slate-500 text-[11px]">
                        Entity: {ev.entity_type} #{ev.entity_id} &bull; Details: {JSON.stringify(ev.details)}
                      </div>
                    </div>
                    <div className="text-[10px] text-slate-400 whitespace-nowrap ml-4">
                      {formatClock(ev.created_at)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
