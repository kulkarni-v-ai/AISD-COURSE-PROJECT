import Link from "next/link";
import { Shield, Cpu, Activity, Database, CheckCircle, ArrowRight } from "lucide-react";

export default function HomePage() {
  return (
    <div className="space-y-12 py-6">
      <div className="text-center max-w-3xl mx-auto space-y-4">
        <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-sky-100 text-sky-800 text-xs font-semibold">
          <span>AI-Powered IT Incident Management Baseline</span>
        </div>
        <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight sm:text-5xl">
          Automated IT Incident Diagnosis & Controlled Remediation
        </h1>
        <p className="text-lg text-slate-600">
          Bridging campus ticketing with deterministic network diagnostic rules, local Ollama LLM reasoning, RAG troubleshooting SOPs, and Windows endpoint agents.
        </p>
        <div className="flex justify-center gap-4 pt-4">
          <Link
            href="/dashboard"
            className="inline-flex items-center px-6 py-3 border border-transparent text-base font-medium rounded-lg text-white bg-sky-600 hover:bg-sky-700 shadow-sm transition"
          >
            Open Technician Dashboard
            <ArrowRight className="w-5 h-5 ml-2" />
          </Link>
          <Link
            href="/login"
            className="inline-flex items-center px-6 py-3 border border-slate-300 text-base font-medium rounded-lg text-slate-700 bg-white hover:bg-slate-50 transition"
          >
            Sign In / Switch Role
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-6">
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div className="w-10 h-10 rounded-lg bg-sky-50 text-sky-600 flex items-center justify-center">
            <Cpu className="w-6 h-6" />
          </div>
          <h3 className="text-lg font-bold text-slate-900">Deterministic + AI Pipeline</h3>
          <p className="text-sm text-slate-600">
            Rules handle deterministic network failures (APIPA, DNS, Gateway). Ollama analyzes ambiguous evidence and grounds hypotheses in retrieved SOPs.
          </p>
        </div>

        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
            <Shield className="w-6 h-6" />
          </div>
          <h3 className="text-lg font-bold text-slate-900">Safe Controlled Remediation</h3>
          <p className="text-sm text-slate-600">
            Never executes raw shell scripts. Only predefined tool IDs in the registry execute under strict risk policies (R0-R3) with technician approval.
          </p>
        </div>

        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-3">
          <div className="w-10 h-10 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center">
            <CheckCircle className="w-6 h-6" />
          </div>
          <h3 className="text-lg font-bold text-slate-900">Postcondition Verification</h3>
          <p className="text-sm text-slate-600">
            Incidents are never marked resolved merely on command exit. Post-action verification actively checks IP, gateway ping, and services before closing.
          </p>
        </div>
      </div>
    </div>
  );
}
