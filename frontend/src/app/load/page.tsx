import { Nav } from "@/components/nav";
import { LoadClient } from "@/components/load-client";

export default function LoadPage() {
  return (
    <>
      <Nav />
      <main className="p-6">
        <LoadClient />
      </main>
    </>
  );
}
