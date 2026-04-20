"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, { type ApiEnvelope, type RouteSummary, type RouteData, type CharacterSummary } from "@/lib/api-client";
import { formatMinutes, cn } from "@/lib/utils";
import { Plus, Loader2 } from "lucide-react";

export default function RoutesListPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [generating, setGenerating] = useState(false);

  const { data: routes, isLoading } = useQuery<RouteSummary[]>({
    queryKey: ["routes", "all"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<RouteSummary[]>>("/routes?status=all");
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

  const handleGenerate = async () => {
    if (!characters?.length) return;
    setGenerating(true);
    try {
      const res = await api.post<ApiEnvelope<RouteData>>("/routes/generate", {
        character_id: characters[0].id,
        mode: "completionist",
      });
      qc.invalidateQueries({ queryKey: ["routes"] });
      router.push(`/routes/${res.data.data.id}`);
    } catch { /* error handled by interceptor */ }
    setGenerating(false);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">My Routes</h1>
        <button
          onClick={handleGenerate}
          disabled={generating || !characters?.length}
          className="inline-flex items-center gap-2 bg-primary hover:bg-primary-hover text-background font-semibold rounded px-4 py-2 text-sm disabled:opacity-50"
        >
          {generating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          Generate Route
        </button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12"><Loader2 className="animate-spin text-primary" size={24} /></div>
      ) : routes && routes.length > 0 ? (
        <div className="space-y-3">
          {routes.map((r) => (
            <Link
              key={r.id}
              href={`/routes/${r.id}`}
              className="block bg-surface rounded-lg border border-border p-4 hover:border-primary transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="capitalize font-semibold">{r.mode}</span>
                  <span className={cn("ml-2 text-xs px-2 py-0.5 rounded", r.status === "active" ? "bg-success/20 text-success" : "bg-border text-text-secondary")}>
                    {r.status}
                  </span>
                </div>
                <span className="text-sm text-text-secondary">{formatMinutes(r.total_estimated_minutes)}</span>
              </div>
              <p className="text-xs text-text-secondary mt-1">
                Created {r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"}
              </p>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-center py-12">
          <p className="text-text-secondary mb-4">No routes yet. Generate your first one!</p>
        </div>
      )}
    </div>
  );
}
