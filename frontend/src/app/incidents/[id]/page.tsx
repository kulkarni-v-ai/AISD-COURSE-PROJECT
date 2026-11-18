"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiRequest, getCurrentUser } from "@/lib/api";
import {
  Activity, CheckCircle2, AlertTriangle, AlertCircle, Cpu, Wrench, Shield,
  Sparkles, BookOpen, Send, Check, X, Network, LogIn
} from "lucide-react";

export default function IncidentDetailPage() {
  const { id } = useParams();
  const [incident, setIncident] = useState<any>(null);
  const [diagnostics, setDiagnostics] = useState<any[]>([]);
  const [plans, setPlans] = useState<any[]>([]);
  const [comments, setComments] = useState<any[]>([]);
  const [newComment, setNewComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadErrorStatus, setLoadErrorStatus] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [diagResult, setDiagResult] = useState<any>(null);
  const [mockMode, setMockMode] = useState(false);
  const [user, setUser] = useState<any>(null);

  const fetchIncidentData = async () => {
    setLoadError(null);
    setLoadErrorStatus(null);
    try {
      const inc = await apiRequest(`/incidents/${id}`);
      setIncident(inc);

      const diag = await apiRequest(`/incidents/${id}/diagnostics`);
      setDiagnostics(diag);
      if (diag.length > 0) {
        setDiagResult((prev: any) => prev || diag[0].findings_json);
      }

      const p = await apiRequest(`/incidents/${id}/remediation-plans`);
      setPlans(p);

      const comm = await apiRequest(`/incidents/${id}/comments`);
      setComments(comm);
    } catch (err: any) {
      setLoadError(err?.message || "Failed to load incident details.");
      setLoadErrorStatus(err?.status ?? null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setUser(getCurrentUser());
    fetchIncidentData();
  }, [id]);

  // Extract latest collected Windows telemetry evidence map
  const latestEvidenceItems = diagnostics?.[0]?.evidence_items || [];
  const evidenceMap: Record<string, any> = {};
  for (const item of latestEvidenceItems) {
    evidenceMap[item.key] = item.value_json;
  }
  const detectedAdapter =
    evidenceMap?.ip_config?.adapter_name ||
    evidenceMap?.network_adapter?.name ||
    null;

  // 1. Trigger automated diagnosis (collects live Windows telemetry on server)
  const handleRunDiagnosis = async (useAi: boolean = true) => {
    setActionLoading(true);
    setActionError(null);
    try {
      const res = await apiRequest(`/incidents/${id}/diagnose`, {
        method: "POST",
        timeoutMs: 70000,
        body: JSON.stringify({ use_ai: useAi, collect_live: true }),
      });
      setDiagResult(res);
      await fetchIncidentData();
    } catch (err: any) {
      setActionError(err?.message || "Diagnosis failed.");
    } finally {
      setActionLoading(false);
    }
  };

  // 2. Propose remediation plan using dynamic detected adapter/tool args
  const handleCreatePlan = async (toolId: string) => {
    setActionLoading(true);
    setActionError(null);
    let args: Record<string, any> = {};
    if (toolId === "restart_approved_service") {
      args = { service_name: "Spooler" };
    } else if (["renew_dhcp", "flush_dns_cache", "enable_adapter", "test_gateway", "test_dns"].includes(toolId)) {
      args = detectedAdapter ? { adapter_name: detectedAdapter } : { adapter_name: "auto" };
    }

    try {
      await apiRequest(`/incidents/${id}/remediation-plan`, {
        method: "POST",
        body: JSON.stringify({
          tool_id: toolId,
          arguments: args,
          reason: `Automated plan proposed based on diagnostic hypothesis. Tool: ${toolId}.`,
        }),
      });
      await fetchIncidentData();
    } catch (err: any) {
      setActionError(err?.message || "Failed to propose remediation plan.");
    } finally {
      setActionLoading(false);
    }
  };

  // 3. Approve or Reject plan
  const handleDecision = async (planId: number, decision: "APPROVED" | "REJECTED") => {
    setActionLoading(true);
    setActionError(null);
    try {
      await apiRequest(`/remediation-plans/${planId}/approve`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          reason: `Decision submitted by ${user?.name || "Technician"}.`,
        }),
      });
      await fetchIncidentData();
    } catch (err: any) {
      setActionError(err?.message || "Approval submission failed.");
    } finally {
      setActionLoading(false);
    }
  };

  // 4. Execute remediation & verification
  const handleExecute = async (planId: number) => {
    setActionLoading(true);
    setActionError(null);
    try {
      await apiRequest(`/remediation-plans/${planId}/execute?is_mock=${mockMode}&simulate_verification_outcome=VERIFIED_RESOLVED`, {
        method: "POST",
        timeoutMs: 40000,
      });
      await fetchIncidentData();
    } catch (err: any) {
      setActionError(err?.message || "Remediation execution failed.");
    } finally {
      setActionLoading(false);
    }
  };

  // 5. Add comment
  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim()) return;
    try {
      await apiRequest(`/incidents/${id}/comments`, {
        method: "POST",
        body: JSON.stringify({ comment: newComment }),
      });
      setNewComment("");
      await fetchIncidentData();
    } catch (err: any) {
      setActionError(err?.message || "Failed to post comment.");
    }
  };

  if (loading) {
    return (
      <div className="p-12 text-center space-y-2">
        <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-sky-600 mx-auto"></div>
        <div className="text-sm text-slate-500">Loading incident console...</div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="max-w-lg mx-auto bg-white p-8 rounded-xl border border-slate-200 shadow-sm text-center space-y-3">
        <AlertCircle className="w-8 h-8 text-rose-500 mx-auto" />
        <h2 className="text-base font-bold text-slate-900">Unable to load Incident #{id}</h2>
        <p className="text-xs text-rose-600">{loadError}</p>
        <div className="flex justify-center gap-2 pt-1">
          <button
            onClick={fetchIncidentData}
            className="px-4 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold"
          >
            Retry
          </button>
          {loadErrorStatus === 401 && (
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

  if (!incident) {
    return <div className="p-12 text-center text-sm text-rose-500">Incident not found.</div>;
  }

  const latestPlan = plans[0];

  return (
    <div className="space-y-6">
      {actionError && (
        <div className="p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-center justify-between gap-3">
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
            <span>{actionError}</span>
          </div>
          <button onClick={() => setActionError(null)} className="text-rose-500 hover:text-rose-700 font-bold">
            Dismiss
          </button>
        </div>
      )}

      {/* Header Banner */}
      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="font-mono text-sm font-bold text-sky-700">{incident.incident_number}</span>
            {incident.status === "RESOLVED" ? (
              <span className="px-3 py-0.5 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 flex items-center">
                <CheckCircle2 className="w-3.5 h-3.5 mr-1 text-emerald-600" />
                FIXED / RESOLVED
              </span>
            ) : incident.status === "ESCALATED" ? (
              <span className="px-3 py-0.5 rounded-full text-xs font-bold bg-rose-100 text-rose-800 border border-rose-300 flex items-center">
                <AlertTriangle className="w-3.5 h-3.5 mr-1 text-rose-600" />
                CANNOT BE DONE AUTOMATICALLY - FLAGGED
              </span>
            ) : incident.status === "APPROVAL_REQUIRED" ? (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300">
                APPROVAL REQUIRED
              </span>
            ) : (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-100 text-sky-800 border border-sky-300">
                {incident.status}
              </span>
            )}
            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
              {incident.priority}
            </span>
            <span className="text-xs text-slate-400">&bull; {incident.category}</span>
          </div>

          <div className="flex items-center space-x-2 text-xs text-slate-500">
            <label className="flex items-center space-x-1.5 cursor-pointer bg-slate-50 px-2.5 py-1 rounded-md border border-slate-200">
              <input
                type="checkbox"
                checked={mockMode}
                onChange={(e) => setMockMode(e.target.checked)}
                className="rounded text-sky-600 focus:ring-0"
              />
              <span className="font-semibold text-slate-700">Mock Mode Active</span>
            </label>
          </div>
        </div>

        <h1 className="text-xl font-bold text-slate-900">{incident.title}</h1>
        <p className="text-sm text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-100">{incident.description}</p>

        {incident.resolution_summary && (
          incident.status === "RESOLVED" ? (
            <div className="p-4 bg-emerald-50 border border-emerald-300 rounded-lg text-xs text-emerald-950 flex items-start space-x-2.5">
              <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold text-emerald-800 uppercase tracking-wider block mb-0.5">✓ Issue Status: FIXED</span>
                <span>{incident.resolution_summary}</span>
              </div>
            </div>
          ) : (
            <div className="p-4 bg-rose-50 border border-rose-300 rounded-lg text-xs text-rose-950 flex items-start space-x-2.5">
              <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold text-rose-800 uppercase tracking-wider block mb-0.5">⚠ Issue Status: FLAGGED (CANNOT BE DONE AUTOMATICALLY)</span>
                <span>{incident.resolution_summary}</span>
              </div>
            </div>
          )
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Diagnostics & AI Reasoning */}
        <div className="lg:col-span-2 space-y-6">
          {/* Diagnostic Action Panel */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center space-x-2">
                <Cpu className="w-5 h-5 text-sky-600" />
                <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">AI & Deterministic Diagnostics</h2>
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => handleRunDiagnosis(false)}
                  disabled={actionLoading}
                  className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 disabled:opacity-60 transition"
                >
                  {actionLoading ? "Collecting..." : "Run Rules Only"}
                </button>
                <button
                  onClick={() => handleRunDiagnosis(true)}
                  disabled={actionLoading}
                  className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-60 shadow-2xs transition flex items-center space-x-1.5"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>{actionLoading ? "Analyzing..." : "Run Ollama Diagnosis"}</span>
                </button>
              </div>
            </div>

            {diagResult ? (
              <div className="space-y-4 pt-2">
                <div className="p-3.5 rounded-lg bg-sky-50/70 border border-sky-100 text-xs text-slate-800 space-y-1">
                  <div className="font-bold text-sky-900 flex flex-wrap items-center justify-between gap-2">
                    <span>Diagnosis Provider: {diagResult.provider || "rule_engine"}</span>
                    {diagResult.is_fallback && (
                      <span className="text-[10px] bg-amber-100 text-amber-800 px-2 py-0.5 rounded font-semibold">
                        Ollama Offline &bull; Fallback to Rules
                      </span>
                    )}
                  </div>
                  <p className="text-slate-700">{diagResult.summary}</p>
                </div>

                {/* Live Windows Telemetry Summary */}
                {evidenceMap.ip_config && (
                  <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
                    <div className="text-[11px] font-bold text-slate-600 uppercase flex items-center space-x-1.5">
                      <Network className="w-3.5 h-3.5 text-sky-600" />
                      <span>Observed Windows Network Telemetry</span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                      <div className="bg-white p-2 rounded border border-slate-200">
                        <div className="text-slate-400">Adapter</div>
                        <div className="font-semibold text-slate-800 truncate">
                          {detectedAdapter || "Unknown"} ({evidenceMap.network_adapter?.status || "N/A"})
                        </div>
                      </div>
                      <div className="bg-white p-2 rounded border border-slate-200">
                        <div className="text-slate-400">IPv4 / DHCP</div>
                        <div className={`font-semibold ${evidenceMap.ip_config.dhcp_enabled === false ? "text-amber-700" : "text-slate-800"}`}>
                          {evidenceMap.ip_config.ipv4_address || "None"}{" "}
                          {evidenceMap.ip_config.dhcp_enabled === false ? "(Static IP)" : "(DHCP)"}
                        </div>
                      </div>
                      <div className="bg-white p-2 rounded border border-slate-200">
                        <div className="text-slate-400">Gateway</div>
                        <div className="font-semibold text-slate-800 truncate">
                          {evidenceMap.ip_config.default_gateway || "None"}{" "}
                          {evidenceMap.gateway_ping ? (evidenceMap.gateway_ping.reachable ? "✓" : "✕") : ""}
                        </div>
                      </div>
                      <div className="bg-white p-2 rounded border border-slate-200">
                        <div className="text-slate-400">DNS Config</div>
                        <div className={`font-semibold truncate ${evidenceMap.ip_config.dns_dhcp_enabled === false ? "text-amber-700" : "text-slate-800"}`}>
                          {evidenceMap.ip_config.dns_dhcp_enabled === false
                            ? `Static (${(evidenceMap.ip_config.dns_servers || []).join(", ") || "Custom"})`
                            : `DHCP (${(evidenceMap.ip_config.dns_servers || []).join(", ") || "Auto"})`}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Hypotheses */}
                <div className="space-y-2">
                  <div className="text-xs font-bold text-slate-700 uppercase">Root Cause Hypotheses</div>
                  {(diagResult.hypotheses || []).map((h: any, idx: number) => (
                    <div key={idx} className="p-3 rounded-lg border border-slate-200 bg-white space-y-2">
                      <div className="flex items-center justify-between text-xs gap-2">
                        <span className="font-bold text-slate-900">{h.cause}</span>
                        <span className="font-mono font-bold text-sky-600 whitespace-nowrap">{Math.round(h.confidence * 100)}% Confidence</span>
                      </div>
                      <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                        <div className="bg-sky-600 h-1.5 rounded-full" style={{ width: `${h.confidence * 100}%` }}></div>
                      </div>
                      <div className="text-[11px] text-slate-500 flex flex-wrap gap-x-4">
                        <span>Grounded in Evidence: {h.evidence_ids?.join(", ") || "None"}</span>
                        <span>Next Checks: {h.next_checks?.join(", ") || "None"}</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Citations / RAG sources */}
                {diagResult.sources && diagResult.sources.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-xs font-bold text-slate-700 uppercase flex items-center space-x-1">
                      <BookOpen className="w-3.5 h-3.5 text-sky-600" />
                      <span>Retrieved Troubleshooting Procedures (RAG)</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {diagResult.sources.map((s: string) => (
                        <span key={s} className="px-2.5 py-1 rounded bg-slate-100 text-slate-800 text-xs font-mono font-semibold border border-slate-200">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recommended Remediation Action Buttons */}
                {diagResult.recommended_tool_ids && diagResult.recommended_tool_ids.length > 0 && (
                  <div className="pt-2 border-t border-slate-100 space-y-2">
                    <div className="text-xs font-bold text-slate-700 uppercase">Proposed Remediation Action</div>
                    <div className="flex flex-wrap gap-2">
                      {diagResult.recommended_tool_ids.map((toolId: string) => (
                        <button
                          key={toolId}
                          onClick={() => handleCreatePlan(toolId)}
                          disabled={actionLoading}
                          className="px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-xs font-bold shadow-sm transition flex items-center space-x-1.5"
                        >
                          <Wrench className="w-3.5 h-3.5" />
                          <span>Propose Tool: {toolId}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-8 text-center text-xs text-slate-400">
                Click &quot;Run Ollama Diagnosis&quot; to collect live Windows evidence and generate root-cause hypotheses.
              </div>
            )}
          </div>

          {/* Remediation & Verification Control Panel */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
            <div className="flex items-center space-x-2">
              <Shield className="w-5 h-5 text-emerald-600" />
              <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">Safe Remediation & Verification Engine</h2>
            </div>

            {latestPlan ? (
              <div className="space-y-4 pt-1">
                <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/50 space-y-3">
                  <div className="flex items-center justify-between text-xs">
                    <div className="font-bold text-slate-900">Active Remediation Plan: #{latestPlan.id}</div>
                    <div className="flex items-center space-x-2">
                      <span className="font-semibold text-slate-600">Risk: <span className="text-orange-700 font-bold">{latestPlan.risk_level}</span></span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        latestPlan.status === "COMPLETED" ? "bg-emerald-100 text-emerald-800" :
                        latestPlan.status === "FAILED" ? "bg-rose-100 text-rose-800" :
                        latestPlan.status === "APPROVED" ? "bg-sky-100 text-sky-800" : "bg-amber-100 text-amber-800"
                      }`}>
                        {latestPlan.status}
                      </span>
                    </div>
                  </div>

                  <div className="text-xs text-slate-700 space-y-1">
                    <div><span className="font-semibold">Tool ID:</span> <span className="font-mono text-sky-700 font-bold">{latestPlan.tool_id}</span></div>
                    <div><span className="font-semibold">Rationale:</span> {latestPlan.reason}</div>
                    <div><span className="font-semibold">Approval Required:</span> {latestPlan.approval_required ? "Yes (Technician authorization mandatory)" : "Pre-approved under policy"}</div>
                  </div>

                  {/* Approval Actions */}
                  {latestPlan.status === "PENDING" && (
                    <div className="pt-2 flex items-center space-x-3">
                      <button
                        onClick={() => handleDecision(latestPlan.id, "APPROVED")}
                        disabled={actionLoading}
                        className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white rounded-lg text-xs font-bold shadow-2xs transition flex items-center space-x-1"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>Authorize / Approve</span>
                      </button>
                      <button
                        onClick={() => handleDecision(latestPlan.id, "REJECTED")}
                        disabled={actionLoading}
                        className="px-3.5 py-1.5 bg-rose-600 hover:bg-rose-700 disabled:opacity-60 text-white rounded-lg text-xs font-bold shadow-2xs transition flex items-center space-x-1"
                      >
                        <X className="w-3.5 h-3.5" />
                        <span>Reject Plan</span>
                      </button>
                    </div>
                  )}

                  {/* Execution Action */}
                  {latestPlan.status === "APPROVED" && (
                    <div className="pt-2">
                      <button
                        onClick={() => handleExecute(latestPlan.id)}
                        disabled={actionLoading}
                        className="px-4 py-2 bg-sky-600 hover:bg-sky-700 disabled:opacity-60 text-white rounded-lg text-xs font-bold shadow-sm transition flex items-center space-x-1.5"
                      >
                        <Activity className="w-4 h-4" />
                        <span>{actionLoading ? "Executing & Verifying..." : "Execute Remediation & Verify Postcondition"}</span>
                      </button>
                    </div>
                  )}

                  {/* Execution & Verification Output */}
                  {latestPlan.execution && (
                    <div className="mt-3 p-3 bg-white rounded-lg border border-slate-200 text-xs space-y-2">
                      <div className="font-bold text-slate-800 flex flex-wrap items-center justify-between gap-2">
                        <span>Execution Status: <span className="font-mono text-slate-900">{latestPlan.execution.execution_status}</span></span>
                        {latestPlan.execution.verification?.status === "VERIFIED_RESOLVED" ? (
                          <span className="px-2.5 py-0.5 rounded text-[11px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 flex items-center">
                            <CheckCircle2 className="w-3.5 h-3.5 mr-1 text-emerald-600" />
                            [FIXED] VERIFIED RESOLVED
                          </span>
                        ) : (
                          <span className="px-2.5 py-0.5 rounded text-[11px] font-bold bg-rose-100 text-rose-800 border border-rose-300 flex items-center">
                            <AlertTriangle className="w-3.5 h-3.5 mr-1 text-rose-600" />
                            [FLAGGED: CANNOT BE DONE AUTOMATICALLY]
                          </span>
                        )}
                      </div>
                      <pre className="p-2.5 rounded bg-slate-900 text-slate-100 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto">
                        {latestPlan.execution.output_redacted}
                      </pre>
                      {latestPlan.execution.verification?.evidence_json && (
                        <div className="p-2 rounded bg-slate-50 border border-slate-200 text-[11px] text-slate-700">
                          <span className="font-semibold">Postcondition Verification Evidence: </span>
                          <span className="font-mono">{JSON.stringify(latestPlan.execution.verification.evidence_json)}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-6 text-center text-xs text-slate-400">
                No active remediation plan. Run diagnosis first to generate a proposed action.
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Timeline & Comments */}
        <div className="space-y-6">
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">Event Timeline & Notes</h2>

            <div className="space-y-3 max-h-[450px] overflow-y-auto pr-1">
              {comments.map((c) => (
                <div key={c.id} className="p-3 rounded-lg bg-slate-50 border border-slate-100 text-xs space-y-1">
                  <div className="flex items-center justify-between font-bold text-slate-700">
                    <span>{c.author_name}</span>
                    <span className="text-[10px] text-slate-400 font-normal">
                      {new Date(c.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <p className="text-slate-600 whitespace-pre-wrap">{c.comment}</p>
                </div>
              ))}
            </div>

            <form onSubmit={handleAddComment} className="pt-2 space-y-2">
              <textarea
                rows={2}
                placeholder="Add technician note or update..."
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                className="w-full p-2.5 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
              <button
                type="submit"
                className="w-full py-1.5 bg-slate-800 hover:bg-slate-900 text-white text-xs font-semibold rounded-lg shadow-2xs transition flex items-center justify-center space-x-1"
              >
                <Send className="w-3 h-3" />
                <span>Post Update</span>
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
