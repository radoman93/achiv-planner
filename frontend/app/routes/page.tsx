"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import api, {
  type ApiEnvelope,
  type CharacterSummary,
  type RouteData,
  type RouteSummary,
} from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { cn, formatMinutes } from "@/lib/utils";
import {
  Check,
  ChevronRight,
  Compass,
  Flag,
  Loader2,
  Target,
  Timer,
  Wand2,
} from "lucide-react";

type SyncNeededState = { characterId: string } | null;
type SyncingState = { characterId: string; percent: number } | null;

type PriorityMode = "completionist" | "pph" | "goal" | "seasonal";

type Constraints = {
  flying: boolean;
  groupContent: boolean;
  dungeons: boolean;
  raids: boolean;
  pvp: boolean;
  includeSeasonal: boolean;
  timeBudget: number;
};

const MODES: {
  id: PriorityMode;
  name: string;
  blurb: string;
  icon: string;
  Icon: React.ComponentType<{ size?: number }>;
  backendValue: string;
}[] = [
  {
    id: "completionist",
    name: "Completionist",
    blurb: "Total coverage. Every achievement you can still get, ordered most efficiently.",
    icon: "◆",
    Icon: Compass,
    backendValue: "completionist",
  },
  {
    id: "pph",
    name: "Points per Hour",
    blurb: "Maximize achievement points earned per hour played. Pragmatic grinder's path.",
    icon: "⚡",
    Icon: Timer,
    backendValue: "points_per_hour",
  },
  {
    id: "goal",
    name: "Goal-Driven",
    blurb: "Pick a meta-achievement. The engine works backward to get you there.",
    icon: "◉",
    Icon: Target,
    backendValue: "goal_driven",
  },
  {
    id: "seasonal",
    name: "Seasonal First",
    blurb: "Prioritize time-gated achievements above all else. Nothing expires on your watch.",
    icon: "✦",
    Icon: Flag,
    backendValue: "seasonal_first",
  },
];

const GEN_STEPS = [
  "Fetching character state from Battle.net",
  "Applying constraint filter (flying, level, faction)",
  "Resolving dependency graph",
  "Geographic clustering · nearest-neighbor + 2-opt",
  "Structuring into sessions",
  "Injecting seasonal overrides",
];

async function waitForSync(
  characterId: string,
  jobId: string,
  onProgress: (pct: number) => void,
): Promise<"completed" | "failed"> {
  while (true) {
    const res = await api.get<
      ApiEnvelope<{
        status: string;
        progress: { processed: number; total: number; percent: number };
      }>
    >(`/characters/${characterId}/sync/status/${jobId}`);
    const data = res.data.data;
    onProgress(data.progress.percent);
    if (data.status === "completed") return "completed";
    if (data.status === "failed") return "failed";
    await new Promise((r) => setTimeout(r, 3000));
  }
}

