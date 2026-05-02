"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const NAV_ITEMS = [
  { href: "/admin/proposals", label: "Proposals" },
  { href: "/admin/trends", label: "Trends" },
  { href: "/admin/knowledge-base", label: "Knowledge Base" },
  { href: "/admin/departments", label: "Departments" },
] as const;

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("admin_token");
    if (!token && pathname !== "/admin/login") {
      router.replace("/admin/login");
    } else {
      setReady(true);
    }
  }, [pathname, router]);

  const handleLogout = () => {
    localStorage.removeItem("admin_token");
    router.replace("/admin/login");
  };

  if (pathname === "/admin/login") {
    return <>{children}</>;
  }

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950">
        <span className="text-sm text-zinc-400">Loading…</span>
      </div>
    );
  }

  return (
    <div className="flex h-dvh min-h-0 overflow-hidden bg-zinc-950 text-white">
      {/* Sidebar — viewport-height shell so Log out stays pinned; main scrolls alone */}
      <aside className="flex h-full min-h-0 w-52 shrink-0 flex-col border-r border-zinc-800 bg-zinc-900">
        <div className="shrink-0 px-5 py-5">
          <span className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
            OIAgent
          </span>
          <p className="mt-0.5 text-sm font-medium text-white">
            Admin Dashboard
          </p>
        </div>

        <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
          {NAV_ITEMS.map(({ href, label }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center rounded px-3 py-2 text-sm transition ${
                  active
                    ? "bg-zinc-700 text-white"
                    : "text-zinc-400 hover:bg-zinc-800 hover:text-white"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="shrink-0 border-t border-zinc-800 p-4">
          <button
            onClick={handleLogout}
            className="w-full rounded px-3 py-2 text-left text-sm text-zinc-400 transition hover:bg-zinc-800 hover:text-white"
          >
            Log out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</main>
    </div>
  );
}
