export interface HealthResponse {
  status: string;
  uptime: number;
  redis_ok: boolean;
  service: "naive" | "optimized";
}

export interface MetricsResponse {
  rps: number;
  p50_ms: number;
  p99_ms: number;
  total_requests: number;
  errors: number;
}

export interface StatusResponse {
  sold: number;
  tickets: Record<string, number>;
}

export interface ServiceSnapshot {
  health: HealthResponse | null;
  metrics: MetricsResponse | null;
  online: boolean;
  history: Array<{ t: number; rps: number; p50: number; p99: number }>;
}

export interface RequestResult {
  requestId: string;
  userId: string;
  isDuplicate: boolean;
  statusCode: number;
  responseMs: number;
  ticket: number | null;
  soldOut: boolean;
  error: string | null;
  timestamp: number;
}

export interface LoadConfig {
  targetUrl: string;
  ticketCount: number;
  concurrency: number;
  totalRequests: number;
  duplicateRatio: number;
  userPoolSize: number;
}

export interface InvariantResult {
  name: string;
  passed: boolean;
  detail: string;
}
