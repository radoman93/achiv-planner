"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseISO } from "date-fns";
import api, { type ApiEnvelope, type SeasonalEvent } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Flame, Calendar as CalendarIcon, Clock } from "lucide-react";

export default function CalendarPage() {
  useAuth();
  const [selected, setSelected] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["seasonal", "all"],
    queryFn: async () => {
      const res = await api.get<
        ApiEnvelope<{ active?: SeasonalEvent[]; upcoming?: SeasonalEvent[] }>
      >("/achievements/seasonal?status=all&days_ahead=120");
      return res.data.data;
    },
  });

  const active = data?.active ?? [];
  const upcoming = data?.upcoming ?? [];

  const selectedEvent = useMemo(
    () =>
      [...active, ...upcoming].find((e) => e.event_name === selected),
    [active, upcoming, selected],
  );

  return (
    <div className="fade-in">
      {/* Page header */}
      <div className="mb-7">
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-1.5 flex items-center gap-2">
          <span
            className="inline-block w-[5px] h-[5px]"
            style={{ transform: "rotate(45deg)", background: "var(--gold-2)" }}
          />
          Seasonal
        </div>
        <h1 className="font-display text-[28px] font-semibold tracking-tight m-0 mb-1.5">
          What&apos;s in season
        </h1>
        <p className="text-[13px] text-fg-3 m-0 max-w-[68ch]">
          Time-gated achievements live and upcoming. Active windows are prioritized in your route.
        </p>
      </div>

      {/* Active events grid */}
      {active.length > 0 && (
        <section className="mb-10">
          <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-fg-3 mb-4 flex items-center gap-2">
            <Flame size={12} className="text-ember" />
            Active now
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {active.map((ev) => (
              <EventCard
                key={ev.event_name}
                ev={ev}
                active
                selected={selected === ev.event_name}
                onClick={() => setSelected(ev.event_name)}
              />
            ))}
          </div>
        </section>
      )}

      {/* Upcoming grid */}
      {upcoming.length > 0 && (
        <section className="mb-10">
          <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-fg-3 mb-4 flex items-center gap-2">
            <CalendarIcon size={12} className="text-fg-3" />
            Upcoming
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {upcoming.map((ev) => (
              <EventCard
                key={ev.event_name}
                ev={ev}
                selected={selected === ev.event_name}
                onClick={() => setSelected(ev.event_name)}
              />
            ))}
          </div>
        </section>
      )}

      {active.length === 0 && upcoming.length === 0 && (
        <div
          className="p-10 text-center text-fg-3"
          style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--r-lg)",
          }}
        >
          No seasonal events loaded.
        </div>
      )}

      {/* Detail drawer */}
      {selectedEvent && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center"
          style={{ background: "rgba(0,0,0,0.6)" }}
          onClick={() => setSelected(null)}
        >
          <div
            className="w-full max-w-lg p-6 max-h-[80vh] overflow-y-auto"
            style={{
              background: "var(--bg-1)",
              border: "1px solid var(--border-2)",
              borderRadius: "var(--r-xl)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-2">
              Seasonal event
            </div>
            <h2 className="font-display text-[24px] font-semibold m-0 mb-2">
              {selectedEvent.event_name}
            </h2>
            <div className="font-mono text-[12px] text-fg-3 mb-4">
              {selectedEvent.opens_at} — {selectedEvent.closes_at}
            </div>
            <p className="text-sm text-fg-2 mb-4 m-0">
              {selectedEvent.achievement_count} achievements available.
              {selectedEvent.days_remaining !== undefined &&
                ` ${selectedEvent.days_remaining} days remaining.`}
              {selectedEvent.days_until_open !== undefined &&
                ` Opens in ${selectedEvent.days_until_open} days.`}
            </p>
            {selectedEvent.achievements && selectedEvent.achievements.length > 0 && (
              <div className="grid gap-2">
                {selectedEvent.achievements.map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center gap-3 p-2.5"
                    style={{
                      background: "var(--bg-2)",
                      border: "1px solid var(--border-1)",
                      borderRadius: "var(--r-md)",
                    }}
                  >
                    <span className="font-mono text-[12px] text-gold-1 font-semibold">
                      +{a.points}
                    </span>
                    <span className="text-sm truncate">{a.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function EventCard({
  ev,
  active,
  selected,
  onClick,
}: {
  ev: SeasonalEvent;
  active?: boolean;
  selected?: boolean;
  onClick: () => void;
}) {
  const daysRemaining = ev.days_remaining ?? 0;
  const daysUntil = ev.days_until_open ?? 0;
  const urgent = active && daysRemaining <= 7;

  const opensAt = parseISO(ev.opens_at);
  const closesAt = parseISO(ev.closes_at);

  return (
    <button
      onClick={onClick}
      className={cn(
        "text-left p-5 transition-all",
        selected && "ring-2 ring-offset-2 ring-offset-bg-0",
      )}
      style={{
        background: active
          ? "linear-gradient(160deg, rgba(224, 138, 60, 0.08), var(--bg-1))"
          : "var(--bg-1)",
        border: active
          ? "1px solid rgba(224, 138, 60, 0.4)"
          : "1px solid var(--border-1)",
        borderRadius: "var(--r-lg)",
        boxShadow: active ? "0 0 40px rgba(224, 138, 60, 0.12)" : "none",
      }}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-10 h-10 rounded grid place-items-center"
          style={{
            background: active
              ? "linear-gradient(135deg, var(--ember-dim), #4a2a10)"
              : "var(--bg-3)",
            color: active ? "#FFE5BC" : "var(--fg-3)",
            border: active ? "1px solid var(--ember-dim)" : "1px solid var(--border-2)",
          }}
        >
          <Flame size={16} />
        </div>
        {urgent && (
          <span
            className="px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] rounded"
            style={{
              background: "rgba(200, 100, 100, 0.15)",
              color: "var(--bad)",
              border: "1px solid rgba(200, 100, 100, 0.3)",
            }}
          >
            Ends soon
          </span>
        )}
      </div>
      <h3 className="font-display text-[18px] font-semibold m-0 mb-1.5">{ev.event_name}</h3>
      <div className="font-mono text-[11px] text-fg-3 flex items-center gap-1.5 mb-3">
        <Clock size={10} />
        {active
          ? `Ends in ${daysRemaining}d`
          : `Opens in ${daysUntil}d`}
      </div>
      <div className="flex items-center justify-between pt-3 border-t border-border-1">
        <span className="font-mono text-[11px] text-fg-3 uppercase tracking-[0.1em]">
          {opensAt.toLocaleDateString()} → {closesAt.toLocaleDateString()}
        </span>
        <span className="font-display text-[16px] text-gold-1 font-semibold">
          +{ev.achievement_count * 10}
          <span className="font-mono text-[10px] text-fg-3 font-normal ml-0.5">pts</span>
        </span>
      </div>
    </button>
  );
}
