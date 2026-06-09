"use client";

import type { ClaimResult, DecisionType, FinancialBreakdown, LineItemDecision, PolicyCheck } from "@/lib/types";

function fmt(n: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n);
}

const DECISION_STYLES: Record<string, { bg: string; text: string; border: string; label: string }> = {
  APPROVED: { bg: "bg-green-900/30", text: "text-green-400", border: "border-green-700", label: "Approved" },
  PARTIAL: { bg: "bg-yellow-900/30", text: "text-yellow-400", border: "border-yellow-700", label: "Partial Approval" },
  REJECTED: { bg: "bg-red-900/30", text: "text-red-400", border: "border-red-700", label: "Rejected" },
  MANUAL_REVIEW: { bg: "bg-blue-900/30", text: "text-blue-400", border: "border-blue-700", label: "Manual Review" },
  BLOCKED: { bg: "bg-orange-900/30", text: "text-orange-400", border: "border-orange-700", label: "Blocked" },
};

export function DecisionBadge({ decision, size = "md" }: { decision: DecisionType | null; size?: "sm" | "md" }) {
  const key = decision ?? "BLOCKED";
  const style = DECISION_STYLES[key] ?? DECISION_STYLES.BLOCKED;
  const sizeClass = size === "sm" ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1";
  return (
    <span className={`${sizeClass} rounded font-semibold ${style.bg} ${style.text} border ${style.border}`}>
      {style.label}
    </span>
  );
}

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? "bg-green-500" : pct >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>Confidence</span>
        <span className="font-mono">{pct}%</span>
      </div>
      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function FinancialBreakdownView({ bd }: { bd: FinancialBreakdown }) {
  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Financial Breakdown</h4>
      <div className="space-y-2">
        <Row label="Claimed Amount" value={fmt(bd.claimed_amount)} />
        {bd.network_discount_amount > 0 && (
          <Row
            label={`Network Discount (${bd.network_discount_percent}%)`}
            value={`-${fmt(bd.network_discount_amount)}`}
            valueClass="text-blue-400"
          />
        )}
        {bd.copay_amount > 0 && (
          <Row
            label={`Co-pay (${bd.copay_percent}% member liability)`}
            value={`-${fmt(bd.copay_amount)}`}
            valueClass="text-yellow-400"
          />
        )}
        <div className="border-t border-gray-700 pt-2 mt-2">
          <Row label="Approved Amount" value={fmt(bd.approved_amount)} valueClass="text-green-400 font-bold text-base" />
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, valueClass = "text-white" }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-sm text-gray-400">{label}</span>
      <span className={`text-sm font-mono ${valueClass}`}>{value}</span>
    </div>
  );
}

