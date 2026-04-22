"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api, {
  type ApiEnvelope,
  type CharacterSummary,
  type RouteSummary,
  type UserStats,
} from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { formatMinutes } from "@/lib/utils";
import {
  AlertTriangle,
  ChevronRight,
  Play,
  Plus,
  X,
  Flame,
  TrendingUp,
  Map as MapIcon,
  Star,
} from "lucide-react";

export default function DashboardPage() {
  useAuth();
  const [bannerDismissed, setBannerDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    const key = `seasonal_banner_dismissed_${new Date().toISOString().slice(0, 10)}`;
    return !!localStorage.getItem(key);
  });

  const dismissBanner = () => {
    const key = `seasonal_banner_dismissed_${new Date().toISOString().slice(0, 10)}`;
    localStorage.setItem(key, "1");
    setBannerDismissed(true);
  };

  const { data: stats } = useQuery<UserStats>({
    queryKey: ["user", "stats"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<UserStats>>("/users/me/stats");
      return res.data.data;
    },
  });

  const { data: characters } = useQuery<CharacterSummary[]>({
    queryKey: ["characters"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<CharacterSummary[]>>("/characters");
      return res.data.data;
    },
  });

  const { data: routes } = useQuery<RouteSummary[]>({
    queryKey: ["routes", "active"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<RouteSummary[]>>("/routes?status=active");
      return res.data.data;
    },
  });

  const { data: seasonal } = useQuery({
    queryKey: ["seasonal", "active"],
    queryFn: async () => {
      const res = await api.get<
        ApiEnvelope<{
          active?: { event_name: string; days_remaining: number; achievement_count: number }[];
        }>
      >("/achievements/seasonal?status=active");
      return res.data.data.active || [];
    },
  });

  const activeRoute = routes?.[0];
  const primaryChar = characters?.[0];
  const completionPct = stats?.overall_completion_pct ?? 0;
  const pointsThisMonth = stats?.achievements_completed_this_month ?? 0;

  return (
    <div className="fade-in">
      {!bannerDismissed && seasonal && seasonal.length > 0 && (
        <div
          className="flex items-center gap-3 mb-6 p-4 rounded-lg"
          style={{
            background:
              "linear-gradient(90deg, rgba(224, 138, 60, 0.12), rgba(233, 190, 106, 0.06))",
            border: "1px solid rgba(224, 138, 60, 0.3)",
          }}
        >
          <AlertTriangle className="text-ember shrink-0" size={20} />
          <div className="flex-1">
            <p className="text-sm font-semibold m-0">
              {seasonal[0].achievement_count} seasonal achievements available —{" "}
              {seasonal[0].days_remaining} days remaining on {seasonal[0].event_name}
            </p>
            {seasonal.length > 1 && (
              <Link href="/calendar" className="text-xs text-gold-1 hover:underline">
                and {seasonal.length - 1} more events
              </Link>
            )}
          </div>
          <button
            onClick={dismissBanner}
            className="text-fg-3 hover:text-fg-1"
            aria-label="Dismiss"
          >
            <X size={18} />
          </button>
        </div>
      )}

      {/* Page header */}
      <div className="flex items-end justify-between gap-6 mb-7 flex-wrap">
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-1.5 flex items-center gap-2">
            <span
              className="inline-block w-[5px] h-[5px]"
              style={{
                transform: "rotate(45deg)",
                background: "var(--gold-2)",
                boxShadow: "0 0 8px var(--gold-glow)",
              }}
            />
            Welcome back{primaryChar ? `, ${primaryChar.name}` : ""}
          </div>
          <h1 className="font-display text-[28px] font-semibold tracking-tight m-0 mb-1.5">
            The road ahead
          </h1>
          <p className="text-[13px] text-fg-3 m-0 max-w-[60ch]">
            {activeRoute
              ? `You're ${routeProgressPct(activeRoute)}% through your current route. Pick up where you left off or plan a new journey.`
              : "You don't have an active route yet. Let the engine plan one for you."}
          </p>
        </div>
        {activeRoute ? (
          <Link
            href={`/routes/${activeRoute.id}`}
            className="btn btn-primary"
            style={{ padding: "10px 18px", fontSize: 13 }}
          >
            <Play size={14} /> Resume
          </Link>
        ) : (
          <Link
            href="/routes"
            className="btn btn-primary"
            style={{ padding: "10px 18px", fontSize: 13 }}
          >
            <Plus size={14} /> Generate a route
          </Link>
        )}
      </div>

      {/* Grid */}
      <div className="grid gap-5 lg:grid-cols-[1fr_340px] items-start">
        <div className="grid gap-5">
          <HeroCard route={activeRoute} stats={stats} />

          <div className="grid gap-3.5 sm:grid-cols-3">
            <StatCard
              label="Completion"
              value={`${completionPct}%`}
              trend={
                stats
                  ? `${stats.total_achievements_completed.toLocaleString()} / ${stats.total_achievements_eligible.toLocaleString()}`
                  : "—"
              }
              Icon={TrendingUp}
            />
            <StatCard
              label="Points earned"
              value={stats ? stats.total_achievement_points.toLocaleString() : "—"}
              trend={
                pointsThisMonth > 0 ? `+${pointsThisMonth} this month` : "No completions yet"
              }
              Icon={Star}
              highlight
            />
            <StatCard
              label="Estimated remaining"
              value={stats ? `${stats.estimated_hours_remaining}h` : "—"}
              trend={
                stats?.favorite_category ? `Favorite · ${stats.favorite_category}` : "at your current pace"
              }
              Icon={MapIcon}
            />
          </div>
        </div>

        <div className="grid gap-5 lg:sticky lg:top-5">
          <Card title="Active Seasonal Events">
            {seasonal && seasonal.length > 0 ? (
              seasonal.slice(0, 4).map((s) => (
                <div
                  key={s.event_name}
                  className="flex items-center gap-3 px-3.5 py-3 border-b last:border-0"
                  style={{
                    borderColor: "var(--border-1)",
                    background:
                      "linear-gradient(90deg, rgba(224, 138, 60, 0.08), transparent 40%)",
                    borderLeft: "2px solid var(--ember)",
                    paddingLeft: 12,
                  }}
                >
                  <div
                    className="w-8 h-8 rounded grid place-items-center shrink-0"
                    style={{
                      background: "linear-gradient(135deg, var(--ember-dim), #4a2a10)",
                      color: "#FFE5BC",
                    }}
                  >
                    <Flame size={14} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium truncate">{s.event_name}</div>
                    <div className="font-mono text-[11px] text-fg-3 mt-0.5">
                      Ends in {s.days_remaining}d · {s.achievement_count} achievements
                    </div>
                  </div>
                  <div className="font-mono text-[12px] text-gold-1 font-semibold">
                    +{s.achievement_count * 10}
                  </div>
                </div>
              ))
            ) : (
              <EmptyRow>No active events right now.</EmptyRow>
            )}
          </Card>

          <Card title="Characters">
            {characters && characters.length > 0 ? (
              characters.slice(0, 4).map((c, i) => (
                <CharacterRow key={c.id} char={c} primary={i === 0} />
              ))
            ) : (
              <EmptyRow>
                <Link href="/onboarding" className="text-gold-1 hover:underline">
                  Connect a character
                </Link>{" "}
                to get started.
              </EmptyRow>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function HeroCard({ route, stats }: { route?: RouteSummary; stats?: UserStats }) {
  if (!route) {
    return (
      <div
        className="relative overflow-hidden p-6"
        style={{
          background:
            "radial-gradient(600px 200px at 90% 0%, var(--gold-glow), transparent 70%), linear-gradient(180deg, var(--bg-2), var(--bg-1))",
          border: "1px solid var(--border-2)",
          borderRadius: "var(--r-xl)",
        }}
      >
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-2">
          No active route
        </div>
        <h2 className="font-display text-[22px] font-semibold m-0 mb-2">The engine is ready.</h2>
        <p className="text-fg-3 text-sm m-0 mb-5 max-w-[46ch]">
          Tell us what &quot;done&quot; means — completionist, points-per-hour, a specific meta — and
          we&apos;ll plan the whole road for you.
        </p>
        <Link href="/routes" className="btn btn-primary" style={{ padding: "10px 18px", fontSize: 13 }}>
          <Plus size={14} /> Generate a route
        </Link>
      </div>
    );
  }

  const pct = routeProgressPct(route);
  const minutes = route.total_estimated_minutes ?? 0;
  const remainingHours = Math.round((minutes * (1 - pct / 100)) / 60);

  return (
    <div
      className="relative overflow-hidden p-6"
      style={{
        background:
          "radial-gradient(600px 200px at 90% 0%, var(--gold-glow), transparent 70%), linear-gradient(180deg, var(--bg-2), var(--bg-1))",
        border: "1px solid var(--border-2)",
        borderRadius: "var(--r-xl)",
      }}
    >
      <div className="flex items-start justify-between gap-4 mb-3.5">
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 flex items-center gap-2 mb-1">
            <span
              className="inline-block w-[5px] h-[5px]"
              style={{ transform: "rotate(45deg)", background: "var(--gold-2)" }}
            />
            Active Route
          </div>
          <h2 className="font-display text-[26px] font-semibold m-0 capitalize">
            {route.mode ?? "Custom"} Mode
          </h2>
          <div className="text-[12px] text-fg-3 italic mt-1">
            {formatMinutes(minutes)} estimated ·{" "}
            <span className="not-italic text-gold-1">
              {Math.round((route.overall_confidence ?? 0) * 100)}% confidence
            </span>
          </div>
        </div>
        <Link
          href={`/routes/${route.id}`}
          className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-mono uppercase tracking-[0.1em] shrink-0"
          style={{
            background: "var(--gold-4)",
            color: "var(--gold-1)",
            border: "1px solid var(--gold-3)",
          }}
        >
          Open <ChevronRight size={12} />
        </Link>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-[12px]">
          <span className="font-mono text-[11px] text-fg-3">Route progress</span>
          <span className="font-mono text-fg-1">
            {pct}% <span className="text-fg-3">· complete</span>
          </span>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-3)" }}>
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{
              width: `${pct}%`,
              background: "linear-gradient(90deg, var(--gold-3), var(--gold-1))",
              boxShadow: "0 0 16px var(--gold-glow)",
            }}
          />
        </div>
      </div>

      <div
        className="grid grid-cols-2 gap-4 mt-5 py-4"
        style={{
          borderTop: "1px solid var(--border-1)",
          borderBottom: "1px solid var(--border-1)",
        }}
      >
        <Metric
          label="Points earned"
          value={stats?.total_achievement_points.toLocaleString() ?? "—"}
          sub={
            stats ? `of ${(stats.total_achievements_eligible * 10).toLocaleString()} possible` : undefined
          }
          gold
        />
        <Metric label="Est. time left" value={`${remainingHours}h`} sub="at your current pace" />
      </div>

      <div className="flex gap-2 mt-5 pt-1">
        <Link
          href={`/routes/${route.id}`}
          className="btn btn-primary"
          style={{ padding: "10px 16px", fontSize: 13 }}
        >
          <Play size={13} /> Continue route
        </Link>
        <Link href="/routes" className="btn" style={{ padding: "10px 14px", fontSize: 13 }}>
          Plan another
        </Link>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  gold,
}: {
  label: string;
  value: string;
  sub?: string;
  gold?: boolean;
}) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-3 mb-1">{label}</div>
      <div
        className="font-display text-[22px] font-semibold leading-tight"
        style={{ color: gold ? "var(--gold-1)" : "var(--fg-1)" }}
      >
        {value}
      </div>
      {sub && <div className="font-mono text-[10px] text-fg-3 mt-0.5">{sub}</div>}
    </div>
  );
}

