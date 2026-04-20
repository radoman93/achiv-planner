"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api, { type ApiEnvelope, type RouteData, type RouteStopData } from "@/lib/api-client";
import { cn, formatMinutes } from "@/lib/utils";
import { List, Loader2 } from "lucide-react";

// Zone approximate positions on stylized SVG map (x, y as percentages)
// Grouped by continent
const ZONE_POSITIONS: Record<string, Record<string, { x: number; y: number }>> = {
  "Eastern Kingdoms": {
    "Stormwind City": { x: 38, y: 72 }, "Ironforge": { x: 48, y: 48 },
    "Elwynn Forest": { x: 36, y: 70 }, "Westfall": { x: 30, y: 74 },
    "Redridge Mountains": { x: 45, y: 73 }, "Duskwood": { x: 38, y: 78 },
    "Stranglethorn Vale": { x: 35, y: 88 }, "Burning Steppes": { x: 50, y: 62 },
    "Tirisfal Glades": { x: 48, y: 18 }, "Silverpine Forest": { x: 42, y: 25 },
    "Hillsbrad Foothills": { x: 47, y: 32 }, "Arathi Highlands": { x: 56, y: 35 },
    "The Hinterlands": { x: 58, y: 30 }, "Western Plaguelands": { x: 52, y: 22 },
    "Eastern Plaguelands": { x: 62, y: 20 }, "Eversong Woods": { x: 65, y: 10 },
    "Silvermoon City": { x: 68, y: 8 }, "Badlands": { x: 55, y: 55 },
    "Twilight Highlands": { x: 65, y: 45 },
  },
  Kalimdor: {
    Orgrimmar: { x: 60, y: 28 }, "Thunder Bluff": { x: 42, y: 48 },
    Durotar: { x: 62, y: 32 }, Mulgore: { x: 40, y: 52 },
    Ashenvale: { x: 38, y: 32 }, Felwood: { x: 35, y: 22 },
    Tanaris: { x: 52, y: 82 }, Silithus: { x: 35, y: 88 },
    "Un'Goro Crater": { x: 42, y: 80 }, Winterspring: { x: 50, y: 15 },
    "Mount Hyjal": { x: 45, y: 18 }, Uldum: { x: 55, y: 90 },
    Desolace: { x: 28, y: 52 }, Feralas: { x: 25, y: 62 },
    Darkshore: { x: 22, y: 22 },
  },
  Northrend: {
    "Borean Tundra": { x: 20, y: 75 }, "Howling Fjord": { x: 75, y: 80 },
    Dragonblight: { x: 45, y: 60 }, "Grizzly Hills": { x: 68, y: 55 },
    "Zul'Drak": { x: 62, y: 40 }, "Sholazar Basin": { x: 25, y: 45 },
    "The Storm Peaks": { x: 40, y: 25 }, Icecrown: { x: 55, y: 20 },
  },
  Shadowlands: {
    Oribos: { x: 50, y: 50 }, Bastion: { x: 70, y: 20 },
    Maldraxxus: { x: 70, y: 45 }, Ardenweald: { x: 30, y: 20 },
    Revendreth: { x: 30, y: 70 }, "The Maw": { x: 50, y: 85 },
    "Zereth Mortis": { x: 50, y: 15 },
  },
  "Dragon Isles": {
    "The Waking Shores": { x: 55, y: 80 }, "Ohn'ahran Plains": { x: 45, y: 55 },
    "The Azure Span": { x: 35, y: 35 }, Thaldraszus: { x: 60, y: 30 },
    Valdrakken: { x: 55, y: 25 }, "Zaralek Cavern": { x: 50, y: 60 },
    "Emerald Dream": { x: 30, y: 15 },
  },
  "Khaz Algar": {
    Dornogal: { x: 50, y: 20 }, "Isle of Dorn": { x: 40, y: 35 },
    "The Ringing Deeps": { x: 55, y: 50 }, Hallowfall: { x: 45, y: 65 },
    "Azj-Kahet": { x: 50, y: 80 },
  },
};

const CONTINENTS = Object.keys(ZONE_POSITIONS);

