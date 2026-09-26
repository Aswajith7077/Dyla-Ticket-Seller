"use client";

import { usePathname } from "next/navigation";

const titles: Record<string, string> = {
  "/": "Health Check",
  "/load": "Load Test",
};

export function PageTitle() {
  const pathname = usePathname();
  return <span className="text-sm font-medium">{titles[pathname] ?? "Dyla"}</span>;
}
