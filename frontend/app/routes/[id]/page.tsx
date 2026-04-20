"use client";

import { useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, { type ApiEnvelope, type RouteData, type RouteStopData } from "@/lib/api-client";
import { cn, formatMinutes, TIER_COLORS, TIER_TEXT_COLORS } from "@/lib/utils";
import { Check, ChevronDown, ChevronRight, ExternalLink, Lightbulb, Loader2, RefreshCw, SkipForward, Swords, MessageSquare, MapPin } from "lucide-react";

const STEP_ICONS: Record<string, typeof Swords> = {
  travel: MapPin,
  kill: Swords,
  talk: MessageSquare,
  action: Check,
};

function StopCard({ stop, routeId, onUpdate }: { stop: RouteStopData; routeId: string; onUpdate: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [tipsOpen, setTipsOpen] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [optimistic, setOptimistic] = useState<"completed" | "skipped" | null>(null);

  const isCompleted = optimistic === "completed" || stop.completed;
  const isSkipped = optimistic === "skipped" || stop.skipped;

  const handleComplete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setOptimistic("completed");
    setCompleting(true);
    try {
      await api.post(`/routes/${routeId}/complete/${stop.achievement?.id}`);
      onUpdate();
    } catch { setOptimistic(null); }
    setCompleting(false);
  };

  const handleSkip = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setOptimistic("skipped");
    setSkipping(true);
    try {
      await api.post(`/routes/${routeId}/skip/${stop.achievement?.id}`);
      onUpdate();
    } catch { setOptimistic(null); }
    setSkipping(false);
  };

  if (!stop.achievement) return null;
  const ach = stop.achievement;
  const tier = stop.confidence_tier || "research_required";

  return (
    <div
      className={cn(
        "bg-surface-elevated rounded-lg border border-border p-4 transition-opacity",
        isCompleted && "opacity-40",
        isSkipped && "opacity-30 line-through",
      )}
    >
      {/* Collapsed */}
      <div className="flex items-center gap-3 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="w-8 h-8 rounded bg-surface flex items-center justify-center shrink-0 text-xs font-mono text-primary">
          {ach.points}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm text-primary truncate">{ach.name}</p>
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            {stop.zone && <span>{stop.zone.name}</span>}
            <span>{formatMinutes(stop.estimated_minutes)}</span>
            <span className={cn("w-2 h-2 rounded-full", TIER_COLORS[tier])} title={tier} />
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!isCompleted && !isSkipped && (
            <>
              <button onClick={handleComplete} disabled={completing} className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded bg-success/10 text-success hover:bg-success/20" title="Complete">
                <Check size={16} />
              </button>
              <button onClick={handleSkip} disabled={skipping} className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded bg-border text-text-secondary hover:bg-surface" title="Skip">
                <SkipForward size={16} />
              </button>
            </>
          )}
          {expanded ? <ChevronDown size={16} className="text-text-secondary" /> : <ChevronRight size={16} className="text-text-secondary" />}
        </div>
      </div>

      {/* Expanded */}
      {expanded && (
        <div className="mt-4 space-y-3 border-t border-border pt-3">
          {/* Steps */}
          {stop.steps && stop.steps.length > 0 && (
            <ol className="space-y-2">
              {stop.steps.map((s, i) => {
                const Icon = STEP_ICONS[s.step_type || "action"] || Check;
                return (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <Icon size={14} className="mt-0.5 text-text-secondary shrink-0" />
                    <div>
                      <span>{s.description || s.label}</span>
                      {s.location && <span className="text-text-secondary text-xs ml-1">({s.location})</span>}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}

          {/* Community Tips */}
          {stop.community_tips && stop.community_tips.length > 0 && (
            <div>
              <button onClick={() => setTipsOpen(!tipsOpen)} className="flex items-center gap-1 text-xs text-primary hover:underline">
                <Lightbulb size={12} /> {stop.community_tips.length} community tips
              </button>
              {tipsOpen && (
                <div className="mt-2 space-y-2">
                  {stop.community_tips.map((tip, i) => (
                    <div key={i} className="bg-surface rounded p-2 text-xs text-text-secondary">
                      {typeof tip === "string" ? tip : tip.text}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Confidence + Wowhead link */}
          <div className="flex items-center justify-between text-xs">
            <span className={cn("capitalize", TIER_TEXT_COLORS[tier])}>
              {tier.replace("_", " ")} confidence
            </span>
            {stop.wowhead_url && (
              <a href={stop.wowhead_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-primary hover:underline">
                View on Wowhead <ExternalLink size={10} />
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function RouteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();

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

  const [reoptimizing, setReoptimizing] = useState(false);
  const [blockedOpen, setBlockedOpen] = useState(false);

  const handleReoptimize = async () => {
    setReoptimizing(true);
    try {
      const res = await api.post<ApiEnvelope<RouteData>>(`/routes/${id}/reoptimize`);
      router.push(`/routes/${res.data.data.id}`);
    } catch { /* rate limit handled by interceptor */ }
    setReoptimizing(false);
  };

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="animate-spin text-primary" size={24} /></div>;
  }
  if (!route) {
    return <p className="text-text-secondary">Route not found.</p>;
  }

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold capitalize">{route.mode} Route</h1>
          <p className="text-sm text-text-secondary">
            {formatMinutes(route.total_estimated_minutes)} &middot; Confidence {route.overall_confidence ? `${(route.overall_confidence * 100).toFixed(0)}%` : "—"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleReoptimize}
            disabled={reoptimizing}
            className="inline-flex items-center gap-2 bg-surface-elevated border border-border rounded px-4 py-2 text-sm hover:border-primary disabled:opacity-50"
          >
            {reoptimizing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Regenerate
          </button>
        </div>
      </div>

      {/* Seasonal block */}
      {route.seasonal_block.stops.length > 0 && (
        <div className="bg-warning/5 border border-warning/20 rounded-lg p-4 mb-6">
          <h2 className="font-semibold text-warning mb-3 flex items-center gap-2">
            <span>&#9200;</span> Do These First
          </h2>
          <div className="space-y-3">
            {route.seasonal_block.stops.map((stop) => (
              <div key={stop.id} className="flex items-center gap-2">
                <span className={cn(
                  "text-xs font-bold px-2 py-0.5 rounded",
                  stop.days_remaining && stop.days_remaining <= 3 ? "bg-error text-white" :
                  stop.days_remaining && stop.days_remaining <= 7 ? "bg-warning text-background" :
                  "bg-border text-text-secondary"
                )}>
                  {stop.days_remaining}d
                </span>
                <StopCard stop={stop} routeId={id} onUpdate={refresh} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sessions */}
      {route.sessions.map((session) => (
        <SessionSection key={session.session_number} session={session} routeId={id} onUpdate={refresh} />
      ))}

      {/* Blocked Pool */}
      {route.blocked_pool.length > 0 && (
        <div className="mt-6">
          <button onClick={() => setBlockedOpen(!blockedOpen)} className="flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary">
            {blockedOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            {route.blocked_pool.length} achievements blocked
          </button>
          {blockedOpen && (
            <div className="mt-3 space-y-2">
              {route.blocked_pool.map((b, i) => (
                <div key={i} className="bg-surface rounded-lg border border-border p-3 text-sm">
                  <p className="font-semibold">{b.achievement_name || "Unknown"}</p>
                  <span className="text-xs bg-error/10 text-error rounded px-2 py-0.5">{b.reason.replace("_", " ")}</span>
                  {b.unlocker && <p className="text-xs text-text-secondary mt-1">{b.unlocker}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SessionSection({ session, routeId, onUpdate }: { session: { session_number: number; estimated_minutes: number; primary_zone: string; stops: RouteStopData[] }; routeId: string; onUpdate: () => void }) {
  const [open, setOpen] = useState(true);
  const completed = session.stops.filter((s) => s.completed).length;
  const total = session.stops.length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="mb-6">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between bg-surface rounded-lg border border-border p-4 sticky top-0 z-10"
      >
        <div className="flex items-center gap-3">
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span className="font-semibold">Session {session.session_number}</span>
          <span className="text-sm text-text-secondary">{session.primary_zone}</span>
          <span className="text-sm text-text-secondary">~{formatMinutes(session.estimated_minutes)}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-24 h-1.5 rounded bg-border overflow-hidden">
            <div className="h-full bg-success rounded" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-xs text-text-secondary">{completed}/{total}</span>
        </div>
      </button>
      {open && (
        <div className="space-y-2 mt-2">
          {session.stops.map((stop) => (
            <StopCard key={stop.id} stop={stop} routeId={routeId} onUpdate={onUpdate} />
          ))}
        </div>
      )}
    </div>
  );
}
