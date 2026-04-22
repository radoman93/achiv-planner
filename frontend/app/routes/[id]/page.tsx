"use client";

import { useState, useCallback, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, {
  type ApiEnvelope,
  type RouteData,
  type RouteStopData,
} from "@/lib/api-client";
import { cn, formatMinutes } from "@/lib/utils";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Loader2,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Play,
} from "lucide-react";

const CONFIDENCE_META: Record<string, { color: string; label: string }> = {
  verified: { color: "var(--conf-verified, #8FBF7A)", label: "Verified" },
  high: { color: "var(--conf-trusted, #D4A04A)", label: "Trusted" },
  medium: { color: "var(--conf-community, #C88A5A)", label: "Community" },
  low: { color: "var(--conf-unverified, #8A6B6B)", label: "Unverified" },
  research_required: { color: "#C86464", label: "Research" },
};

type SortMode = "completionist" | "pph" | "goal" | "seasonal";

const SORT_MODES: { id: SortMode; label: string }[] = [
  { id: "completionist", label: "Completionist" },
  { id: "pph", label: "Pts / Hr" },
  { id: "goal", label: "Goal" },
  { id: "seasonal", label: "Seasonal" },
];

export default function RouteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const [sortMode, setSortMode] = useState<SortMode>("completionist");
  const [query, setQuery] = useState("");
  const [blockedOpen, setBlockedOpen] = useState(false);
  const [reoptimizing, setReoptimizing] = useState(false);

  const { data: route, isLoading } = useQuery<RouteData>({
    queryKey: ["route", id],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<RouteData>>(`/routes/${id}`);
      return res.data.data;
    },
  });

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["route", id] });
  }, [qc, id]);

  const handleReoptimize = async () => {
    setReoptimizing(true);
    try {
      const res = await api.post<ApiEnvelope<RouteData>>(`/routes/${id}/reoptimize`);
      router.push(`/routes/${res.data.data.id}`);
    } catch {
      /* interceptor handles */
    }
    setReoptimizing(false);
  };

  const allStops: RouteStopData[] = useMemo(() => {
    if (!route) return [];
    const seasonal = route.seasonal_block?.stops ?? [];
    const fromSessions = route.sessions.flatMap((s) => s.stops);
    return [...seasonal, ...fromSessions];
  }, [route]);

  const sortedStops = useMemo(() => {
    const copy = [...allStops];
    if (sortMode === "pph") {
      copy.sort((a, b) => {
        const aPph =
          (a.achievement?.points ?? 0) / Math.max(a.estimated_minutes ?? 1, 1);
        const bPph =
          (b.achievement?.points ?? 0) / Math.max(b.estimated_minutes ?? 1, 1);
        return bPph - aPph;
      });
    } else if (sortMode === "seasonal") {
      copy.sort((a, b) => Number(b.is_seasonal) - Number(a.is_seasonal));
    } else if (sortMode === "goal") {
      copy.sort((a, b) => (b.achievement?.points ?? 0) - (a.achievement?.points ?? 0));
    }
    return copy;
  }, [allStops, sortMode]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sortedStops;
    return sortedStops.filter((s) =>
      s.achievement?.name.toLowerCase().includes(q),
    );
  }, [sortedStops, query]);

  const grouped = useMemo(() => {
    const groups: {
      zoneId: string;
      zoneName: string;
      expansion: string | null;
      stops: RouteStopData[];
    }[] = [];
    for (const s of filtered) {
      const zoneName = s.zone?.name ?? "Unzoned";
      const expansion = s.zone?.expansion ?? null;
      const last = groups[groups.length - 1];
      if (last && last.zoneName === zoneName) {
        last.stops.push(s);
      } else {
        groups.push({ zoneId: zoneName, zoneName, expansion, stops: [s] });
      }
    }
    return groups;
  }, [filtered]);

  const totals = useMemo(() => {
    const pts = filtered.reduce((sum, s) => sum + (s.achievement?.points ?? 0), 0);
    const mins = filtered.reduce((sum, s) => sum + (s.estimated_minutes ?? 0), 0);
    const done = filtered.filter((s) => s.completed).length;
    return { pts, mins, done };
  }, [filtered]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="animate-spin text-gold-1" size={24} />
      </div>
    );
  }

  if (!route) {
    return <p className="text-fg-3">Route not found.</p>;
  }

  return (
    <div className="fade-in">
      {/* Page header */}
      <div className="flex items-end justify-between gap-6 mb-7 flex-wrap">
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-1.5 flex items-center gap-2">
            <span
              className="inline-block w-[5px] h-[5px]"
              style={{ transform: "rotate(45deg)", background: "var(--gold-2)" }}
            />
            Active Route
            {route.created_at && (
              <>
                {" · "}
                <span className="tracking-normal normal-case text-fg-3">
                  Generated {new Date(route.created_at).toLocaleDateString()}
                </span>
              </>
            )}
          </div>
          <h1 className="font-display text-[28px] font-semibold tracking-tight m-0 mb-1.5 capitalize">
            {route.mode ?? "Custom"} Route
          </h1>
          <p className="text-[13px] text-fg-3 m-0 max-w-[68ch]">
            {filtered.length} stops across {grouped.length} zones — ordered by constraint
            filter → dependency resolver → geographic clusterer. Switching priority mode re-runs
            the assembler.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleReoptimize}
            disabled={reoptimizing}
            className="btn"
            style={{ padding: "10px 14px", fontSize: 13 }}
          >
            {reoptimizing ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            Regenerate
          </button>
          <button className="btn btn-primary" style={{ padding: "10px 16px", fontSize: 13 }}>
            <Play size={14} /> Play mode
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        <span className="f-label">Sort by</span>
        <div className="mode-pill-row">
          {SORT_MODES.map((m) => (
            <button
              key={m.id}
              className={cn("mode-pill", sortMode === m.id && "on")}
              onClick={() => setSortMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="flex-1" />

        <div className="relative">
          <Search
            size={12}
            className="absolute top-1/2 -translate-y-1/2"
            style={{ left: 9, color: "var(--fg-3)" }}
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter stops"
            className="font-mono"
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border-2)",
              borderRadius: "var(--r-md)",
              padding: "5px 10px 5px 26px",
              fontSize: 12,
              color: "var(--fg-1)",
              outline: "none",
              width: 180,
            }}
          />
        </div>

        <button className="btn" style={{ padding: "5px 10px", fontSize: 11 }}>
          <SlidersHorizontal size={12} /> Filters
        </button>
      </div>

      {/* Summary strip */}
      <div className="flex gap-3.5 mb-6 font-mono text-[12px] text-fg-3 flex-wrap">
        <span>
          <span className="text-fg-1 font-semibold">{filtered.length}</span> stops
        </span>
        <span>·</span>
        <span>
          <span className="text-gold-1 font-semibold">{totals.pts}</span> pts
        </span>
        <span>·</span>
        <span>
          <span className="text-fg-1 font-semibold">~{Math.round(totals.mins / 60)}h</span>
        </span>
        <span>·</span>
        <span>
          <span className="text-good font-semibold">{totals.done}</span> done
        </span>
        <span>·</span>
        <span>
          Confidence{" "}
          <span className="text-gold-1 font-semibold">
            {route.overall_confidence ? `${Math.round(route.overall_confidence * 100)}%` : "—"}
          </span>
        </span>
      </div>

      {/* Timeline */}
      <div className="timeline">
        {grouped.length === 0 && (
          <div className="p-10 text-center text-fg-3">
            No stops match your current filters. Try clearing the search.
          </div>
        )}
        {grouped.map((g, gi) => {
          const zPts = g.stops.reduce((sum, s) => sum + (s.achievement?.points ?? 0), 0);
          const zMins = g.stops.reduce((sum, s) => sum + (s.estimated_minutes ?? 0), 0);
          return (
            <div key={g.zoneId + gi} className="zone-block">
              <div className="zone-header">
                <div>
                  <div className="zone-name">{g.zoneName}</div>
                  {g.expansion && <div className="zone-continent">{g.expansion}</div>}
                </div>
                <div className="zone-sum">
                  {g.stops.length} stops · {zPts} pts ·{" "}
                  ~{Math.round((zMins / 60) * 10) / 10}h
                </div>
              </div>
              {g.stops.map((stop) => (
                <StopItem
                  key={stop.id}
                  stop={stop}
                  routeId={id}
                  onUpdate={refresh}
                />
              ))}
            </div>
          );
        })}
      </div>

      {/* Blocked pool */}
      {route.blocked_pool.length > 0 && (
        <div className="mt-10">
          <button
            onClick={() => setBlockedOpen(!blockedOpen)}
            className="flex items-center gap-2 text-sm text-fg-3 hover:text-fg-1 font-mono uppercase tracking-[0.1em]"
          >
            {blockedOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            {route.blocked_pool.length} achievements blocked
          </button>
          {blockedOpen && (
            <div className="mt-3 grid gap-2">
              {route.blocked_pool.map((b, i) => (
                <div
                  key={i}
                  className="p-3 text-sm"
                  style={{
                    background: "var(--bg-1)",
                    border: "1px solid var(--border-1)",
                    borderRadius: "var(--r-md)",
                  }}
                >
                  <p className="font-semibold m-0">{b.achievement_name || "Unknown"}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className="text-xs font-mono uppercase tracking-[0.08em] px-2 py-0.5 rounded"
                      style={{
                        background: "rgba(200, 100, 100, 0.1)",
                        color: "var(--bad)",
                        border: "1px solid rgba(200, 100, 100, 0.3)",
                      }}
                    >
                      {b.reason.replace("_", " ")}
                    </span>
                    {b.unlocker && (
                      <span className="text-xs text-fg-3 font-mono">{b.unlocker}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StopItem({
  stop,
  routeId,
  onUpdate,
}: {
  stop: RouteStopData;
  routeId: string;
  onUpdate: () => void;
}) {
  const [optimistic, setOptimistic] = useState<"completed" | "skipped" | null>(null);
  const [expanded, setExpanded] = useState(false);

  const isCompleted = optimistic === "completed" || stop.completed;
  const isSkipped = optimistic === "skipped" || stop.skipped;
  const ach = stop.achievement;

  const toggleComplete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!ach) return;
    if (isCompleted) {
      setOptimistic(null);
      try {
        await api.post(`/routes/${routeId}/reopen/${ach.id}`);
        onUpdate();
      } catch {
        setOptimistic("completed");
      }
      return;
    }
    setOptimistic("completed");
    try {
      await api.post(`/routes/${routeId}/complete/${ach.id}`);
      onUpdate();
    } catch {
      setOptimistic(null);
    }
  };

  if (!ach) return null;

  const tier = stop.confidence_tier || "research_required";
  const confMeta = CONFIDENCE_META[tier] ?? CONFIDENCE_META.research_required;

  return (
    <div
      className={cn(
        "stop",
        isCompleted && "done",
        isSkipped && "done",
        stop.is_seasonal && "seasonal",
      )}
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="stop-row">
        <div
          className={cn("stop-check", isCompleted && "checked")}
          onClick={toggleComplete}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M5 12l4 4 10-10" />
          </svg>
        </div>
        <div className="stop-body">
          <div className="stop-title">
            <span
              className="conf-dot"
              style={{ background: confMeta.color }}
              title={confMeta.label}
            />
            {ach.name}
            {stop.is_seasonal && (
              <span
                className="chip"
                style={{
                  background: "rgba(224,138,60,0.12)",
                  color: "var(--ember)",
                  borderColor: "rgba(224,138,60,0.3)",
                }}
              >
                Seasonal
                {stop.days_remaining !== null &&
                  stop.days_remaining !== undefined &&
                  ` · ${stop.days_remaining}d`}
              </span>
            )}
          </div>
          <div className="stop-meta">
            {stop.estimated_minutes && (
              <span>~{formatMinutes(stop.estimated_minutes)}</span>
            )}
            {ach.category && <span>{ach.category}</span>}
            <span>{confMeta.label}</span>
          </div>
        </div>
        <div className="stop-pts">
          +{ach.points}
          <span className="unit">pts</span>
        </div>
      </div>

      {expanded && (
        <div
          className="mt-3 pt-3 text-xs text-fg-3"
          style={{ borderTop: "1px solid var(--border-1)" }}
          onClick={(e) => e.stopPropagation()}
        >
          {stop.steps && stop.steps.length > 0 && (
            <ol className="grid gap-2 m-0 pl-4 list-decimal">
              {stop.steps.slice(0, 6).map((s, i) => (
                <li key={i}>{s.description || s.label}</li>
              ))}
            </ol>
          )}
          {stop.wowhead_url && (
            <a
              href={stop.wowhead_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1 text-gold-1 hover:underline"
            >
              View on Wowhead <ExternalLink size={10} />
            </a>
          )}
        </div>
      )}
    </div>
  );
}
