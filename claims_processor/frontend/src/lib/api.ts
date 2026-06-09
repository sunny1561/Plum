import type {
  ClaimResult,
  ClaimSummary,
  TestCase,
  TestCaseRunResult,
} from "./types";

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listClaims(): Promise<ClaimSummary[]> {
    return request("/claims");
  },

  getClaim(claimId: string): Promise<ClaimResult> {
    return request(`/claims/${claimId}`);
  },

  submitClaim(body: unknown): Promise<ClaimResult> {
    return request("/claims", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  listTestCases(): Promise<{ test_cases: TestCase[] }> {
    return request("/test-cases");
  },

  runTestCase(caseId: string): Promise<TestCaseRunResult> {
    return request(`/test-cases/${caseId}/run`, { method: "POST" });
  },

  runAllTestCases(): Promise<{
    summary: { total: number; passing: number; failing: number };
    cases: Array<{ case_id: string; case_name: string; passed: boolean; result: ClaimResult }>;
  }> {
    return request("/test-cases/run-all", { method: "POST" });
  },

  listMembers(): Promise<unknown[]> {
    return request("/members");
  },
};
