"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";

export function Nav() {
  const pathname = usePathname();
  const { data: session } = useSession();

  return (
    <nav className="border-b px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <span className="font-semibold text-sm">Ticket Load Tester</span>
        <div className="flex gap-1">
          <Link href="/">
            <Button variant={pathname === "/" ? "default" : "ghost"} size="sm">
              Dashboard
            </Button>
          </Link>
          <Link href="/load">
            <Button variant={pathname === "/load" ? "default" : "ghost"} size="sm">
              Load Test
            </Button>
          </Link>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {session?.user?.email && (
          <span className="text-xs text-muted-foreground">{session.user.email}</span>
        )}
        <Button variant="outline" size="sm" onClick={() => signOut()}>
          Sign out
        </Button>
      </div>
    </nav>
  );
}
