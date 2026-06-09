"use client";

import { useState } from "react";
import type { TraceEntry, TraceStatus } from "@/lib/types";

const STATUS_STYLES: Record<TraceStatus, { dot: string; text: string; bg: string }> = {
  PASS: { dot: "bg-green-400", text: "text-green-400", bg: "bg-green-900/10" },
  FAIL: { dot: "bg-red-400", text: "text-red-400", bg: "bg-red-900/10" },
  WARN: { dot: "bg-yellow-400", text: "text-yellow-400", bg: "bg-yellow-900/10" },
  INFO: { dot: "bg-blue-400", text: "text-blue-400", bg: "bg-blue-900/10" },
  ERROR: { dot: "bg-red-500", text: "text-red-300", bg: "bg-red-900/20" },
};

const COMPONENT_COLORS: Record<string, string> = {
  pipeline: "text-purple-400",
  document_validator: "text-blue-400",
  document_extractor: "text-cyan-400",
  fraud_detector: "text-yellow-400",
  policy_engine: "text-green-400",
  decision_maker: "text-orange-400",
};

function groupByComponent(entries: TraceEntry[]): Map<string, TraceEntry[]> {
  const map = new Map<string, TraceEntry[]>();
  for (const e of entries) {
    if (!map.has(e.component)) map.set(e.component, []);
    map.get(e.component)!.push(e);
  }
  return map;
}

function TraceRow({ entry }: { entry: TraceEntry }) {
  const [expanded, setExpanded] = useState(false);
  const style = STATUS_STYLES[entry.status] ?? STATUS_STYLES.INFO;
  const hasData = entry.data && Object.keys(entry.data).length > 0;

  return (
    <div className={`rounded-lg border border-transparent transition-colors ${expanded ? style.bg : "hover:bg-gray-800/50"}`}>
      <button
        className="w-full text-left px-3 py-2 flex items-start gap-2"
        onClick={() => hasData && setExpanded((v) => !v)}
        disabled={!hasData}
      >
        <div className="mt-1.5 shrink-0">
          <div className={`w-2 h-2 rounded-full ${style.dot}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-xs font-mono font-medium ${style.text}`}>{entry.status}</span>
            <span className="text-xs text-gray-500 font-mono">{entry.step}</span>
          </div>
          <div className="text-sm text-gray-300 mt-0.5 leading-snug">{entry.detail}</div>
        </div>
        {hasData && (
          <svg
            className={`w-4 h-4 text-gray-600 shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-90" : ""}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        )}
      </button>
      {expanded && entry.data && (
        <div className="px-4 pb-3">
          <pre className="text-xs text-gray-400 bg-gray-900 rounded p-2 overflow-x-auto font-mono leading-relaxed">
            {JSON.stringify(entry.data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export function TraceViewer({ trace }: { trace: TraceEntry[] }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [filterStatus, setFilterStatus] = useState<TraceStatus | "ALL">("ALL");

  if (!trace || trace.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 text-center text-gray-500 text-sm">
        No trace available
      </div>
    );
  }

  const groups = groupByComponent(trace);

  const toggleGroup = (component: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(component)) next.delete(component);
      else next.add(component);
      return next;
    });
  };

  const filteredTrace = filterStatus === "ALL"
    ? trace
    : trace.filter((e) => e.status === filterStatus);

  const statusCounts = trace.reduce<Partial<Record<TraceStatus, number>>>((acc, e) => {
    acc[e.status] = (acc[e.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">
          Audit Trace
          <span className="ml-2 text-xs text-gray-500 font-normal font-mono">{trace.length} events</span>
        </h3>
        <div className="flex items-center gap-1">
          {(["ALL", "PASS", "FAIL", "WARN", "ERROR"] as const).map((s) => {
            const count = s === "ALL" ? trace.length : (statusCounts[s as TraceStatus] ?? 0);
            if (count === 0 && s !== "ALL") return null;
            return (
              <button
                key={s}
                onClick={() => setFilterStatus(s)}
                className={`text-xs px-2 py-1 rounded transition-colors ${
                  filterStatus === s
                    ? "bg-gray-700 text-white"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {s === "ALL" ? "All" : s} {s !== "ALL" && <span className="opacity-60">{count}</span>}
              </button>
            );
          })}
        </div>
      </div>

      <div className="p-3 space-y-3">
        {filterStatus !== "ALL" ? (
          <div className="space-y-1">
            {filteredTrace.map((e, i) => <TraceRow key={i} entry={e} />)}
          </div>
        ) : (
          Array.from(groups.entries()).map(([component, entries]) => {
            const isCollapsed = collapsed.has(component);
            const failCount = entries.filter((e) => e.status === "FAIL" || e.status === "ERROR").length;
            const warnCount = entries.filter((e) => e.status === "WARN").length;
            const componentColor = COMPONENT_COLORS[component] ?? "text-gray-400";

            return (
              <div key={component} className="border border-gray-800 rounded-lg overflow-hidden">
                <button
                  onClick={() => toggleGroup(component)}
                  className="w-full flex items-center justify-between px-3 py-2 bg-gray-800/60 hover:bg-gray-800 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <svg
                      className={`w-3.5 h-3.5 text-gray-500 transition-transform ${isCollapsed ? "-rotate-90" : ""}`}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
                    </svg>
                    <span className={`text-xs font-mono font-semibold ${componentColor}`}>{component}</span>
                    <span className="text-xs text-gray-600">{entries.length} events</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {failCount > 0 && (
                      <span className="text-xs bg-red-900/40 text-red-400 border border-red-800 px-1.5 py-0.5 rounded">
                        {failCount} fail
                      </span>
                    )}
                    {warnCount > 0 && (
                      <span className="text-xs bg-yellow-900/40 text-yellow-400 border border-yellow-800 px-1.5 py-0.5 rounded">
                        {warnCount} warn
                      </span>
                    )}
                  </div>
                </button>
                {!isCollapsed && (
                  <div className="px-2 py-1 space-y-0.5">
                    {entries.map((e, i) => <TraceRow key={i} entry={e} />)}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
