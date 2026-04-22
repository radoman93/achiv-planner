"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import api, { type ApiEnvelope, type RouteSummary, type RouteData, type CharacterSummary } from "@/lib/api-client";
import { formatMinutes, cn } from "@/lib/utils";
import { Plus, Loader2 } from "lucide-react";

type SyncNeededState = { characterId: string } | null;
type SyncingState = { characterId: string; percent: number } | null;

async function waitForSync(characterId: string, jobId: string, onProgress: (pct: number) => void): Promise<"completed" | "failed"> {
  while (true) {
    const res = await api.get<ApiEnvelope<{
      status: string;
      progress: { processed: number; total: number; percent: number };
    }>>(`/characters/${characterId}/sync/status/${jobId}`);
    const data = res.data.data;
    onProgress(data.progress.percent);
    if (data.status === "completed") return "completed";
    if (data.status === "failed") return "failed";
    await new Promise((r) => setTimeout(r, 3000));
  }
}

export default function RoutesListPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [generating, setGenerating] = useState(false);
  const [syncNeeded, setSyncNeeded] = useState<SyncNeededState>(null);
  const [syncing, setSyncing] = useState<SyncingState>(null);
  const [genError, setGenError] = useState<string | null>(null);

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

  const generateFor = async (characterId: string) => {
    setGenError(null);
    const res = await api.post<ApiEnvelope<RouteData>>("/routes/generate", {
      character_id: characterId,
      mode: "completionist",
    });
    qc.invalidateQueries({ queryKey: ["routes"] });
    router.push(`/routes/${res.data.data.id}`);
  };

  const handleGenerate = async () => {
    if (!characters?.length) return;
    const characterId = characters[0].id;
    setGenerating(true);
    try {
      await generateFor(characterId);
    } catch (err) {
      const axErr = err as AxiosError<{ detail?: { error?: string; character_id?: string } }>;
      const detail = axErr.response?.data?.detail;
      if (axErr.response?.status === 409 && detail && typeof detail === "object" && detail.error === "character_not_synced") {
        setSyncNeeded({ characterId: detail.character_id ?? characterId });
      } else {
        setGenError("Failed to generate route. Please try again.");
      }
    }
    setGenerating(false);
  };

  const handleSyncNow = async () => {
    if (!syncNeeded) return;
    const { characterId } = syncNeeded;
    setSyncNeeded(null);
    setSyncing({ characterId, percent: 0 });
    try {
      const res = await api.post<ApiEnvelope<{ job_id: string }>>(`/characters/${characterId}/sync`);
      const jobId = res.data.data.job_id;
      const outcome = await waitForSync(characterId, jobId, (p) =>
        setSyncing((s) => (s ? { ...s, percent: p } : s)),
      );
      if (outcome === "failed") {
        setSyncing(null);
        setGenError("Sync failed. Check the character still exists on Battle.net, then try again.");
        return;
      }
      qc.invalidateQueries({ queryKey: ["characters"] });
      setSyncing(null);
      setGenerating(true);
      try {
        await generateFor(characterId);
      } catch {
        setGenError("Route generation failed after sync. Please try again.");
      }
      setGenerating(false);
    } catch {
      setSyncing(null);
      setGenError("Could not start sync. Please try again.");
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">My Routes</h1>
        <button
          onClick={handleGenerate}
          disabled={generating || syncing !== null || !characters?.length}
          className="inline-flex items-center gap-2 bg-primary hover:bg-primary-hover text-background font-semibold rounded px-4 py-2 text-sm disabled:opacity-50"
        >
          {generating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          Generate Route
        </button>
      </div>

      {genError && (
        <div className="mb-4 bg-error/10 border border-error/40 text-error rounded-lg p-3 text-sm">
          {genError}
        </div>
      )}

      {syncNeeded && (
        <div className="mb-4 bg-surface border border-border rounded-lg p-4">
          <p className="font-semibold mb-1">This character hasn&apos;t been synced yet</p>
          <p className="text-sm text-text-secondary mb-3">
            We need to pull your completed achievements from Battle.net before generating a route, otherwise the route will include things you&apos;ve already done.
          </p>
          <div className="flex gap-2">
            <button
              onClick={handleSyncNow}
              className="bg-primary hover:bg-primary-hover text-background font-semibold rounded px-4 py-2 text-sm"
            >
              Sync now
            </button>
            <button
              onClick={() => setSyncNeeded(null)}
              className="bg-surface-elevated border border-border rounded px-4 py-2 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {syncing && (
        <div className="mb-4 bg-surface border border-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Loader2 className="animate-spin text-primary" size={16} />
            <p className="font-semibold text-sm">Syncing achievements from Battle.net…</p>
          </div>
          <div className="w-full bg-border rounded-full h-2 overflow-hidden">
            <div
              className="bg-primary h-full transition-all duration-500"
              style={{ width: `${syncing.percent}%` }}
            />
          </div>
          <p className="text-xs text-text-secondary mt-2">{syncing.percent}%</p>
        </div>
      )}

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
