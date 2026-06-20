"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { apiFetch, loadSession } from "@/lib/api";
import type { Session } from "@/types/api";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/map", label: "Map" },
  { href: "/commander", label: "Command Assistant" }
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    loadSession()
      .then((nextSession) => {
        setSession(nextSession);
        if (!nextSession.authenticated) {
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        }
      })
      .catch(() => router.replace(`/login?next=${encodeURIComponent(pathname)}`));
  }, [pathname, router]);

  async function handleLogout() {
    await apiFetch("/api/logout", { method: "POST", body: "{}" }).catch(() => null);
    router.replace("/login");
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="civic-header">
        <div className="police-lockup">
          <img src="/assets/bengaluru-city-police-header.png" alt="Bengaluru City Police" />
        </div>
        <div className="product-lockup" aria-label="NammaPark Intel">
          <img src="/assets/nammapark-wordmark.png" alt="NammaPark Intel" />
        </div>
        <div className="operator-area">
          <span>Operator</span>
          <strong>{session?.user || "operator"}</strong>
          <button type="button" className="logout-button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>
      <nav className="section-nav" aria-label="Primary navigation">
        <div className="section-nav-inner">
          {navItems.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={active ? "active" : ""}>
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>
      <main id="main" className="app-main">
        {children}
      </main>
    </div>
  );
}