function StatCard({
  label,
  value,
  trend,
  Icon,
  highlight,
}: {
  label: string;
  value: string;
  trend: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  highlight?: boolean;
}) {
  return (
    <div
      className="p-4"
      style={{
        background: "var(--bg-1)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--r-lg)",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="font-mono text-[10px] text-fg-3 uppercase tracking-[0.14em]">{label}</div>
        <Icon size={14} className={highlight ? "text-gold-1" : "text-fg-3"} />
      </div>
      <div
        className="font-display text-[24px] font-semibold"
        style={{ color: highlight ? "var(--gold-1)" : "var(--fg-1)" }}
      >
        {value}
      </div>
      <div className="font-mono text-[11px] text-fg-3 mt-2">{trend}</div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        background: "var(--bg-1)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--r-lg)",
      }}
    >
      <div
        className="px-[18px] py-3.5 flex items-center justify-between"
        style={{ borderBottom: "1px solid var(--border-1)" }}
      >
        <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-fg-3 m-0">
          {title}
        </h3>
      </div>
      <div>{children}</div>
    </div>
  );
}

function EmptyRow({ children }: { children: React.ReactNode }) {
  return <div className="px-[18px] py-5 text-[13px] text-fg-3">{children}</div>;
}

function CharacterRow({ char, primary }: { char: CharacterSummary; primary: boolean }) {
  const isHorde = char.faction?.toLowerCase() === "horde";
  return (
    <div
      className="flex items-center gap-3 px-3.5 py-3 border-b last:border-0"
      style={{
        borderColor: "var(--border-1)",
        background: primary
          ? "linear-gradient(90deg, var(--gold-glow), transparent 40%)"
          : undefined,
        borderLeft: primary ? "2px solid var(--gold-2)" : undefined,
        paddingLeft: primary ? 12 : undefined,
      }}
    >
      <div
        className="w-9 h-9 rounded grid place-items-center font-display font-semibold text-base shrink-0"
        style={{
          background: isHorde
            ? "linear-gradient(135deg, var(--horde-dim), #3d1919)"
            : "linear-gradient(135deg, var(--alliance-dim), #152447)",
          color: isHorde ? "#F5B4B4" : "#B4CCF5",
          border: `1px solid ${isHorde ? "var(--horde)" : "var(--alliance)"}`,
        }}
      >
        {char.name.slice(0, 1).toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-medium truncate">{char.name}</div>
        <div className="font-mono text-[11px] text-fg-3 truncate">
          {char.realm}
          {char.class ? ` · ${char.class}` : ""}
          {char.level ? ` · lvl ${char.level}` : ""}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="font-mono text-[12px] text-gold-1 font-semibold">
          {char.achievement_completion_pct}%
        </div>
        <div className="font-mono text-[9px] text-fg-4 uppercase tracking-[0.1em] mt-0.5">done</div>
      </div>
    </div>
  );
}

function routeProgressPct(_route: RouteSummary): number {
  return 0;
}
