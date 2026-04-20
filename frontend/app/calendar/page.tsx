"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { addMonths, subMonths, startOfMonth, endOfMonth, eachDayOfInterval, format, getDay, isToday, isWithinInterval, parseISO } from "date-fns";
import api, { type ApiEnvelope, type SeasonalEvent } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Hash event name to a color index
function eventColor(name: string): string {
  const colors = [
    "bg-[#e74c3c]", "bg-[#3498db]", "bg-[#2ecc71]", "bg-[#f39c12]",
    "bg-[#9b59b6]", "bg-[#1abc9c]", "bg-[#e67e22]", "bg-[#e91e63]",
  ];
  let hash = 0;
  for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) % colors.length;
  return colors[Math.abs(hash)];
}

export default function CalendarPage() {
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["seasonal", "all"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<{ active?: SeasonalEvent[]; upcoming?: SeasonalEvent[] }>>(
        "/achievements/seasonal?status=all&days_ahead=120",
      );
      return res.data.data;
    },
  });

  const events = useMemo(() => {
    const all: SeasonalEvent[] = [...(data?.active || []), ...(data?.upcoming || [])];
    return all;
  }, [data]);

  const monthStart = startOfMonth(currentMonth);
  const monthEnd = endOfMonth(currentMonth);
  const days = eachDayOfInterval({ start: monthStart, end: monthEnd });
  const startDay = getDay(monthStart);

  // Which events overlap this month
  const monthEvents = events.filter((ev) => {
    const start = parseISO(ev.opens_at);
    const end = parseISO(ev.closes_at);
    return start <= monthEnd && end >= monthStart;
  });

  const selectedEventData = selectedEvent ? events.find((e) => e.event_name === selectedEvent) : null;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Seasonal Calendar</h1>

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Calendar grid */}
        <div className="flex-1">
          <div className="bg-surface rounded-lg border border-border p-4">
            {/* Month navigation */}
            <div className="flex items-center justify-between mb-4">
              <button onClick={() => setCurrentMonth(subMonths(currentMonth, 1))} className="p-2 hover:bg-surface-elevated rounded">
                <ChevronLeft size={18} />
              </button>
              <h2 className="font-semibold">{format(currentMonth, "MMMM yyyy")}</h2>
              <button onClick={() => setCurrentMonth(addMonths(currentMonth, 1))} className="p-2 hover:bg-surface-elevated rounded">
                <ChevronRight size={18} />
              </button>
            </div>

            {/* Day headers */}
            <div className="grid grid-cols-7 gap-1 mb-1">
              {DAY_NAMES.map((d) => (
                <div key={d} className="text-center text-xs text-text-secondary font-medium py-1">{d}</div>
              ))}
            </div>

            {/* Days grid */}
            <div className="grid grid-cols-7 gap-1">
              {/* Empty cells for alignment */}
              {Array.from({ length: startDay }).map((_, i) => (
                <div key={`empty-${i}`} className="h-12" />
              ))}
              {days.map((day) => {
                const dayEvents = monthEvents.filter((ev) =>
                  isWithinInterval(day, { start: parseISO(ev.opens_at), end: parseISO(ev.closes_at) }),
                );
                return (
                  <div
                    key={day.toISOString()}
                    className={cn(
                      "h-12 rounded text-xs flex flex-col items-center justify-start p-1 relative",
                      isToday(day) && "ring-1 ring-primary",
                    )}
                  >
                    <span className={cn("text-[10px]", isToday(day) ? "text-primary font-bold" : "text-text-secondary")}>
                      {format(day, "d")}
                    </span>
                    <div className="flex flex-wrap gap-0.5 mt-0.5">
                      {dayEvents.slice(0, 3).map((ev) => (
                        <button
                          key={ev.event_name}
                          onClick={() => setSelectedEvent(ev.event_name)}
                          className={cn("w-2 h-2 rounded-full", eventColor(ev.event_name))}
                          title={ev.event_name}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Event legend */}
            <div className="flex flex-wrap gap-3 mt-4 pt-3 border-t border-border">
              {monthEvents.map((ev) => (
                <button
                  key={ev.event_name}
                  onClick={() => setSelectedEvent(ev.event_name)}
                  className={cn("flex items-center gap-1.5 text-xs", selectedEvent === ev.event_name && "text-primary font-semibold")}
                >
                  <span className={cn("w-2 h-2 rounded-full", eventColor(ev.event_name))} />
                  {ev.event_name}
                </button>
              ))}
            </div>
          </div>

          {/* Upcoming Events List */}
          {data?.upcoming && data.upcoming.length > 0 && (
            <div className="bg-surface rounded-lg border border-border p-4 mt-6">
              <h3 className="font-semibold mb-3 text-sm">Upcoming Events</h3>
              <div className="space-y-2">
                {data.upcoming.map((ev) => (
                  <button
                    key={ev.event_name}
                    onClick={() => setSelectedEvent(ev.event_name)}
                    className={cn(
                      "w-full flex items-center justify-between text-left p-3 rounded border border-border hover:border-primary transition-colors",
                      ev.days_until_open && ev.days_until_open <= 7 ? "border-warning/30" : false
                    )}
                  >
                    <div>
                      <p className="text-sm font-semibold">{ev.event_name}</p>
                      <p className="text-xs text-text-secondary">{ev.opens_at} &mdash; {ev.closes_at}</p>
                    </div>
                    <div className="text-right">
                      <p className={cn("text-sm font-bold", ev.days_until_open && ev.days_until_open <= 7 ? "text-warning" : "text-text-secondary")}>
                        {ev.days_until_open}d
                      </p>
                      <p className="text-xs text-text-secondary">{ev.achievement_count} achievements</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Event detail sidebar */}
        <div className="w-full lg:w-80 shrink-0">
          <div className="bg-surface rounded-lg border border-border p-4 sticky top-4">
            {selectedEventData ? (
              <>
                <h3 className="font-semibold mb-1">{selectedEventData.event_name}</h3>
                <p className="text-xs text-text-secondary mb-3">
                  {selectedEventData.opens_at} &mdash; {selectedEventData.closes_at}
                </p>
                <p className="text-sm text-text-secondary mb-4">
                  {selectedEventData.achievement_count} achievements
                </p>
                {selectedEventData.achievements && selectedEventData.achievements.length > 0 && (
                  <div className="space-y-2 mb-4">
                    {selectedEventData.achievements.map((a) => (
                      <div key={a.id} className="flex items-center gap-2 text-sm">
                        <span className="text-xs font-mono text-primary">{a.points}</span>
                        <span className="truncate">{a.name}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-text-secondary">Select an event to see details</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
