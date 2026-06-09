"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TestCase, TestCaseRunResult, ClaimResult } from "@/lib/types";
import { DecisionBadge } from "@/components/DecisionCard";
import { DecisionCard } from "@/components/DecisionCard";
import { TraceViewer } from "@/components/TraceViewer";

export default function HomePage() {
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, TestCaseRunResult>>({});
  const [selectedResult, setSelectedResult] = useState<TestCaseRunResult | null>(null);
  const [runningAll, setRunningAll] = useState(false);
  const [allSummary, setAllSummary] = useState<{ passing: number; failing: number; total: number } | null>(null);

  useEffect(() => {
    api.listTestCases().then((d) => setTestCases(d.test_cases)).catch(console.error);
  }, []);

  async function runCase(caseId: string) {
    setRunning(caseId);
    try {
      const result = await api.runTestCase(caseId);
      setResults((prev) => ({ ...prev, [caseId]: result }));
      setSelectedResult(result);
    } catch (e) {
      console.error(e);
    } finally {
      setRunning(null);
    }
  }

  async function runAll() {
    setRunningAll(true);
    setResults({});
    try {
      const data = await api.runAllTestCases();
      setAllSummary(data.summary);
      const newResults: Record<string, TestCaseRunResult> = {};
      for (const c of data.cases) {
        newResults[c.case_id] = {
          case_id: c.case_id,
          case_name: c.case_name,
          expected: {},
          result: c.result,
        };
      }
      setResults(newResults);
    } catch (e) {
      console.error(e);
    } finally {
      setRunningAll(false);
    }
  }

  const getDecisionFromResult = (r: ClaimResult) => {
    if (r.status === "VALIDATION_FAILED") return null;
    return r.decision;
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
      {/* Left panel — test case list */}
      <div className="xl:col-span-1">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Test Cases</h2>
          <button
            onClick={runAll}
            disabled={runningAll}
            className="text-xs px-3 py-1.5 bg-plum-700 hover:bg-plum-600 disabled:opacity-50 rounded-md text-white transition-colors"
          >
            {runningAll ? "Running..." : "Run All"}
          </button>
        </div>

        {allSummary && (
          <div className="mb-4 p-3 rounded-lg bg-gray-800 border border-gray-700 text-sm grid grid-cols-3 gap-2 text-center">
            <div>
              <div className="text-2xl font-bold text-white">{allSummary.total}</div>
              <div className="text-gray-400 text-xs">Total</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-green-400">{allSummary.passing}</div>
              <div className="text-gray-400 text-xs">Passing</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-red-400">{allSummary.failing}</div>
              <div className="text-gray-400 text-xs">Failing</div>
            </div>
          </div>
        )}

        <div className="space-y-2">
          {testCases.map((tc) => {
            const res = results[tc.case_id];
            const decision = res ? getDecisionFromResult(res.result) : null;
            const isSelected = selectedResult?.case_id === tc.case_id;

            return (
              <button
                key={tc.case_id}
                onClick={() => {
                  if (res) {
                    setSelectedResult(res);
                  } else {
                    runCase(tc.case_id);
                  }
                }}
                className={`w-full text-left p-3 rounded-lg border transition-all ${
                  isSelected
                    ? "bg-plum-900/50 border-plum-600"
                    : "bg-gray-900 border-gray-800 hover:border-gray-600"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-gray-500 font-mono">{tc.case_id}</div>
                    <div className="text-sm text-white font-medium truncate">{tc.case_name}</div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {running === tc.case_id ? (
                      <span className="text-xs text-gray-400 animate-pulse">running...</span>
                    ) : res ? (
                      <>
                        {decision ? (
                          <DecisionBadge decision={decision} size="sm" />
                        ) : (
                          <span className="text-xs px-2 py-0.5 rounded bg-orange-900/40 text-orange-400 border border-orange-800">
                            BLOCKED
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-xs text-gray-500 px-2 py-0.5 rounded bg-gray-800">
                        Run
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-xs text-gray-500 mt-1 line-clamp-2 leading-relaxed">
                  {tc.description}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Right panel — result detail */}
      <div className="xl:col-span-2">
        {selectedResult ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-gray-500 font-mono">{selectedResult.case_id}</span>
                <h2 className="text-lg font-semibold text-white">{selectedResult.case_name}</h2>
              </div>
              <button
                onClick={() => runCase(selectedResult.case_id)}
                disabled={running === selectedResult.case_id}
                className="text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-md text-gray-300 transition-colors"
              >
                {running === selectedResult.case_id ? "Re-running..." : "Re-run"}
              </button>
            </div>

            <DecisionCard result={selectedResult.result} />
            <TraceViewer trace={selectedResult.result.trace} />
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-center py-20">
            <div>
              <div className="w-16 h-16 rounded-2xl bg-gray-800 flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <h3 className="text-white font-medium mb-1">No claim selected</h3>
              <p className="text-gray-500 text-sm">
                Click a test case to run it and see the full decision trace.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
