"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { RefreshCw, AlertCircle, WifiOff, Wifi, LogIn, Activity, Copy, Check, Server } from "lucide-react";

export default function AgentsPage() {
  const [agents, setAgents] = useState<any[]>([]);
  const [networkInfo, setNetworkInfo] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  const fetchAgents = async () => {
    setLoading(true);
    setError(null);
    setErrorStatus(null);
    try {
      const data = await apiRequest("/agents");
      setAgents(Array.isArray(data) ? data : []);
      try {
        const net = await apiRequest("/agents/network-info");
        setNetworkInfo(net);
      } catch {
        // Optional helper
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load Windows endpoint fleet.");
      setErrorStatus(err?.status ?? null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAgents();
  }, []);

  const isHeartbeatStale = (isoTimestamp?: string) => {
    if (!isoTimestamp) return false;
    const ms = new Date(isoTimestamp).getTime();
    if (Number.isNaN(ms)) return false;
    return Date.now() - ms > 5 * 60 * 1000;
  };

  const formatTimestamp = (isoTimestamp?: string) => {
    if (!isoTimestamp) return "Never";
    const d = new Date(isoTimestamp);
    if (Number.isNaN(d.getTime())) return isoTimestamp;
    return d.toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const handleCopy = async () => {
    if (!networkInfo?.join_command || typeof navigator === "undefined") return;
    try {
      await navigator.clipboard.writeText(networkInfo.join_command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard restriction
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Windows Endpoint Fleet</h1>
          <p className="text-sm text-slate-500">Managed endpoint agents, LAN IP addresses, heartbeat status, and offline synchronization</p>
        </div>
        <button
          onClick={fetchAgents}
          disabled={loading}
          className="inline-flex items-center px-3.5 py-1.5 border border-slate-200 text-xs font-semibold rounded-lg text-slate-700 bg-white hover:bg-slate-50 disabled:opacity-60 shadow-2xs transition"
        >
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Refreshing..." : "Refresh Fleet"}
        </button>
      </div>

      {networkInfo && (
        <div className="bg-white rounded-xl border border-slate-200 border-l-4 border-l-sky-600 shadow-sm p-4 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-slate-800">
              <Server className="w-4 h-4 text-sky-600" />
              <span>Join Another Windows System on the Same Network</span>
            </div>
            <span className="text-[11px] text-slate-500">
              Server LAN IP(s):{" "}
              <span className="font-mono font-semibold text-slate-800">
                {(networkInfo.lan_ips || [networkInfo.primary_lan_ip]).filter(Boolean).join(", ")}
              </span>
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <code className="flex-1 min-w-[240px] bg-slate-50 border border-slate-200 rounded px-3 py-1.5 font-mono text-xs text-slate-800">
              {networkInfo.join_command}
            </code>
            <button
              type="button"
              onClick={handleCopy}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-xs font-semibold text-slate-700 transition"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="text-[11px] text-slate-500">
            Run <code className="bg-slate-100 px-1 rounded font-mono">JOIN_LAN_AGENT.bat</code> as Administrator on any laptop on the same LAN to allow live monitoring &amp; remote execution from <Link href="/dashboard" className="text-sky-600 font-semibold hover:underline">Dashboard</Link>.
          </p>
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-10 text-center space-y-2">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-sky-600 mx-auto"></div>
            <div className="text-xs text-slate-500">Loading Windows endpoint fleet...</div>
          </div>
        ) : error ? (
          <div className="p-8 text-center space-y-3">
            <AlertCircle className="w-7 h-7 text-rose-500 mx-auto" />
            <div className="text-sm font-semibold text-slate-800">Unable to load Endpoint Fleet</div>
            <p className="text-xs text-rose-600 max-w-md mx-auto">{error}</p>
            <div className="flex justify-center gap-2 pt-1">
              <button
                onClick={fetchAgents}
                className="px-3.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold transition"
              >
                Retry
              </button>
              {errorStatus === 401 && (
                <Link
                  href="/login"
                  className="inline-flex items-center px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold transition"
                >
                  <LogIn className="w-3.5 h-3.5 mr-1.5" />
                  Sign In
                </Link>
              )}
            </div>
          </div>
        ) : agents.length === 0 ? (
          <div className="p-12 text-center text-xs text-slate-400">
            No endpoint agents enrolled yet. Start an agent using:{" "}
            <code className="bg-slate-100 px-1.5 py-0.5 rounded font-mono text-slate-700">python agent.py daemon</code>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {agents.map((agent) => {
              const stale = isHeartbeatStale(agent.last_seen_at);
              const ipAddr = agent.ip_address || agent.last_telemetry?.ip_config?.ipv4_address;
              const adapter = agent.adapter_name || agent.last_telemetry?.ip_config?.adapter_name || agent.last_telemetry?.network_adapter?.name;
              return (
                <div key={agent.id} className="p-4 sm:p-5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-bold text-sm text-slate-900">{agent.hostname}</span>
                      <span className="font-mono text-xs text-slate-400">({agent.agent_uuid})</span>
                      <span className="text-[10px] bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded font-semibold">
                        v{agent.agent_version}
                      </span>
                      {ipAddr && (
                        <span className="text-[11px] font-mono bg-sky-50 text-sky-700 border border-sky-200 px-2 py-0.5 rounded font-semibold">
                          {ipAddr}
                        </span>
                      )}
                      {adapter && (
                        <span className="text-[11px] bg-slate-50 text-slate-600 border border-slate-200 px-2 py-0.5 rounded">
                          {adapter}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500">
                      Operating System: <span className="font-medium text-slate-700">{agent.os_name} {agent.os_version}</span>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-3 text-xs">
                    <div className="text-right">
                      <div className="text-[11px] text-slate-400">Last Seen</div>
                      <div className="font-medium text-slate-700">
                        {formatTimestamp(agent.last_seen_at)}
                      </div>
                      {stale && (
                        <div className="text-[10px] text-amber-600 font-medium">
                          Heartbeat stale (&gt;5m ago)
                        </div>
                      )}
                    </div>

                    <span className={`px-2.5 py-1 rounded-full text-xs font-bold flex items-center space-x-1 whitespace-nowrap ${
                      agent.status === "ONLINE" && !stale
                        ? "bg-emerald-100 text-emerald-800"
                        : agent.status === "ONLINE"
                        ? "bg-amber-100 text-amber-800"
                        : "bg-slate-100 text-slate-600"
                    }`}>
                      {agent.status === "ONLINE" ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
                      <span>{agent.status === "ONLINE" && stale ? "STALE" : agent.status}</span>
                    </span>

                    <Link
                      href={`/dashboard?agent=${encodeURIComponent(agent.agent_uuid)}`}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-sky-50 hover:bg-sky-100 text-sky-700 font-semibold border border-sky-200 transition"
                    >
                      <Activity className="w-3.5 h-3.5" />
                      Monitor
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
