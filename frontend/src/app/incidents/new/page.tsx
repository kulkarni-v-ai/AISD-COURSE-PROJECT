"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/api";
import { PlusCircle, Sparkles, AlertCircle } from "lucide-react";

export default function NewIncidentPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("NETWORK");
  const [priority, setPriority] = useState("HIGH");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadPreset = (presetType: "wifi" | "printer") => {
    if (presetType === "wifi") {
      setTitle("My laptop is connected to the college Wi-Fi, but I cannot access anything.");
      setDescription("Connected to 'Campus-Student-WiFi' in the Central Library. Network status shows 'No Internet, secured'. The IP address appears to be 169.254.x.x link-local and I cannot load college intranet or course portals.");
      setCategory("NETWORK");
      setPriority("HIGH");
    } else {
      setTitle("Lab 2 Network LaserJet Printer is unresponsive");
      setDescription("Students in Computer Lab 2 cannot send print jobs to HP LaserJet 400. The print spooler appears to be stopped or halted.");
      setCategory("PRINTER");
      setPriority("MEDIUM");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const data = await apiRequest("/incidents", {
        method: "POST",
        body: JSON.stringify({
          title,
          description,
          category,
          priority,
        }),
      });
      router.push(`/incidents/${data.id}`);
    } catch (err: any) {
      setError(err.message || "Failed to create incident");
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Report IT Incident</h1>
          <p className="text-sm text-slate-500">Submit an issue for automated diagnostic analysis and technician resolution</p>
        </div>
      </div>

      {/* Preset demo buttons */}
      <div className="bg-sky-50 p-4 rounded-xl border border-sky-100 space-y-2">
        <div className="flex items-center space-x-1.5 text-xs font-bold text-sky-800">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Quick Demonstration Scenarios</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => loadPreset("wifi")}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-sky-200 text-sky-800 hover:bg-sky-100/50 shadow-2xs transition"
          >
            Scenario 1: College Wi-Fi / DHCP Lease Failure (APIPA 169.254)
          </button>
          <button
            type="button"
            onClick={() => loadPreset("printer")}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-sky-200 text-sky-800 hover:bg-sky-100/50 shadow-2xs transition"
          >
            Scenario 2: Lab Print Spooler Stoppage
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 text-xs bg-rose-50 border border-rose-200 text-rose-700 rounded-lg flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Incident Title</label>
          <input
            type="text"
            required
            placeholder="Brief summary of the issue..."
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full px-3.5 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-sky-500 focus:outline-none"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:ring-2 focus:ring-sky-500 focus:outline-none"
            >
              <option value="NETWORK">Network / Wi-Fi</option>
              <option value="PRINTER">Printer / Spooler</option>
              <option value="SOFTWARE">Software / OS</option>
              <option value="HARDWARE">Hardware / Peripherals</option>
              <option value="ACCOUNT">Account / Credentials</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Priority</label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:ring-2 focus:ring-sky-500 focus:outline-none"
            >
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Description & Symptoms</label>
          <textarea
            required
            rows={5}
            placeholder="Provide observed error messages, adapter state, or affected services..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full px-3.5 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-sky-500 focus:outline-none"
          />
        </div>

        <div className="pt-2 flex justify-end space-x-3">
          <button
            type="button"
            onClick={() => router.back()}
            className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="px-5 py-2 bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold rounded-lg shadow-sm transition"
          >
            {loading ? "Submitting..." : "Submit Ticket"}
          </button>
        </div>
      </form>
    </div>
  );
}
