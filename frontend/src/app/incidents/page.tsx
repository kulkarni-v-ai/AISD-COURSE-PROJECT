"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { Search, Filter, Plus, ArrowRight, ShieldAlert, CheckCircle2, Clock, AlertCircle, LogIn } from "lucide-react";

export default function IncidentsListPage() {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  const fetchIncidents = async () => {
    setLoading(true);
    setError(null);
    setErrorStatus(null);
    try {
      let url = "/incidents?";
      if (statusFilter) url += `status=${statusFilter}&`;
      if (categoryFilter) url += `category=${categoryFilter}&`;
      const data = await apiRequest(url);
      setIncidents(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load incident queue.");
      setErrorStatus(err?.status ?? null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIncidents();
  }, [statusFilter, categoryFilter]);

  const filtered = incidents.filter((i) =>
    i.title.toLowerCase().includes(search.toLowerCase()) ||
    i.incident_number.toLowerCase().includes(search.toLowerCase())
  );

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "RESOLVED":
        return <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">✓ FIXED</span>;
      case "ESCALATED":
        return <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-rose-100 text-rose-800 border border-rose-300">⚠ FLAGGED (CANNOT BE DONE)</span>;
      case "APPROVAL_REQUIRED":
        return <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-amber-100 text-amber-800 border border-amber-300">APPROVAL REQUIRED</span>;
      case "DIAGNOSING":
      case "REMEDIATING":
      case "VERIFYING":
        return <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-sky-100 text-sky-800 animate-pulse border border-sky-300">{status}</span>;
      default:
        return <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-slate-100 text-slate-800 border border-slate-200">{status}</span>;
    }
  };

  const getPriorityBadge = (pri: string) => {
    switch (pri) {
      case "CRITICAL":
        return <span className="text-[11px] font-bold text-rose-600 bg-rose-50 px-2 py-0.5 rounded">CRITICAL</span>;
      case "HIGH":
        return <span className="text-[11px] font-bold text-orange-600 bg-orange-50 px-2 py-0.5 rounded">HIGH</span>;
      default:
        return <span className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-0.5 rounded">{pri}</span>;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Incident Queue</h1>
          <p className="text-sm text-slate-500">Track, diagnose, and resolve reported college IT issues</p>
        </div>
        <Link
          href="/incidents/new"
          className="inline-flex items-center px-4 py-2 bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold rounded-lg shadow-sm transition"
        >
          <Plus className="w-4 h-4 mr-1.5" />
          Create Incident
        </Link>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row gap-4 items-center justify-between">
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
          <input
            type="text"
            placeholder="Search by ticket # or title..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
          />
        </div>

        <div className="flex items-center gap-3 w-full md:w-auto">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none"
          >
            <option value="">All Statuses</option>
            <option value="NEW">New</option>
            <option value="DIAGNOSING">Diagnosing</option>
            <option value="APPROVAL_REQUIRED">Approval Required</option>
            <option value="REMEDIATING">Remediating</option>
            <option value="RESOLVED">Resolved</option>
            <option value="ESCALATED">Escalated</option>
          </select>

          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none"
          >
            <option value="">All Categories</option>
            <option value="NETWORK">Network</option>
            <option value="PRINTER">Printer</option>
            <option value="SOFTWARE">Software</option>
            <option value="HARDWARE">Hardware</option>
          </select>
        </div>
      </div>

      {/* Incident List */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-500 text-sm">Loading incidents...</div>
        ) : error ? (
          <div className="p-8 text-center space-y-3">
            <AlertCircle className="w-7 h-7 text-rose-500 mx-auto" />
            <div className="text-sm font-semibold text-slate-800">Unable to load Incident Queue</div>
            <p className="text-xs text-rose-600">{error}</p>
            <div className="flex justify-center gap-2 pt-1">
              <button
                onClick={fetchIncidents}
                className="px-3.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold"
              >
                Retry
              </button>
              {errorStatus === 401 && (
                <Link
                  href="/login"
                  className="inline-flex items-center px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold"
                >
                  <LogIn className="w-3.5 h-3.5 mr-1.5" />
                  Sign In
                </Link>
              )}
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center space-y-2">
            <CheckCircle2 className="w-8 h-8 text-slate-400 mx-auto" />
            <div className="text-sm font-semibold text-slate-700">No matching incidents found</div>
            <div className="text-xs text-slate-400">Clear filters or submit a new ticket.</div>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {filtered.map((inc) => (
              <Link
                key={inc.id}
                href={`/incidents/${inc.id}`}
                className="p-4 sm:p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 hover:bg-slate-50/80 transition"
              >
                <div className="space-y-1.5 flex-1">
                  <div className="flex items-center space-x-3">
                    <span className="font-mono text-xs font-bold text-sky-700">{inc.incident_number}</span>
                    {getStatusBadge(inc.status)}
                    {getPriorityBadge(inc.priority)}
                    <span className="text-[11px] text-slate-400">&bull; {inc.category}</span>
                  </div>
                  <h3 className="text-sm font-bold text-slate-900">{inc.title}</h3>
                  <p className="text-xs text-slate-500 line-clamp-1">{inc.description}</p>
                </div>

                <div className="flex items-center space-x-6 text-xs text-slate-500 self-end sm:self-center">
                  <div className="text-right hidden md:block">
                    <div>Reporter: <span className="font-medium text-slate-700">{inc.reporter_name || "Student"}</span></div>
                    <div className="text-[10px] text-slate-400">
                      {new Date(inc.created_at).toLocaleDateString()} {new Date(inc.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-slate-400" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
