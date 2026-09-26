"use client";
import { useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { runLoad } from "@/lib/loadRunner";
import { checkInvariants, percentile } from "@/lib/invariants";
import { postReset, fetchStatus, postSlowInject, postClearSlow } from "@/lib/api";
import type { RequestResult, InvariantResult, LoadConfig } from "@/lib/types";

const BarChart = dynamic(() => import("recharts").then((m) => m.BarChart), { ssr: false });
const Bar = dynamic(() => import("recharts").then((m) => m.Bar), { ssr: false });
const LineChart = dynamic(() => import("recharts").then((m) => m.LineChart), { ssr: false });
const Line = dynamic(() => import("recharts").then((m) => m.Line), { ssr: false });
const XAxis = dynamic(() => import("recharts").then((m) => m.XAxis), { ssr: false });
const YAxis = dynamic(() => import("recharts").then((m) => m.YAxis), { ssr: false });
const Tooltip = dynamic(() => import("recharts").then((m) => m.Tooltip), { ssr: false });
const ReferenceLine = dynamic(() => import("recharts").then((m) => m.ReferenceLine), { ssr: false });
const ResponsiveContainer = dynamic(
  () => import("recharts").then((m) => m.ResponsiveContainer),
  { ssr: false }
);

const NAIVE_URL = process.env.NEXT_PUBLIC_NAIVE_URL!;
const OPT_URL = process.env.NEXT_PUBLIC_OPTIMIZED_URL!;
const CLUSTER_URL = process.env.NEXT_PUBLIC_CLUSTER_URL!;

type Target = "naive" | "optimized" | "both" | "cluster";

function resolveTargetUrl(target: Target): string {
  if (target === "optimized") return OPT_URL;
  if (target === "cluster") return CLUSTER_URL;
  // "both" is a pre-existing option that isn't actually wired to run
  // against both stores in one pass — left as-is, out of scope here.
  return NAIVE_URL;
}

interface RunState {
  running: boolean;
  completed: number;
  total: number;
  results: RequestResult[];
  liveRps: number;
}

interface RunResult {
  target: Target;
  config: LoadConfig;
  results: RequestResult[];
  invariants: InvariantResult[] | null;
  invariantError: string | null;
  metrics: {
    total: number;
    successes: number;
    soldOut: number;
    errors: number;
    rps: number;
    p50: number;
    p99: number;
    min: number;
    max: number;
    durationMs: number;
  };
}

interface FormState {
  target: Target;
  ticketCount: number;
  concurrency: number;
  totalRequests: number;
  duplicateRatio: number;
  userPoolSize: number;
}

function buildConfig(targetUrl: string, form: FormState): LoadConfig {
  return {
    targetUrl,
    ticketCount: form.ticketCount,
    concurrency: form.concurrency,
    totalRequests: form.totalRequests,
    duplicateRatio: form.duplicateRatio,
    userPoolSize: form.userPoolSize,
  };
}

export function LoadClient() {
  const [form, setForm] = useState<FormState>({
    target: "naive",
    ticketCount: 100,
    concurrency: 50,
    totalRequests: 5000,
    duplicateRatio: 0.1,
    userPoolSize: 200,
  });

  const [runState, setRunState] = useState<RunState>({
    running: false,
    completed: 0,
    total: 0,
    results: [],
    liveRps: 0,
  });

  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const reportRef = useRef<HTMLDivElement>(null);
  const lastBatchTime = useRef<number>(Date.now());
  const lastBatchCount = useRef<number>(0);

  const targetUrl = resolveTargetUrl(form.target);

  const startRun = useCallback(
    async (withReset: boolean) => {
      abortRef.current = new AbortController();
      const startTime = Date.now();

      if (withReset) {
        await postReset(targetUrl, form.ticketCount);
      }

      lastBatchTime.current = Date.now();
      lastBatchCount.current = 0;
      setRunState({ running: true, completed: 0, total: form.totalRequests, results: [], liveRps: 0 });
      setRunResult(null);

      const config = buildConfig(targetUrl, form);

      await runLoad(
        config,
        {
          onProgress: (completed, results) => {
            const now = Date.now();
            const elapsed = (now - lastBatchTime.current) / 1000;
            const delta = completed - lastBatchCount.current;
            const liveRps = elapsed > 0 ? delta / elapsed : 0;
            lastBatchTime.current = now;
            lastBatchCount.current = completed;
            setRunState((prev) => ({ ...prev, completed, results, liveRps }));
          },
          onComplete: async (results) => {
            const durationMs = Date.now() - startTime;
            const responseTimes = results.map((r) => r.responseMs);
            const successes = results.filter((r) => r.ticket !== null).length;
            const soldOut = results.filter((r) => r.soldOut).length;
            const errors = results.filter((r) => r.error !== null).length;

            let invariants: InvariantResult[] | null = null;
            let invariantError: string | null = null;
            try {
              const status = await fetchStatus(targetUrl);
              if (typeof status?.sold !== "number" || !Array.isArray(status?.tickets)) {
                throw new Error("unexpected shape");
              }
              invariants = checkInvariants(status, results, form.ticketCount);
            } catch {
              invariantError = "Could not verify invariants — /status returned unexpected data";
            }

            setRunResult({
              target: form.target,
              config,
              results,
              invariants,
              invariantError,
              metrics: {
                total: results.length,
                successes,
                soldOut,
                errors,
                rps: Math.round((results.length / durationMs) * 1000),
                p50: Math.round(percentile(responseTimes, 50)),
                p99: Math.round(percentile(responseTimes, 99)),
                min: results.length ? Math.round(Math.min(...responseTimes)) : 0,
                max: results.length ? Math.round(Math.max(...responseTimes)) : 0,
                durationMs,
              },
            });
            setRunState((prev) => ({ ...prev, running: false }));
          },
        },
        abortRef.current.signal
      );
    },
    [form, targetUrl]
  );

  const histogramData = runResult
    ? [
        { label: "0-10ms", count: 0 },
        { label: "10-25ms", count: 0 },
        { label: "25-50ms", count: 0 },
        { label: "50-100ms", count: 0 },
        { label: "100-250ms", count: 0 },
        { label: "250ms+", count: 0 },
      ].map((bucket, i) => {
        const ranges: Array<[number, number]> = [
          [0, 10],
          [10, 25],
          [25, 50],
          [50, 100],
          [100, 250],
          [250, Infinity],
        ];
        const [lo, hi] = ranges[i];
        const count = runResult.results.filter((r) => r.responseMs >= lo && r.responseMs < hi).length;
        return { ...bucket, count };
      })
    : [];

  const timelineData = runResult
    ? (() => {
        const step = Math.max(1, Math.floor(runResult.results.length / 500));
        return runResult.results
          .filter((_, i) => i % step === 0)
          .map((r, i) => ({ i: i * step, ms: Math.round(r.responseMs) }));
      })()
    : [];

  const instanceData =
    runResult && runResult.target === "cluster"
      ? Object.entries(
          runResult.results.reduce<Record<string, number>>((acc, r) => {
            const instance = r.servedBy ?? "unknown";
            acc[instance] = (acc[instance] ?? 0) + 1;
            return acc;
          }, {})
        ).map(([instance, count]) => ({ instance, count }))
      : [];

  const allPassed = runResult?.invariants?.every((inv) => inv.passed) ?? false;

  return (
    <div className="space-y-6 max-w-5xl">
      <h1 className="text-lg font-semibold">Load Test</h1>

      {/* Config */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex gap-2 items-center flex-wrap">
            {(["naive", "optimized", "both", "cluster"] as Target[]).map((t) => (
              <Button
                key={t}
                size="sm"
                variant={form.target === t ? "default" : "outline"}
                onClick={() => setForm((f) => ({ ...f, target: t }))}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </Button>
            ))}
            {form.target === "cluster" && (
              <span className="text-xs text-muted-foreground">3 instances, nginx LB, port 8003</span>
            )}
          </div>

          <div className="border rounded p-3 space-y-2">
            <div className="text-xs font-medium text-muted-foreground">
              Chaos Controls (optimized / cluster only)
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={form.target === "naive" || form.target === "both"}
                onClick={() => postSlowInject(targetUrl, 10, 200)}
              >
                Inject 200ms Delay (10s)
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={form.target === "naive" || form.target === "both"}
                onClick={() => postClearSlow(targetUrl)}
              >
                Clear Delay
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">Ticket Count</span>
              <input
                type="number"
                className="w-full border rounded px-2 py-1 text-sm bg-background"
                value={form.ticketCount}
                onChange={(e) => setForm((f) => ({ ...f, ticketCount: +e.target.value }))}
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">Total Requests</span>
              <input
                type="number"
                className="w-full border rounded px-2 py-1 text-sm bg-background"
                value={form.totalRequests}
                onChange={(e) => setForm((f) => ({ ...f, totalRequests: +e.target.value }))}
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">User Pool Size</span>
              <input
                type="number"
                className="w-full border rounded px-2 py-1 text-sm bg-background"
                value={form.userPoolSize}
                onChange={(e) => setForm((f) => ({ ...f, userPoolSize: +e.target.value }))}
              />
            </label>
          </div>

          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Concurrency: {form.concurrency}</span>
            <Slider
              min={1}
              max={500}
              step={1}
              value={[form.concurrency]}
              onValueChange={([v]) => setForm((f) => ({ ...f, concurrency: v }))}
            />
          </div>

          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">
              Duplicate Ratio: {(form.duplicateRatio * 100).toFixed(0)}%
            </span>
            <Slider
              min={0}
              max={1}
              step={0.01}
              value={[form.duplicateRatio]}
              onValueChange={([v]) => setForm((f) => ({ ...f, duplicateRatio: v }))}
            />
          </div>

          <div className="flex gap-2">
            <Button disabled={runState.running} onClick={() => startRun(true)}>
              Reset & Run
            </Button>
            <Button variant="outline" disabled={runState.running} onClick={() => startRun(false)}>
              Run Without Reset
            </Button>
            {runState.running && (
              <Button variant="destructive" onClick={() => abortRef.current?.abort()}>
                Stop
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Live run */}
      {runState.running && (
        <Card className="border-primary animate-pulse">
          <CardHeader>
            <CardTitle className="text-sm">Running…</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Progress value={(runState.completed / runState.total) * 100} />
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <span className="text-muted-foreground">Sent: </span>
                {runState.completed}
              </div>
              <div>
                <span className="text-muted-foreground">Tickets: </span>
                {runState.results.filter((r) => r.ticket !== null).length}
              </div>
              <div>
                <span className="text-muted-foreground">RPS: </span>
                {Math.round(runState.liveRps)}
              </div>
              <div>
                <span className="text-muted-foreground">Sold Out: </span>
                {runState.results.filter((r) => r.soldOut).length}
              </div>
              <div>
                <span className="text-muted-foreground">Errors: </span>
                {runState.results.filter((r) => r.error !== null).length}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {runResult && (
        <div ref={reportRef} className="space-y-6">
          {/* Invariants */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">Invariant Check</CardTitle>
                {runResult.invariants && (
                  <Badge variant={allPassed ? "default" : "destructive"}>
                    {allPassed ? "ALL PASSED" : "VIOLATIONS FOUND"}
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {runResult.invariants ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Invariant</TableHead>
                      <TableHead>Result</TableHead>
                      <TableHead>Detail</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {runResult.invariants.map((inv) => (
                      <TableRow key={inv.name}>
                        <TableCell className="font-medium">{inv.name}</TableCell>
                        <TableCell>
                          <Badge variant={inv.passed ? "default" : "destructive"}>
                            {inv.passed ? "PASS" : "FAIL"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{inv.detail}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-sm text-muted-foreground">{runResult.invariantError}</p>
              )}
            </CardContent>
          </Card>

          {/* Metrics */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Metrics Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableBody>
                  {(
                    [
                      ["Total Requests", runResult.metrics.total],
                      ["Successful (ticket issued)", runResult.metrics.successes],
                      ["Sold Out Responses", runResult.metrics.soldOut],
                      ["Errors", runResult.metrics.errors],
                      ["Requests / Second", runResult.metrics.rps],
                      ["Median Response Time", `${runResult.metrics.p50} ms`],
                      ["P99 Response Time", `${runResult.metrics.p99} ms`],
                      ["Min Response Time", `${runResult.metrics.min} ms`],
                      ["Max Response Time", `${runResult.metrics.max} ms`],
                      ["Duration", `${(runResult.metrics.durationMs / 1000).toFixed(2)} s`],
                    ] as Array<[string, string | number]>
                  ).map(([label, value]) => (
                    <TableRow key={label}>
                      <TableCell className="text-muted-foreground text-sm">{label}</TableCell>
                      <TableCell className="font-medium text-sm">{value}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Charts */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Response Time Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={histogramData}>
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="count" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Response Time Timeline</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={timelineData}>
                  <XAxis dataKey="i" hide />
                  <YAxis />
                  <Tooltip formatter={(v) => [`${v} ms`]} labelFormatter={() => ""} />
                  <ReferenceLine
                    y={runResult.metrics.p99}
                    stroke="red"
                    strokeDasharray="4 2"
                    label={{ value: "p99", position: "right", fontSize: 10 }}
                  />
                  <Line type="monotone" dataKey="ms" dot={false} strokeWidth={1} />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {runResult.target === "cluster" && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Load Distribution Across Instances</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={instanceData}>
                    <XAxis dataKey="instance" tick={{ fontSize: 11 }} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          <Button onClick={() => downloadPdf(reportRef, runResult)}>Download Report (PDF)</Button>
        </div>
      )}
    </div>
  );
}

async function downloadPdf(reportRef: React.RefObject<HTMLDivElement | null>, result: RunResult) {
  const { default: jsPDF } = await import("jspdf");
  const { default: html2canvas } = await import("html2canvas-pro");

  if (!reportRef.current) return;

  const canvas = await html2canvas(reportRef.current, { scale: 1.5 });
  const imgData = canvas.toDataURL("image/png");
  const pdf = new jsPDF({ orientation: "portrait", unit: "px", format: "a4" });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const imgWidth = pageWidth;
  const imgHeight = (canvas.height * imgWidth) / canvas.width;

  pdf.setFontSize(12);
  pdf.text(`Load Test Report — ${result.target} — ${new Date().toISOString()}`, 10, 20);
  pdf.addImage(imgData, "PNG", 0, 30, imgWidth, imgHeight);
  pdf.save(`load-report-${result.target}-${Date.now()}.pdf`);
}
