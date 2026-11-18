"use client";

import React, { useMemo, useState } from "react";
import { Activity } from "lucide-react";

export interface TelemetryPoint {
  id: number;
  recorded_at: string;
  hostname?: string;
  ip_address?: string | null;
  adapter_name?: string | null;
  adapter_status?: string | null;
  dhcp_enabled?: boolean | null;
  dns_dhcp_enabled?: boolean | null;
  gateway_latency_ms?: number | null;
  internet_latency_ms?: number | null;
  gateway_loss_pct?: number;
  internet_loss_pct?: number;
  dns_resolved?: boolean | null;
  services_running_count?: number;
  services_total_count?: number;
  health_score?: number;
  anomaly_count?: number;
  source_mode?: string;
}

type ChartMode = "latency" | "health" | "stability";

interface TelemetryChartProps {
  data: TelemetryPoint[];
  onCollectSample?: () => void;
  collecting?: boolean;
}

function buildSmoothPath(points: { x: number; y: number }[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let d = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i];
    const p1 = points[i + 1];
    const cx = (p0.x + p1.x) / 2;
    d += ` C ${cx.toFixed(2)} ${p0.y.toFixed(2)}, ${cx.toFixed(2)} ${p1.y.toFixed(2)}, ${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`;
  }
  return d;
}

function formatShortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function TelemetryChart({ data, onCollectSample, collecting }: TelemetryChartProps) {
  const [mode, setMode] = useState<ChartMode>("latency");
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const width = 920;
  const height = 250;
  const padL = 54;
  const padR = 54;
  const padT = 18;
  const padB = 34;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const series = useMemo(() => {
    const slice = (data || []).slice(-40);
    if (slice.length === 0) {
      return {
        slice,
        primaryLabel: "",
        secondaryLabel: "",
        primaryColor: "#0284c7",
        secondaryColor: "#6366f1",
        leftUnit: "ms",
        rightUnit: "ms",
        leftMin: 0,
        leftMax: 100,
        rightMin: 0,
        rightMax: 100,
        p1Points: [] as { x: number; y: number; val: number }[],
        p2Points: [] as { x: number; y: number; val: number }[],
      };
    }

    const getX = (idx: number) =>
      slice.length === 1 ? padL + plotW / 2 : padL + (idx / (slice.length - 1)) * plotW;

    let leftMin = 0;
    let leftMax = 100;
    let rightMin = 0;
    let rightMax = 100;
    let leftVals: number[] = [];
    let rightVals: number[] = [];
    let primaryLabel = "Gateway RTT (ms)";
    let secondaryLabel = "Internet WAN RTT (ms)";
    let primaryColor = "#0284c7"; // sky-600
    let secondaryColor = "#6366f1"; // indigo-500
    let leftUnit = "ms";
    let rightUnit = "ms";

    if (mode === "latency") {
      primaryLabel = "Gateway RTT (ms)";
      secondaryLabel = "Internet WAN RTT (ms)";
      primaryColor = "#0284c7";
      secondaryColor = "#6366f1";
      leftVals = slice.map((d) => (d.gateway_latency_ms != null ? Number(d.gateway_latency_ms) : 0));
      rightVals = slice.map((d) => (d.internet_latency_ms != null ? Number(d.internet_latency_ms) : 0));
      const maxL = Math.max(10, ...leftVals, ...rightVals);
      const niceMax = Math.ceil(maxL / 10) * 10;
      leftMin = 0;
      leftMax = niceMax;
      rightMin = 0;
      rightMax = niceMax;
    } else if (mode === "health") {
      primaryLabel = "Health Score (%)";
      secondaryLabel = "Running Core Services";
      primaryColor = "#059669"; // emerald-600
      secondaryColor = "#0284c7"; // sky-600
      leftUnit = "%";
      rightUnit = " svc";
      leftVals = slice.map((d) => Number(d.health_score ?? 100));
      rightVals = slice.map((d) => Number(d.services_running_count ?? 4));
      leftMin = 0;
      leftMax = 100;
      rightMin = 0;
      rightMax = 4;
    } else {
      primaryLabel = "Packet Loss Avg (%)";
      secondaryLabel = "Detected Anomalies";
      primaryColor = "#e11d48"; // rose-600
      secondaryColor = "#d97706"; // amber-600
      leftUnit = "%";
      rightUnit = " flags";
      leftVals = slice.map((d) =>
        Math.round(((Number(d.gateway_loss_pct ?? 0) + Number(d.internet_loss_pct ?? 0)) / 2) * 10) / 10
      );
      rightVals = slice.map((d) => Number(d.anomaly_count ?? 0));
      leftMin = 0;
      leftMax = 100;
      rightMin = 0;
      rightMax = Math.max(4, ...rightVals);
    }

    const scaleY = (val: number, min: number, max: number) => {
      const span = Math.max(1e-6, max - min);
      const ratio = Math.max(0, Math.min(1, (val - min) / span));
      return padT + plotH - ratio * plotH;
    };

    const p1Points = leftVals.map((v, i) => ({ x: getX(i), y: scaleY(v, leftMin, leftMax), val: v }));
    const p2Points = rightVals.map((v, i) => ({ x: getX(i), y: scaleY(v, rightMin, rightMax), val: v }));

    return {
      slice,
      primaryLabel,
      secondaryLabel,
      primaryColor,
      secondaryColor,
      leftUnit,
      rightUnit,
      leftMin,
      leftMax,
      rightMin,
      rightMax,
      p1Points,
      p2Points,
    };
  }, [data, mode, plotH, plotW]);

  const activeIndex = hoverIdx !== null && hoverIdx < series.slice.length ? hoverIdx : null;
  const activeSample = activeIndex !== null ? series.slice[activeIndex] : null;
  const activeP1 = activeIndex !== null ? series.p1Points[activeIndex] : null;
  const activeP2 = activeIndex !== null ? series.p2Points[activeIndex] : null;

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (series.slice.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * width;
    if (relX < padL - 12 || relX > width - padR + 12) {
      setHoverIdx(null);
      return;
    }
    if (series.slice.length === 1) {
      setHoverIdx(0);
      return;
    }
    const clamped = Math.max(padL, Math.min(padL + plotW, relX));
    const idx = Math.round(((clamped - padL) / plotW) * (series.slice.length - 1));
    setHoverIdx(Math.max(0, Math.min(series.slice.length - 1, idx)));
  };

  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTickIndices = useMemo(() => {
    const n = series.slice.length;
    if (n === 0) return [];
    if (n <= 6) return series.slice.map((_, i) => i);
    const steps = 6;
    const indices: number[] = [];
    for (let i = 0; i <= steps; i++) {
      const idx = Math.round((i / steps) * (n - 1));
      if (!indices.includes(idx)) indices.push(idx);
    }
    return indices;
  }, [series.slice]);

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-sky-600" />
          <h2 className="text-sm font-bold text-slate-900">
            Endpoint Network &amp; Health Time-Series Telemetry
          </h2>
          <span className="text-xs text-slate-400 font-medium">
            ({series.slice.length} sample{series.slice.length === 1 ? "" : "s"})
          </span>
        </div>

        <div className="inline-flex items-center bg-slate-100 p-1 rounded-lg border border-slate-200 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setMode("latency")}
            className={`px-3 py-1 rounded-md transition ${
              mode === "latency" ? "bg-sky-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            Gateway &amp; WAN RTT
          </button>
          <button
            type="button"
            onClick={() => setMode("health")}
            className={`px-3 py-1 rounded-md transition ${
              mode === "health" ? "bg-sky-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            Health &amp; Services
          </button>
          <button
            type="button"
            onClick={() => setMode("stability")}
            className={`px-3 py-1 rounded-md transition ${
              mode === "stability" ? "bg-sky-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            Loss &amp; Anomalies
          </button>
        </div>
      </div>

      {series.slice.length === 0 ? (
        <div className="h-[220px] flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/70 text-center px-4">
          <p className="text-xs text-slate-500 max-w-md">
            No time-series snapshots stored yet for this system. Run a live telemetry probe or keep the endpoint agent daemon running to stream live data every 15s.
          </p>
          {onCollectSample && (
            <button
              type="button"
              onClick={onCollectSample}
              disabled={collecting}
              className="mt-3 px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 disabled:opacity-60 text-white text-xs font-semibold transition"
            >
              {collecting ? "Collecting Sample..." : "Collect First Sample Now"}
            </button>
          )}
        </div>
      ) : (
        <div className="relative">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="w-full h-auto select-none overflow-visible"
            onMouseMove={handleMouseMove}
            onMouseLeave={() => setHoverIdx(null)}
          >
            <defs>
              <linearGradient id="aisdPrimaryArea" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={series.primaryColor} stopOpacity="0.14" />
                <stop offset="100%" stopColor={series.primaryColor} stopOpacity="0.01" />
              </linearGradient>
            </defs>

            {/* Horizontal grid lines + Left/Right Y Axis labels */}
            {yTicks.map((t) => {
              const y = padT + plotH - t * plotH;
              const lVal = Math.round((series.leftMin + t * (series.leftMax - series.leftMin)) * 10) / 10;
              const rVal = Math.round((series.rightMin + t * (series.rightMax - series.rightMin)) * 10) / 10;
              return (
                <g key={t}>
                  <line
                    x1={padL}
                    x2={padL + plotW}
                    y1={y}
                    y2={y}
                    stroke="#e2e8f0"
                    strokeDasharray="3 3"
                    strokeWidth="1"
                  />
                  <text
                    x={padL - 8}
                    y={y + 3}
                    textAnchor="end"
                    fontSize="10"
                    fontWeight="600"
                    fill={series.primaryColor}
                  >
                    {lVal}
                    {series.leftUnit.trim()}
                  </text>
                  <text
                    x={padL + plotW + 8}
                    y={y + 3}
                    textAnchor="start"
                    fontSize="10"
                    fontWeight="600"
                    fill={series.secondaryColor}
                  >
                    {rVal}
                    {series.rightUnit.trim()}
                  </text>
                </g>
              );
            })}

            {/* Vertical grid lines + X Axis timestamps */}
            {xTickIndices.map((idx) => {
              const x = series.p1Points[idx]?.x ?? padL;
              return (
                <g key={idx}>
                  <line
                    x1={x}
                    x2={x}
                    y1={padT}
                    y2={padT + plotH}
                    stroke="#f1f5f9"
                    strokeWidth="1"
                  />
                  <text
                    x={x}
                    y={height - 10}
                    textAnchor="middle"
                    fontSize="9.5"
                    fill="#64748b"
                  >
                    {formatShortTime(series.slice[idx].recorded_at)}
                  </text>
                </g>
              );
            })}

            {/* Soft area under primary curve */}
            {series.p1Points.length > 1 && (
              <path
                d={`${buildSmoothPath(series.p1Points)} L ${series.p1Points[series.p1Points.length - 1].x} ${padT + plotH} L ${series.p1Points[0].x} ${padT + plotH} Z`}
                fill="url(#aisdPrimaryArea)"
              />
            )}

            {/* Smooth metric lines */}
            <path
              d={buildSmoothPath(series.p1Points)}
              fill="none"
              stroke={series.primaryColor}
              strokeWidth="2.4"
              strokeLinecap="round"
            />
            <path
              d={buildSmoothPath(series.p2Points)}
              fill="none"
              stroke={series.secondaryColor}
              strokeWidth="2.2"
              strokeLinecap="round"
            />

            {/* Show dots when <= 20 points or on single point */}
            {series.slice.length <= 20 &&
              series.p1Points.map((pt, idx) => (
                <g key={idx}>
                  <circle cx={pt.x} cy={pt.y} r="3" fill="#ffffff" stroke={series.primaryColor} strokeWidth="2" />
                  <circle
                    cx={series.p2Points[idx].x}
                    cy={series.p2Points[idx].y}
                    r="3"
                    fill="#ffffff"
                    stroke={series.secondaryColor}
                    strokeWidth="2"
                  />
                </g>
              ))}

            {/* Hover crosshair and markers */}
            {activeP1 && activeP2 && (
              <g>
                <line
                  x1={activeP1.x}
                  x2={activeP1.x}
                  y1={padT}
                  y2={padT + plotH}
                  stroke="#94a3b8"
                  strokeDasharray="4 3"
                  strokeWidth="1.2"
                />
                <circle cx={activeP1.x} cy={activeP1.y} r="5" fill={series.primaryColor} stroke="#ffffff" strokeWidth="2" />
                <circle cx={activeP2.x} cy={activeP2.y} r="5" fill={series.secondaryColor} stroke="#ffffff" strokeWidth="2" />
              </g>
            )}
          </svg>

          {/* Hover floating tooltip */}
          {activeSample && activeP1 && (
            <div
              className="pointer-events-none absolute top-2 z-20 bg-white/95 backdrop-blur border border-slate-200 rounded-lg shadow-md px-3 py-2 text-[11px] space-y-1 min-w-[205px]"
              style={{
                left: activeP1.x > width * 0.62 ? "auto" : `${Math.min(72, (activeP1.x / width) * 100 + 2)}%`,
                right: activeP1.x > width * 0.62 ? `${Math.min(72, 100 - (activeP1.x / width) * 100 + 2)}%` : "auto",
              }}
            >
              <div className="font-bold text-slate-900 flex items-center justify-between gap-2 border-b border-slate-100 pb-1">
                <span>{formatShortTime(activeSample.recorded_at)}</span>
                <span className="text-[10px] font-mono bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
                  {activeSample.source_mode || "ONLINE"}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-500">{series.primaryLabel}:</span>
                <span className="font-bold text-slate-900">
                  {activeP1.val}
                  {series.leftUnit}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-500">{series.secondaryLabel}:</span>
                <span className="font-bold text-slate-900">
                  {activeP2?.val}
                  {series.rightUnit}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-500">IPv4 / DHCP:</span>
                <span className="font-mono text-slate-800">
                  {activeSample.ip_address || "N/A"} ({activeSample.dhcp_enabled === false ? "Static" : "DHCP"})
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-500">Health Score:</span>
                <span
                  className={`font-bold ${
                    (activeSample.health_score ?? 100) >= 80
                      ? "text-emerald-600"
                      : (activeSample.health_score ?? 100) >= 50
                      ? "text-amber-600"
                      : "text-rose-600"
                  }`}
                >
                  {activeSample.health_score ?? 100}%
                </span>
              </div>
            </div>
          )}

          {/* Legend */}
          <div className="flex items-center justify-center gap-6 mt-2 text-xs text-slate-600">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-1 rounded-full inline-block" style={{ backgroundColor: series.primaryColor }} />
              <span className="font-medium">{series.primaryLabel}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-1 rounded-full inline-block" style={{ backgroundColor: series.secondaryColor }} />
              <span className="font-medium">{series.secondaryLabel}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
