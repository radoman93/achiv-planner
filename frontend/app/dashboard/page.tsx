"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api, { type ApiEnvelope, type CharacterSummary, type RouteSummary, type UserStats } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { formatMinutes } from "@/lib/utils";
import { AlertTriangle, ChevronRight, Plus, RefreshCw, X } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

export default function DashboardPage() {
  useAuth();
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // Check localStorage for banner dismiss
  useEffect(() => {
    const key = `seasonal_banner_dismissed_${new Date().toISOString().slice(0, 10)}`;
    if (typeof window !== "undefined" && localStorage.getItem(key)) {
      setBannerDismissed(true);
    }
  }, []);

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
      const res = await api.get<ApiEnvelope<{ active?: { event_name: string; days_remaining: number; achievement_count: number }[] }>>("/achievements/seasonal?status=active");
      return res.data.data.active || [];
    },
  });

  const activeRoute = routes?.[0];
  const primaryChar = characters?.[0];

  // Expansion chart data
  const expansionData = stats?.completion_by_expansion
    ? Object.entries(stats.completion_by_expansion)
        .slice(-5)
        .map(([name, data]) => ({ name: name.length > 12 ? name.slice(0, 12) + "..." : name, pct: data.pct }))
    : [];

  return (
    <div>
      {/* Seasonal Alert Banner */}
      {!bannerDismissed && seasonal && seasonal.length > 0 && (
        <div className="bg-gradient-to-r from-warning/20 to-error/20 border border-warning/30 rounded-lg p-4 mb-6 flex items-center gap-3">
          <AlertTriangle className="text-warning shrink-0" size={20} />
          <div className="flex-1">
            <p className="text-sm font-semibold">
              {seasonal[0].achievement_count} seasonal achievements available &mdash; {seasonal[0].days_remaining} days remaining on {seasonal[0].event_name}
            </p>
            {seasonal.length > 1 && (
              <Link href="/calendar" className="text-xs text-primary hover:underline">
                and {seasonal.length - 1} more events
              </Link>
            )}
          </div>
          <button onClick={dismissBanner} className="text-text-secondary hover:text-text-primary">
            <X size={18} />
          </button>
        </div>
      )}

      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Active Route Card */}
        <div className="bg-surface rounded-lg border border-border p-6">
          <h2 className="text-sm font-semibold text-text-secondary mb-3">Active Route</h2>
          {activeRoute ? (
            <>
              <p className="text-lg font-bold capitalize mb-1">{activeRoute.mode} Mode</p>
              <p className="text-sm text-text-secondary mb-4">
                {formatMinutes(activeRoute.total_estimated_minutes)} estimated
              </p>
              <Link
                href={`/routes/${activeRoute.id}`}
                className="inline-flex items-center gap-1 bg-primary hover:bg-primary-hover text-background font-semibold rounded px-4 py-2 text-sm"
              >
                Continue Route <ChevronRight size={16} />
              </Link>
            </>
          ) : (
            <div className="text-center py-4">
              <p className="text-text-secondary text-sm mb-3">No active route yet</p>
              <Link
                href="/routes"
                className="inline-flex items-center gap-1 bg-primary hover:bg-primary-hover text-background font-semibold rounded px-4 py-2 text-sm"
              >
                <Plus size={16} /> Generate Your First Route
              </Link>
            </div>
          )}
        </div>

        {/* Character Stats Card */}
        <div className="bg-surface rounded-lg border border-border p-6">
          <h2 className="text-sm font-semibold text-text-secondary mb-3">
            {primaryChar ? primaryChar.name : "Character Stats"}
          </h2>
          {stats ? (
            <>
              <div className="flex items-center gap-4 mb-4">
                {/* Circular progress */}
                <div className="relative w-16 h-16">
                  <svg viewBox="0 0 36 36" className="w-16 h-16">
                    <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="var(--border)" strokeWidth="3" />
                    <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="var(--primary)" strokeWidth="3" strokeDasharray={`${stats.overall_completion_pct}, 100`} />
                  </svg>
                  <span className="absolute inset-0 flex items-center justify-center text-xs font-bold">
                    {stats.overall_completion_pct}%
                  </span>
                </div>
                <div>
                  <p className="font-mono text-primary font-bold">{stats.total_achievement_points.toLocaleString()} pts</p>
                  <p className="text-xs text-text-secondary">
                    {stats.total_achievements_completed} / {stats.total_achievements_eligible} achievements
                  </p>
                  <p className="text-xs text-text-secondary">
                    ~{stats.estimated_hours_remaining}h remaining
                  </p>
                </div>
              </div>
              {/* Expansion chart */}
              {expansionData.length > 0 && (
                <div className="h-32 -mx-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={expansionData}>
                      <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#9aa0b4" }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "#9aa0b4" }} />
                      <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid #2d2d4e", borderRadius: 8, fontSize: 12 }} />
                      <Bar dataKey="pct" radius={[4, 4, 0, 0]}>
                        {expansionData.map((_, i) => (
                          <Cell key={i} fill="#c9a227" />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </>
          ) : (
            <p className="text-text-secondary text-sm">Loading stats...</p>
          )}
        </div>

        {/* Quick Actions */}
        <div className="bg-surface rounded-lg border border-border p-6">
          <h2 className="text-sm font-semibold text-text-secondary mb-3">Quick Actions</h2>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/routes"
              className="inline-flex items-center gap-2 bg-surface-elevated border border-border rounded-lg px-4 py-2 text-sm hover:border-primary transition-colors"
            >
              <RefreshCw size={14} /> Regenerate Route
            </Link>
            {characters && characters.length > 1 && (
              <div className="inline-flex items-center gap-2 bg-surface-elevated border border-border rounded-lg px-4 py-2 text-sm">
                <select className="bg-transparent text-text-primary text-sm">
                  {characters.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} - {c.realm}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Recent Activity */}
        <div className="bg-surface rounded-lg border border-border p-6">
          <h2 className="text-sm font-semibold text-text-secondary mb-3">Recent Activity</h2>
          {stats && stats.achievements_completed_this_month > 0 ? (
            <p className="text-sm text-text-secondary">
              {stats.achievements_completed_this_month} achievements completed this month
              {stats.favorite_category && (
                <span> &middot; Favorite: {stats.favorite_category}</span>
              )}
            </p>
          ) : (
            <p className="text-sm text-text-secondary">No achievements completed yet. Start your first route!</p>
          )}
        </div>
      </div>
    </div>
  );
}
