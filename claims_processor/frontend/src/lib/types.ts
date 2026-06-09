export type DecisionType = "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW";

export type TraceStatus = "PASS" | "FAIL" | "WARN" | "INFO" | "ERROR";

export interface TraceEntry {
  component: string;
  step: string;
  status: TraceStatus;
  detail: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

export interface PolicyCheck {
  check_name: string;
  passed: boolean;
  detail: string;
  impact?: string;
}

export interface LineItemDecision {
  description: string;
  claimed_amount: number;
  approved_amount: number;
  reason?: string;
  covered: boolean;
}

export interface FinancialBreakdown {
  claimed_amount: number;
  network_discount_amount: number;
  network_discount_percent: number;
  copay_amount: number;
  copay_percent: number;
  approved_amount: number;
}

export interface ValidationIssue {
  code: string;
  severity: "BLOCKING" | "SOFT_BLOCK" | "WARNING";
  message: string;
  documents_involved: string[];
}

export interface ValidationFailedResult {
  status: "VALIDATION_FAILED";
  claim_id: string;
  errors: string[];
  issues: ValidationIssue[];
  trace: TraceEntry[];
  processing_time_ms: number;
}

export interface ClaimDecisionResult {
  status: "DECIDED";
  claim_id: string;
  decision: DecisionType;
  approved_amount: number;
  claimed_amount: number;
  reason: string;
  confidence_score: number;
  rejection_reasons: string[];
  financial_breakdown?: FinancialBreakdown;
  line_items: LineItemDecision[];
  policy_checks: PolicyCheck[];
  fraud_signals: string[];
  warnings: string[];
  eligibility_date?: string;
  degraded_components: string[];
  processing_errors: string[];
  trace: TraceEntry[];
  processing_time_ms: number;
}

export type ClaimResult = ValidationFailedResult | ClaimDecisionResult;

export interface TestCase {
  case_id: string;
  case_name: string;
  description: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
}

export interface TestCaseRunResult {
  case_id: string;
  case_name: string;
  expected: Record<string, unknown>;
  result: ClaimResult;
}

export interface ClaimSummary {
  claim_id: string;
  status: string;
  decision?: DecisionType;
  approved_amount?: number;
  claimed_amount?: number;
  confidence_score?: number;
  processing_time_ms?: number;
}
