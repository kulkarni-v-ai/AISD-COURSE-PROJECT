"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest, setAuthToken } from "@/lib/api";
import { Shield, User, Wrench, Lock, ArrowRight } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("tech@college.edu");
  const [password, setPassword] = useState("Tech@123");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleLogin = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const data = await apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setAuthToken(data.access_token);
      localStorage.setItem("aisd_user", JSON.stringify(data.user));
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Login failed. Please verify credentials.");
    } finally {
      setLoading(false);
    }
  };

  const selectRole = (roleEmail: string, rolePass: string) => {
    setEmail(roleEmail);
    setPassword(rolePass);
  };

  return (
    <div className="max-w-md mx-auto my-8 bg-white p-8 rounded-2xl border border-slate-200 shadow-sm space-y-6">
      <div className="text-center space-y-2">
        <div className="w-12 h-12 rounded-xl bg-sky-600 flex items-center justify-center text-white mx-auto shadow-sm">
          <Shield className="w-6 h-6" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Sign in to AISD</h2>
        <p className="text-xs text-slate-500">College IT Incident Management & Diagnostic Engine</p>
      </div>

      {error && (
        <div className="p-3 text-xs bg-rose-50 border border-rose-200 text-rose-700 rounded-lg">
          {error}
        </div>
      )}

      {/* Demo Role Selector */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Quick Demo Login</label>
        <div className="grid grid-cols-3 gap-2">
          <button
            type="button"
            onClick={() => selectRole("tech@college.edu", "Tech@123")}
            className={`p-2.5 rounded-lg border text-left transition ${
              email === "tech@college.edu" ? "border-sky-600 bg-sky-50 text-sky-800" : "border-slate-200 hover:bg-slate-50"
            }`}
          >
            <Wrench className="w-4 h-4 mb-1 text-sky-600" />
            <div className="text-xs font-bold">Technician</div>
            <div className="text-[10px] text-slate-500">Manage & Repair</div>
          </button>

          <button
            type="button"
            onClick={() => selectRole("student@college.edu", "Student@123")}
            className={`p-2.5 rounded-lg border text-left transition ${
              email === "student@college.edu" ? "border-sky-600 bg-sky-50 text-sky-800" : "border-slate-200 hover:bg-slate-50"
            }`}
          >
            <User className="w-4 h-4 mb-1 text-emerald-600" />
            <div className="text-xs font-bold">Student</div>
            <div className="text-[10px] text-slate-500">Report & Track</div>
          </button>

          <button
            type="button"
            onClick={() => selectRole("admin@college.edu", "Admin@123")}
            className={`p-2.5 rounded-lg border text-left transition ${
              email === "admin@college.edu" ? "border-sky-600 bg-sky-50 text-sky-800" : "border-slate-200 hover:bg-slate-50"
            }`}
          >
            <Lock className="w-4 h-4 mb-1 text-purple-600" />
            <div className="text-xs font-bold">Admin</div>
            <div className="text-[10px] text-slate-500">System & Policy</div>
          </button>
        </div>
      </div>

      <form onSubmit={handleLogin} className="space-y-4 pt-2">
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Email Address</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-sky-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-sky-500 focus:outline-none"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 px-4 bg-sky-600 hover:bg-sky-700 text-white font-medium rounded-lg text-sm shadow-sm transition flex items-center justify-center space-x-2"
        >
          <span>{loading ? "Authenticating..." : "Sign In"}</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}
