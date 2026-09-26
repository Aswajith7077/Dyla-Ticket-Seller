"use client";
import { useServiceMetrics } from "@/hooks/useServiceMetrics";
import { ServicePanel } from "./service-panel";

const NAIVE_URL = process.env.NEXT_PUBLIC_NAIVE_URL!;
const OPT_URL = process.env.NEXT_PUBLIC_OPTIMIZED_URL!;
const CLUSTER_URL = process.env.NEXT_PUBLIC_CLUSTER_URL!;

export function DashboardClient() {
  const naiveSnap = useServiceMetrics(NAIVE_URL);
  const optSnap = useServiceMetrics(OPT_URL);
  const clusterSnap = useServiceMetrics(CLUSTER_URL);

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Service Health</h1>
      <div className="flex gap-4 flex-wrap">
        <ServicePanel label="Naive Store (port 8001)" snap={naiveSnap} />
        <ServicePanel label="Optimized Store (port 8002)" snap={optSnap} />
        <ServicePanel label="Cluster (nginx to 3 instances, port 8003)" snap={clusterSnap} />
      </div>
    </div>
  );
}
