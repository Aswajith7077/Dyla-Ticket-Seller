import type { RequestResult, StatusResponse, InvariantResult } from "./types";

export function checkInvariants(
  status: StatusResponse,
  results: RequestResult[],
  ticketCount: number
): InvariantResult[] {
  const ticketNums = Object.values(status.tickets);

  const noOversell: InvariantResult = {
    name: "No Oversell",
    passed: status.sold <= ticketCount,
    detail: `Sold ${status.sold} of ${ticketCount} available tickets`,
  };

  const numSet = new Set(ticketNums);
  const dupeCount = ticketNums.length - numSet.size;
  const noDoubleIssue: InvariantResult = {
    name: "No Double Issue",
    passed: dupeCount === 0,
    detail: dupeCount === 0 ? "All ticket numbers unique" : `${dupeCount} duplicate ticket number(s) found`,
  };

  const byRequestId = new Map<string, RequestResult[]>();
  for (const r of results) {
    if (!byRequestId.has(r.requestId)) byRequestId.set(r.requestId, []);
    byRequestId.get(r.requestId)!.push(r);
  }
  let idempViolations = 0;
  for (const [, reqs] of byRequestId) {
    if (reqs.length < 2) continue;
    const tickets = reqs.map((r) => r.ticket).filter((t) => t !== null);
    const uniqueTickets = new Set(tickets);
    if (uniqueTickets.size > 1) idempViolations++;
  }
  const idempotency: InvariantResult = {
    name: "Idempotency Held",
    passed: idempViolations === 0,
    detail:
      idempViolations === 0
        ? "Duplicate request IDs returned consistent responses"
        : `${idempViolations} request ID(s) returned different ticket numbers across calls`,
  };

  const countMatches: InvariantResult = {
    name: "Count Matches",
    passed: status.sold === ticketNums.length,
    detail: `/status.sold (${status.sold}) ${status.sold === ticketNums.length ? "matches" : "does not match"} tickets array length (${ticketNums.length})`,
  };

  return [noOversell, noDoubleIssue, idempotency, countMatches];
}

export function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.floor((p / 100) * sorted.length);
  return sorted[Math.min(idx, sorted.length - 1)];
}
