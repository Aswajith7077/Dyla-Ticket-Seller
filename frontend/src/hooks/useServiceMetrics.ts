"use client";
import { useState, useCallback } from "react";
import { fetchHealth, fetchMetrics } from "@/lib/api";
import { useInterval } from "./useInterval";
import type { ServiceSnapshot } from "@/lib/types";

const MAX_HISTORY = 30;

export function useServiceMetrics(baseUrl: string): ServiceSnapshot {
  const [snap, setSnap] = useState<ServiceSnapshot>({
    health: null,
    metrics: null,
    online: false,
    history: [],
  });

  const poll = useCallback(async () => {
    try {
      const [health, metrics] = await Promise.all([
        fetchHealth(baseUrl),
        fetchMetrics(baseUrl),
      ]);
      setSnap((prev) => {
        const point = { t: Date.now(), rps: metrics.rps, p50: metrics.p50_ms, p99: metrics.p99_ms };
        const history = [...prev.history.slice(-(MAX_HISTORY - 1)), point];
        return { health, metrics, online: true, history };
      });
    } catch {
      setSnap((prev) => {
        const point = { t: Date.now(), rps: 0, p50: 0, p99: 0 };
        const history = [...prev.history.slice(-(MAX_HISTORY - 1)), point];
        return { ...prev, online: false, history };
      });
    }
  }, [baseUrl]);

  useInterval(poll, 1000);
  return snap;
}
