import { Nav } from "@/components/nav";
import { DashboardClient } from "@/components/dashboard-client";

export default function DashboardPage() {
  return (
    <>
      <Nav />
      <main className="p-6">
        <DashboardClient />
      </main>
    </>
  );
}
