import axios from "axios";
import type { HealthResponse, MetricsResponse, StatusResponse } from "./types";

function url(base: string, path: string) {
  return `${base}${path}`;
}

export async function fetchHealth(base: string): Promise<HealthResponse> {
  const r = await axios.get(url(base, "/health"), { timeout: 2000 });
  return r.data;
}

export async function fetchMetrics(base: string): Promise<MetricsResponse> {
  const r = await axios.get(url(base, "/metrics"), { timeout: 2000 });
  return r.data;
}

export async function fetchStatus(base: string): Promise<StatusResponse> {
  const r = await axios.get(url(base, "/status"), { timeout: 5000 });
  return r.data;
}

export async function postReset(base: string, ticketCount: number): Promise<void> {
  await axios.post(url(base, "/reset"), { ticket_count: ticketCount });
}

export async function postSlowInject(
  base: string,
  seconds: number,
  delayMs: number
): Promise<void> {
  await axios.post(url(base, "/debug/slow"), null, { params: { seconds, delay_ms: delayMs } });
}

export async function postClearSlow(base: string): Promise<void> {
  await axios.post(url(base, "/debug/slow/clear"));
}

export async function postBuy(
  base: string,
  userId: string,
  requestId: string
): Promise<{ ticket?: number; sold_out?: boolean }> {
  const r = await axios.post(url(base, "/buy"), { user_id: userId, request_id: requestId });
  return r.data;
}