export default function RoutesPage() {
  useAuth();
  const router = useRouter();
  const qc = useQueryClient();

  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<PriorityMode>("completionist");
  const [constraints, setConstraints] = useState<Constraints>({
    flying: true,
    groupContent: false,
    dungeons: false,
    raids: false,
    pvp: false,
    includeSeasonal: true,
    timeBudget: 4,
  });

  const [generating, setGenerating] = useState(false);
  const [genStep, setGenStep] = useState(0);
  const [genError, setGenError] = useState<string | null>(null);
  const [syncNeeded, setSyncNeeded] = useState<SyncNeededState>(null);
  const [syncing, setSyncing] = useState<SyncingState>(null);

  const { data: characters } = useQuery<CharacterSummary[]>({
    queryKey: ["characters"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<CharacterSummary[]>>("/characters");
      return res.data.data;
    },
  });

  const { data: pastRoutes } = useQuery<RouteSummary[]>({
    queryKey: ["routes", "all"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<RouteSummary[]>>("/routes?status=all");
      return res.data.data;
    },
  });

  useEffect(() => {
    if (!generating) return;
    setGenStep(0);
    const interval = setInterval(() => {
      setGenStep((s) => {
        if (s >= GEN_STEPS.length - 1) {
          clearInterval(interval);
          return GEN_STEPS.length;
        }
        return s + 1;
      });
    }, 550);
    return () => clearInterval(interval);
  }, [generating]);

  const generateFor = async (characterId: string) => {
    const selectedMode = MODES.find((m) => m.id === mode)?.backendValue ?? "completionist";
    const res = await api.post<ApiEnvelope<RouteData>>("/routes/generate", {
      character_id: characterId,
      mode: selectedMode,
      session_duration_minutes: constraints.timeBudget * 60,
      include_seasonal: constraints.includeSeasonal,
      solo_only: !constraints.groupContent,
    });
    qc.invalidateQueries({ queryKey: ["routes"] });
    router.push(`/routes/${res.data.data.id}`);
  };

  const handleChart = async () => {
    if (!characters?.length) {
      setGenError("Connect a character first.");
      return;
    }
    setGenError(null);
    setGenerating(true);
    try {
      await generateFor(characters[0].id);
    } catch (err) {
      setGenerating(false);
      const axErr = err as AxiosError<{
        detail?: { error?: string; character_id?: string };
      }>;
      const detail = axErr.response?.data?.detail;
      if (
        axErr.response?.status === 409 &&
        detail &&
        typeof detail === "object" &&
        detail.error === "character_not_synced"
      ) {
        setSyncNeeded({ characterId: detail.character_id ?? characters[0].id });
      } else {
        setGenError("Failed to generate route. Please try again.");
      }
    }
  };

  const handleSyncNow = async () => {
    if (!syncNeeded) return;
    const { characterId } = syncNeeded;
    setSyncNeeded(null);
    setSyncing({ characterId, percent: 0 });
    try {
      const res = await api.post<ApiEnvelope<{ job_id: string }>>(
        `/characters/${characterId}/sync`,
      );
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
        setGenerating(false);
        setGenError("Route generation failed after sync. Please try again.");
      }
    } catch {
      setSyncing(null);
      setGenError("Could not start sync. Please try again.");
    }
  };

  const steps = ["Priority", "Constraints", "Goal", "Review"];

  if (generating) {
    return (
      <div className="wiz fade-in">
        <div className="grid place-items-center min-h-[400px]">
          <div className="text-center max-w-[440px]">
            <div className="gen-ring">
              <svg viewBox="0 0 120 120">
                <circle
                  cx="60"
                  cy="60"
                  r="54"
                  stroke="var(--gold-4)"
                  strokeWidth="1"
                  fill="none"
                  strokeDasharray="2 6"
                />
                <circle
                  cx="60"
                  cy="60"
                  r="44"
                  stroke="var(--gold-2)"
                  strokeWidth="1"
                  fill="none"
                  strokeDasharray="100 200"
                />
                <circle
                  cx="60"
                  cy="60"
                  r="34"
                  stroke="var(--gold-3)"
                  strokeWidth="1"
                  fill="none"
                  strokeDasharray="4 8"
                />
              </svg>
              <div className="inner">◆</div>
            </div>
            <div className="font-display text-[22px] text-gold-1 mb-1.5">
              Charting your route
            </div>
            <div className="font-mono text-[12px] text-fg-3">
              The Assembler is combining 6 pipeline outputs
            </div>
            <div className="mt-7 text-left">
              {GEN_STEPS.map((s, i) => (
                <div
                  key={i}
                  className={cn(
                    "gen-step",
                    i < genStep && "done",
                    i === genStep && "active",
                  )}
                >
                  <span className="s-num">
                    {i < genStep ? <Check size={10} /> : i + 1}
                  </span>
                  <span>{s}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="wiz fade-in">
      {/* Page header */}
      <div className="mb-7">
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-1.5 flex items-center gap-2">
          <span
            className="inline-block w-[5px] h-[5px]"
            style={{ transform: "rotate(45deg)", background: "var(--gold-2)" }}
          />
          New Route
        </div>
        <h1 className="font-display text-[28px] font-semibold tracking-tight m-0 mb-1.5">
          Plan your next journey
        </h1>
        <p className="text-[13px] text-fg-3 m-0 max-w-[68ch]">
          Four steps. The router engine handles dependency, geography, and seasonal overrides for
          you.
        </p>
      </div>

      {/* Step indicator */}
      <div className="wiz-steps">
        {steps.map((s, i) => (
          <div
            key={s}
            className={cn(
              "wiz-step",
              i < step && "done",
              i === step && "active",
            )}
          >
            <div className="num">{i < step ? <Check size={12} /> : i + 1}</div>
            <div className="step-label">{s}</div>
          </div>
        ))}
      </div>

      {/* Error / sync banners */}
      {genError && (
        <div
          className="mb-4 p-3 text-sm"
          style={{
            background: "rgba(200, 100, 100, 0.08)",
            border: "1px solid rgba(200, 100, 100, 0.3)",
            color: "var(--bad)",
            borderRadius: "var(--r-md)",
          }}
        >
          {genError}
        </div>
      )}

      {syncNeeded && (
        <div
          className="mb-4 p-4"
          style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--r-md)",
          }}
        >
          <p className="font-semibold mb-1">This character hasn&apos;t been synced yet</p>
          <p className="text-sm text-fg-3 mb-3">
            We need to pull your completed achievements from Battle.net before generating a
            route, otherwise the route will include things you&apos;ve already done.
          </p>
          <div className="flex gap-2">
            <button onClick={handleSyncNow} className="btn btn-primary">
              Sync now
            </button>
            <button onClick={() => setSyncNeeded(null)} className="btn">
              Cancel
            </button>
          </div>
        </div>
      )}

      {syncing && (
        <div
          className="mb-4 p-4"
          style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--r-md)",
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Loader2 className="animate-spin text-gold-1" size={16} />
            <p className="font-semibold text-sm m-0">Syncing achievements from Battle.net…</p>
          </div>
          <div
            className="w-full h-2 rounded-full overflow-hidden"
            style={{ background: "var(--bg-3)" }}
          >
            <div
              className="h-full transition-all duration-500"
              style={{
                width: `${syncing.percent}%`,
                background: "linear-gradient(90deg, var(--gold-3), var(--gold-1))",
                boxShadow: "0 0 12px var(--gold-glow)",
              }}
            />
          </div>
          <p className="text-xs text-fg-3 mt-2 font-mono">{syncing.percent}%</p>
        </div>
      )}

      {/* Step content */}
      {step === 0 && (
        <div className="mode-grid fade-in">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={cn("mode-card", mode === m.id && "selected")}
              onClick={() => setMode(m.id)}
            >
              <div className="m-ico">{m.icon}</div>
              <div className="m-name">{m.name}</div>
              <div className="m-blurb">{m.blurb}</div>
              <div className="m-check">
                {mode === m.id && <Check size={12} />}
              </div>
            </button>
          ))}
        </div>
      )}

      {step === 1 && (
        <div
          className="fade-in"
          style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--r-lg)",
            overflow: "hidden",
          }}
        >
          <div
            className="px-[18px] py-3.5 flex items-center justify-between"
            style={{ borderBottom: "1px solid var(--border-1)" }}
          >
            <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-fg-3 m-0">
              Hard Constraints · applied at filter stage
            </h3>
          </div>
          {(
            [
              { k: "flying", name: "Flying unlocked", hint: "All expansions · pathfinder cleared" },
              {
                k: "groupContent",
                name: "Include group content",
                hint: "Dungeons, raids, PvP instances",
              },
              { k: "dungeons", name: "Dungeons", hint: "Mythic & heroic versions" },
              {
                k: "raids",
                name: "Raids",
                hint: "Requires full group · only if above is on",
              },
              { k: "pvp", name: "PvP content", hint: "Battlegrounds & arena achievements" },
              {
                k: "includeSeasonal",
                name: "Inject seasonal windows",
                hint: "Time-gated content overrides ordering",
              },
            ] as { k: keyof Constraints; name: string; hint: string }[]
          ).map((c) => (
            <div
              key={c.k}
              className="flex items-center gap-4 px-4 py-3 border-b last:border-0"
              style={{ borderColor: "var(--border-1)" }}
            >
              <div className="flex-1">
                <div className="text-[13px] font-medium">{c.name}</div>
                <div className="text-[11px] text-fg-3 font-mono mt-0.5">{c.hint}</div>
              </div>
              <button
                className={cn("toggle", Boolean(constraints[c.k]) && "on")}
                onClick={() =>
                  setConstraints({ ...constraints, [c.k]: !constraints[c.k] })
                }
                aria-pressed={Boolean(constraints[c.k])}
              />
            </div>
          ))}
          <div
            className="px-4 py-3.5"
            style={{ borderTop: "1px solid var(--border-1)" }}
          >
            <div className="flex items-center justify-between mb-2.5">
              <div>
                <div className="text-[13px] font-medium">Time budget per session</div>
                <div className="text-[11px] text-fg-3 font-mono mt-0.5">
                  Structures route into playable chunks
                </div>
              </div>
              <div className="font-mono text-[13px] text-gold-1 font-semibold">
                {constraints.timeBudget}h
              </div>
            </div>
            <input
              type="range"
              min={1}
              max={12}
              step={1}
              value={constraints.timeBudget}
              onChange={(e) =>
                setConstraints({ ...constraints, timeBudget: +e.target.value })
              }
              className="w-full"
              style={{
                accentColor: "var(--gold-1)",
              }}
            />
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="fade-in text-center">
          <div className="font-mono text-[11px] uppercase tracking-[0.1em] text-fg-3 mb-4">
            The engine will pick the meta that best fits your mode and character state.
          </div>
          <div
            className="p-6"
            style={{
              background: "var(--bg-1)",
              border: "1px solid var(--border-1)",
              borderRadius: "var(--r-lg)",
            }}
          >
            <Wand2 className="mx-auto text-gold-1 mb-3" size={28} />
            <div className="font-display text-[18px] font-semibold mb-1">
              Goal inferred from mode
            </div>
            <div className="text-[13px] text-fg-3 max-w-[46ch] mx-auto">
              When you chose{" "}
              <span className="text-gold-1 font-medium">
                {MODES.find((m) => m.id === mode)?.name}
              </span>
              , we lined up the most appropriate meta-achievement for your character.
              {mode === "seasonal" && " We'll prioritize whatever's time-gated this month."}
              {mode === "pph" && " We'll prefer short high-value achievements first."}
              {mode === "completionist" && " We'll order every outstanding achievement."}
              {mode === "goal" && " We'll work backward from the biggest unfinished meta."}
            </div>
          </div>
        </div>
      )}

      {step === 3 && (
        <div
          className="fade-in"
          style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--r-lg)",
            overflow: "hidden",
          }}
        >
          <div
            className="px-[18px] py-3.5 flex items-center justify-between"
            style={{ borderBottom: "1px solid var(--border-1)" }}
          >
            <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-fg-3 m-0">
              Ready to chart
            </h3>
          </div>
          <div className="p-6 grid gap-5" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <ReviewRow label="Priority Mode" value={MODES.find((m) => m.id === mode)?.name ?? "—"} />
            <ReviewRow label="Goal" value="Auto-selected meta" />
            <ReviewRow label="Session Budget" value={`${constraints.timeBudget}h / session`} />
            <ReviewRow
              label="Constraints Active"
              value={`${
                Object.entries(constraints).filter(([, v]) => typeof v === "boolean" && v).length
              } of 6`}
            />
          </div>
          <div
            className="px-6 py-4 text-[12px] text-fg-3 leading-[1.7]"
            style={{ borderTop: "1px solid var(--border-1)" }}
          >
            The engine will run:{" "}
            <span className="font-mono text-gold-1">
              constraint filter → dependency resolver → geographic clusterer → session structurer →
              seasonal override → assembler
            </span>
            . Route persists to your profile.
          </div>
        </div>
      )}

      {/* Footer */}
      <div
        className="flex justify-between mt-6 pt-5"
        style={{ borderTop: "1px solid var(--border-1)" }}
      >
        <button
          className="btn"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          style={{ opacity: step === 0 ? 0.4 : 1 }}
        >
          Back
        </button>
        {step < 3 ? (
          <button className="btn btn-primary" onClick={() => setStep((s) => s + 1)}>
            Continue <ChevronRight size={12} />
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={handleChart}
            disabled={syncing !== null}
          >
            <Wand2 size={14} /> Chart my route
          </button>
        )}
      </div>

      {/* Past routes */}
      {pastRoutes && pastRoutes.length > 0 && (
        <div className="mt-16">
          <div className="font-mono text-[11px] uppercase tracking-[0.1em] text-fg-3 mb-4">
            Past Routes
          </div>
          <div className="grid gap-2">
            {pastRoutes.map((r) => (
              <Link
                key={r.id}
                href={`/routes/${r.id}`}
                className="block p-4 hover:border-border-2 transition-colors"
                style={{
                  background: "var(--bg-1)",
                  border: "1px solid var(--border-1)",
                  borderRadius: "var(--r-md)",
                  textDecoration: "none",
                }}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="capitalize font-semibold">{r.mode}</span>
                    <span
                      className={cn(
                        "ml-2 text-xs px-2 py-0.5 rounded font-mono uppercase tracking-[0.08em]",
                      )}
                      style={{
                        background:
                          r.status === "active"
                            ? "rgba(143, 191, 122, 0.12)"
                            : "var(--bg-3)",
                        color:
                          r.status === "active" ? "var(--good)" : "var(--fg-3)",
                      }}
                    >
                      {r.status}
                    </span>
                  </div>
                  <span className="text-sm text-fg-3 font-mono">
                    {formatMinutes(r.total_estimated_minutes)}
                  </span>
                </div>
                <p className="text-xs text-fg-3 mt-1 font-mono m-0">
                  Created {r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"}
                </p>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] text-fg-3 uppercase tracking-[0.14em] mb-1">
        {label}
      </div>
      <div className="font-display text-[18px] text-gold-1 font-semibold">{value}</div>
    </div>
  );
}