export default function RouteMapPage() {
  const { id } = useParams<{ id: string }>();
  const [selectedContinent, setSelectedContinent] = useState(CONTINENTS[0]);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);

  const { data: route, isLoading } = useQuery<RouteData>({
    queryKey: ["route", id],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<RouteData>>(`/routes/${id}`);
      return res.data.data;
    },
  });

  // Build zone → stops map
  const zoneStops = useMemo(() => {
    if (!route) return new Map<string, RouteStopData[]>();
    const map = new Map<string, RouteStopData[]>();
    const allStops = [
      ...route.seasonal_block.stops,
      ...route.sessions.flatMap((s) => s.stops),
    ];
    for (const stop of allStops) {
      const zoneName = stop.zone?.name || "Unknown";
      const arr = map.get(zoneName) || [];
      arr.push(stop);
      map.set(zoneName, arr);
    }
    return map;
  }, [route]);

  // Zone completion status
  const zoneStatus = (zoneName: string): "active" | "completed" | "none" => {
    const stops = zoneStops.get(zoneName);
    if (!stops || stops.length === 0) return "none";
    if (stops.every((s) => s.completed)) return "completed";
    return "active";
  };

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="animate-spin text-primary" size={24} /></div>;
  }

  // Mobile guard
  return (
    <div>
      {/* Mobile warning */}
      <div className="md:hidden bg-surface border border-border rounded-lg p-6 text-center">
        <p className="text-text-secondary mb-4">Map view is not available on mobile.</p>
        <Link href={`/routes/${id}`} className="inline-flex items-center gap-2 text-primary hover:underline">
          <List size={16} /> Switch to List View
        </Link>
      </div>

      {/* Desktop map */}
      <div className="hidden md:flex gap-6">
        <div className="flex-1">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Link href={`/routes/${id}`} className="text-sm text-text-secondary hover:text-primary flex items-center gap-1">
                <List size={14} /> List View
              </Link>
            </div>
          </div>

          {/* Continent tabs */}
          <div className="flex flex-wrap gap-1 mb-4">
            {CONTINENTS.map((c) => (
              <button
                key={c}
                onClick={() => { setSelectedContinent(c); setSelectedZone(null); }}
                className={cn(
                  "px-3 py-1.5 rounded text-xs font-medium transition-colors",
                  selectedContinent === c ? "bg-primary text-background" : "bg-surface-elevated text-text-secondary hover:text-text-primary"
                )}
              >
                {c}
              </button>
            ))}
          </div>

          {/* SVG Map */}
          <div className="bg-surface rounded-lg border border-border p-4 relative aspect-[4/3]">
            <svg viewBox="0 0 100 100" className="w-full h-full">
              {Object.entries(ZONE_POSITIONS[selectedContinent] || {}).map(([zoneName, pos]) => {
                const status = zoneStatus(zoneName);
                const stops = zoneStops.get(zoneName);
                const isSelected = selectedZone === zoneName;
                const fill = status === "completed" ? "var(--success)" : status === "active" ? "var(--primary)" : "#2d2d4e";
                return (
                  <g key={zoneName} onClick={() => setSelectedZone(zoneName)} className="cursor-pointer">
                    <circle
                      cx={pos.x}
                      cy={pos.y}
                      r={isSelected ? 4 : 3}
                      fill={fill}
                      stroke={isSelected ? "#fff" : "none"}
                      strokeWidth={0.5}
                    />
                    <text x={pos.x} y={pos.y + 6} textAnchor="middle" fill="#9aa0b4" fontSize="2.5" className="pointer-events-none">
                      {zoneName.length > 15 ? zoneName.slice(0, 13) + "..." : zoneName}
                    </text>
                    {stops && stops.length > 0 && (
                      <text x={pos.x + 4} y={pos.y - 2} textAnchor="start" fill="#c9a227" fontSize="2.5" fontWeight="bold" className="pointer-events-none">
                        {stops.length}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          </div>
        </div>

        {/* Sidebar */}
        <div className="w-80 shrink-0">
          <div className="bg-surface rounded-lg border border-border p-4 sticky top-4">
            {selectedZone ? (
              <>
                <h3 className="font-semibold mb-3">{selectedZone}</h3>
                {(zoneStops.get(selectedZone) || []).map((stop) => (
                  <div key={stop.id} className={cn("p-2 rounded mb-2 border border-border text-sm", stop.completed && "opacity-40")}>
                    <p className="font-semibold text-primary text-xs">{stop.achievement?.name}</p>
                    <p className="text-xs text-text-secondary">{formatMinutes(stop.estimated_minutes)}</p>
                  </div>
                ))}
              </>
            ) : (
              <p className="text-sm text-text-secondary">Click a zone to see its achievements</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
