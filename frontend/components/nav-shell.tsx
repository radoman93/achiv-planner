"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Compass, Flag, Calendar, Trophy, Settings, Plus } from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Home", icon: Compass, section: "workspace" },
  { href: "/routes", label: "My Route", icon: Flag, section: "workspace" },
  { href: "/calendar", label: "Calendar", icon: Calendar, section: "workspace" },
  { href: "/browse", label: "Browse", icon: Trophy, section: "library" },
  { href: "/settings", label: "Characters", icon: Settings, section: "library" },
];

export default function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  const workspace = NAV_ITEMS.filter((i) => i.section === "workspace");
  const library = NAV_ITEMS.filter((i) => i.section === "library");

  return (
    <div className="min-h-screen flex relative z-10">
      {/* Desktop sidebar */}
      <aside
        className="hidden lg:flex flex-col w-60 fixed inset-y-0 left-0 z-40 py-5"
        style={{ background: "var(--bg-1)", borderRight: "1px solid var(--border-1)" }}
      >
        {/* Brand */}
        <Link
          href="/dashboard"
          className="flex items-center gap-2.5 px-5 pb-5 mb-3.5 border-b border-border-1"
        >
          <div
            className="w-8 h-8 rounded-lg grid place-items-center font-display font-bold text-base relative"
            style={{
              background: "radial-gradient(circle at 50% 40%, var(--gold-1), var(--gold-3))",
              color: "#1A1408",
              boxShadow: "0 0 20px var(--gold-glow)",
            }}
          >
            A
          </div>
          <div className="leading-none">
            <div className="font-display text-[15px] font-semibold tracking-wide text-fg-1">Achiv</div>
            <div className="font-mono text-[9px] text-fg-3 uppercase tracking-[0.15em] mt-0.5">
              Route Optimizer
            </div>
          </div>
        </Link>

        {/* Workspace section */}
        <NavSection label="Workspace" />
        <NavGroup items={workspace} pathname={pathname} />

        {/* Library section */}
        <div className="mt-2.5">
          <NavSection label="Library" />
          <NavGroup items={library} pathname={pathname} />
        </div>

        {/* New Route CTA */}
        <div className="mt-auto px-3 pt-3 border-t border-border-1">
          <Link href="/routes" className="btn btn-primary w-full justify-center">
            <Plus size={14} /> New Route
          </Link>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 lg:ml-60 pb-20 lg:pb-0">
        <div className="max-w-[1280px] mx-auto p-4 sm:p-7 lg:p-8">{children}</div>
      </main>

      {/* Mobile bottom tabs */}
      <nav
        className="lg:hidden fixed bottom-0 inset-x-0 z-40 safe-area-bottom"
        style={{ background: "var(--bg-1)", borderTop: "1px solid var(--border-1)" }}
      >
        <div className="flex justify-around items-center h-16">
          {NAV_ITEMS.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex flex-col items-center gap-0.5 min-w-[44px] min-h-[44px] justify-center",
                  active ? "text-gold-1" : "text-fg-3",
                )}
              >
                <item.icon size={20} />
                <span className="text-[10px]">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}

function NavSection({ label }: { label: string }) {
  return (
    <div className="px-3 pt-1 pb-1 font-mono text-[10px] text-fg-4 uppercase tracking-[0.15em]">
      {label}
    </div>
  );
}

function NavGroup({
  items,
  pathname,
}: {
  items: typeof NAV_ITEMS;
  pathname: string;
}) {
  return (
    <nav className="flex flex-col gap-0.5">
      {items.map((item) => {
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "relative flex items-center gap-3 mx-2 px-3.5 py-2 rounded-md text-[13px] font-medium transition-colors",
              active ? "text-fg-1" : "text-fg-2 hover:text-fg-1",
            )}
            style={{
              background: active ? "var(--bg-3)" : "transparent",
            }}
          >
            {active && (
              <span
                aria-hidden
                className="absolute -left-2 top-2 bottom-2 w-0.5 rounded"
                style={{ background: "var(--gold-2)", boxShadow: "0 0 8px var(--gold-glow)" }}
              />
            )}
            <item.icon
              size={16}
              className={active ? "text-gold-2" : "text-fg-3"}
            />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
