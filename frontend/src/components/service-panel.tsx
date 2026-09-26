"use client";
import dynamic from "next/dynamic";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ServiceSnapshot } from "@/lib/types";

const LineChart = dynamic(() => import("recharts").then((m) => m.LineChart), { ssr: false });
const Line = dynamic(() => import("recharts").then((m) => m.Line), { ssr: false });
const XAxis = dynamic(() => import("recharts").then((m) => m.XAxis), { ssr: false });
const YAxis = dynamic(() => import("recharts").then((m) => m.YAxis), { ssr: false });
const Tooltip = dynamic(() => import("recharts").then((m) => m.Tooltip), { ssr: false });
const ResponsiveContainer = dynamic(
  () => import("recharts").then((m) => m.ResponsiveContainer),
  { ssr: false }
);

interface Props {
  label: string;
  snap: ServiceSnapshot;
}

function MetricCard({ title, value }: { title: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs text-muted-foreground">{title}</div>
        <div className="text-xl font-semibold mt-1">{value}</div>
      </CardContent>
    </Card>
  );
}

export function ServicePanel({ label, snap }: Props) {
  const { health, metrics, online, history } = snap;

  if (!online) {
    return (
      <Card className="flex-1">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">{label}</CardTitle>
            <Badge variant="destructive">Offline</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Service Offline — check that the seller is running on port {label.match(/\b\d{4}\b/)?.[0] ?? "800X"}.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="flex-1">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">{label}</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant={online ? "default" : "destructive"}>
              {online ? "Online" : "Offline"}
            </Badge>
            {health && (
              <Badge variant={health.redis_ok ? "default" : "destructive"}>
                {health.redis_ok ? "Redis OK" : "Redis Down"}
              </Badge>
            )}
            {health?.instance_id && health.instance_id !== "standalone" && (
              <Badge variant="outline">Instance {health.instance_id}</Badge>
            )}
            {health && (
              <span className="text-xs text-muted-foreground">Uptime {health.uptime}s</span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <MetricCard title="Requests / sec" value={metrics?.rps ?? 0} />
          <MetricCard title="P50 Latency (ms)" value={metrics?.p50_ms ?? 0} />
          <MetricCard title="P99 Latency (ms)" value={metrics?.p99_ms ?? 0} />
          <MetricCard title="Total Errors" value={metrics?.errors ?? 0} />
        </div>

        <div>
          <div className="text-xs text-muted-foreground mb-2">RPS — last 30s</div>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={history}>
              <XAxis dataKey="t" hide />
              <YAxis width={30} />
              <Tooltip formatter={(v) => [`${v} rps`]} labelFormatter={() => ""} />
              <Line type="monotone" dataKey="rps" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
