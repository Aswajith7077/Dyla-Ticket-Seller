import type { LoadConfig, RequestResult } from "./types";

export interface LoadRunnerCallbacks {
  onProgress: (completed: number, results: RequestResult[]) => void;
  onComplete: (results: RequestResult[]) => void;
}

function generateId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export async function runLoad(
  config: LoadConfig,
  callbacks: LoadRunnerCallbacks,
  signal: AbortSignal
): Promise<void> {
  const { targetUrl, concurrency, totalRequests, duplicateRatio, userPoolSize } = config;

  const userPool = Array.from({ length: userPoolSize }, (_, i) => `user_${i}`);

  const uniqueCount = Math.floor(totalRequests * (1 - duplicateRatio));
  const uniqueIds = Array.from({ length: uniqueCount }, () => generateId());

  const allPairs: Array<{ userId: string; requestId: string; isDuplicate: boolean }> = [];

  for (let i = 0; i < totalRequests; i++) {
    const userId = userPool[Math.floor(Math.random() * userPool.length)];
    if (i < uniqueCount) {
      allPairs.push({ userId, requestId: uniqueIds[i], isDuplicate: false });
    } else {
      const dupId = uniqueIds[Math.floor(Math.random() * uniqueIds.length)];
      allPairs.push({ userId, requestId: dupId, isDuplicate: true });
    }
  }

  for (let i = allPairs.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [allPairs[i], allPairs[j]] = [allPairs[j], allPairs[i]];
  }

  const results: RequestResult[] = [];

  for (let i = 0; i < allPairs.length; i += concurrency) {
    if (signal.aborted) break;
    const batch = allPairs.slice(i, i + concurrency);

    const batchResults = await Promise.allSettled(
      batch.map(async (pair) => {
        const start = performance.now();
        try {
          const res = await fetch(`${targetUrl}/buy`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: pair.userId, request_id: pair.requestId }),
            signal,
          });
          const data = await res.json();
          const responseMs = performance.now() - start;
          return {
            requestId: pair.requestId,
            userId: pair.userId,
            isDuplicate: pair.isDuplicate,
            statusCode: res.status,
            responseMs,
            ticket: data.ticket ?? null,
            soldOut: data.sold_out ?? false,
            error: null,
            timestamp: Date.now(),
          } satisfies RequestResult;
        } catch (err) {
          return {
            requestId: pair.requestId,
            userId: pair.userId,
            isDuplicate: pair.isDuplicate,
            statusCode: 0,
            responseMs: performance.now() - start,
            ticket: null,
            soldOut: false,
            error: err instanceof Error ? err.message : "unknown",
            timestamp: Date.now(),
          } satisfies RequestResult;
        }
      })
    );

    for (const r of batchResults) {
      if (r.status === "fulfilled") results.push(r.value);
    }

    callbacks.onProgress(results.length, results);
  }

  callbacks.onComplete(results);
}