function LineItemsTable({ items }: { items: LineItemDecision[] }) {
  if (!items.length) return null;
  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 overflow-hidden">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3 border-b border-gray-700">
        Line Items
      </h4>
      <table className="w-full">
        <thead>
          <tr className="text-xs text-gray-500 border-b border-gray-700/50">
            <th className="text-left px-4 py-2 font-normal">Description</th>
            <th className="text-right px-4 py-2 font-normal">Claimed</th>
            <th className="text-right px-4 py-2 font-normal">Approved</th>
            <th className="text-right px-4 py-2 font-normal">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={i} className="border-b border-gray-700/30 last:border-0">
              <td className="px-4 py-2.5">
                <div className="text-sm text-white">{item.description}</div>
                {item.reason && <div className="text-xs text-gray-500 mt-0.5">{item.reason}</div>}
              </td>
              <td className="px-4 py-2.5 text-right text-sm font-mono text-gray-300">{fmt(item.claimed_amount)}</td>
              <td className="px-4 py-2.5 text-right text-sm font-mono">
                <span className={item.covered ? "text-green-400" : "text-red-400"}>{fmt(item.approved_amount)}</span>
              </td>
              <td className="px-4 py-2.5 text-right">
                {item.covered ? (
                  <span className="text-xs text-green-400">Covered</span>
                ) : (
                  <span className="text-xs text-red-400">Excluded</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PolicyChecks({ checks }: { checks: PolicyCheck[] }) {
  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3 border-b border-gray-700">
        Policy Checks
      </h4>
      <div className="divide-y divide-gray-700/50">
        {checks.map((c, i) => (
          <div key={i} className="px-4 py-3 flex gap-3">
            <div className="mt-0.5 shrink-0">
              {c.passed ? (
                <svg className="w-4 h-4 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-4 h-4 text-red-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-mono text-gray-500">{c.check_name}</div>
              <div className="text-sm text-gray-300 mt-0.5">{c.detail}</div>
              {c.impact && <div className="text-xs text-blue-400 mt-1">{c.impact}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DecisionCard({ result }: { result: ClaimResult }) {
  if (result.status === "VALIDATION_FAILED") {
    return (
      <div className="space-y-4">
        <div className="p-5 rounded-xl bg-orange-900/20 border border-orange-700">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-orange-800/40">
              <svg className="w-5 h-5 text-orange-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-orange-300 mb-1">Document Validation Failed</h3>
              <p className="text-sm text-gray-400 mb-3">
                The claim cannot be processed until the following issue(s) are resolved:
              </p>
              <div className="space-y-2">
                {result.errors.map((err, i) => (
                  <div key={i} className="bg-orange-900/30 rounded-lg p-3 text-sm text-orange-200 border border-orange-800/50">
                    {err}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div className="text-xs text-gray-500 font-mono">Claim ID: {result.claim_id}</div>
      </div>
    );
  }

  const d = result;
  const style = DECISION_STYLES[d.decision] ?? DECISION_STYLES.BLOCKED;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className={`p-5 rounded-xl ${style.bg} border ${style.border}`}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <DecisionBadge decision={d.decision} />
            <div className="mt-2">
              {d.decision === "APPROVED" || d.decision === "PARTIAL" ? (
                <div className="text-3xl font-bold text-white">{fmt(d.approved_amount)}</div>
              ) : (
                <div className="text-3xl font-bold text-white">—</div>
              )}
              <div className="text-sm text-gray-400 mt-0.5">
                of {fmt(d.claimed_amount)} claimed
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-gray-500 font-mono">{d.claim_id}</div>
            <div className="text-xs text-gray-500 mt-1">{d.processing_time_ms}ms</div>
          </div>
        </div>
        <div className="mt-3 text-sm text-gray-300">{d.reason}</div>
        {d.eligibility_date && (
          <div className="mt-2 text-xs text-yellow-400">
            Eligible from: {d.eligibility_date}
          </div>
        )}
      </div>

      {/* Confidence */}
      <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
        <ConfidenceBar score={d.confidence_score} />
        {d.degraded_components.length > 0 && (
          <div className="mt-2 text-xs text-yellow-400">
            Degraded components: {d.degraded_components.join(", ")}
          </div>
        )}
      </div>

      {/* Financial breakdown */}
      {d.financial_breakdown && d.financial_breakdown.network_discount_amount > 0 && (
        <FinancialBreakdownView bd={d.financial_breakdown} />
      )}

      {/* Line items */}
      {d.line_items.length > 0 && <LineItemsTable items={d.line_items} />}

      {/* Fraud signals */}
      {d.fraud_signals.length > 0 && (
        <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg p-4">
          <h4 className="text-xs font-semibold text-yellow-400 uppercase tracking-wider mb-2">
            Fraud Signals
          </h4>
          <div className="space-y-1">
            {d.fraud_signals.map((s, i) => (
              <div key={i} className="text-sm text-yellow-200">{s}</div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings */}
      {d.warnings.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Warnings</h4>
          <div className="space-y-1">
            {d.warnings.map((w, i) => (
              <div key={i} className="text-sm text-gray-300">{w}</div>
            ))}
          </div>
        </div>
      )}

      {/* Policy checks */}
      {d.policy_checks.length > 0 && <PolicyChecks checks={d.policy_checks} />}
    </div>
  );
}
