"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import api, { type ApiEnvelope, type CharacterSummary } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Check, Loader2, Map, Sword, Trophy, Calendar } from "lucide-react";

const VALID_CLASSES = [
  "warrior","paladin","hunter","rogue","priest","shaman",
  "mage","warlock","monk","druid","demon hunter","death knight","evoker",
];

const MODES = [
  { id: "completionist", label: "Completionist", desc: "Get everything. Full coverage, optimized order.", icon: Map },
  { id: "points_per_hour", label: "Points Per Hour", desc: "Maximum achievement points in minimum time.", icon: Sword },
  { id: "goal_driven", label: "Goal-Driven", desc: "Pick a meta-achievement and work backwards to it.", icon: Trophy },
  { id: "seasonal_first", label: "Seasonal First", desc: "Never miss a time-limited achievement.", icon: Calendar },
];

const DURATION_MARKS = [30,60,90,120,150,180,210,240,300,360,420,480];

function durationLabel(m: number) {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}h ${r}m` : `${h} hours`;
}

export default function OnboardingPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [step, setStep] = useState(1);

  // Step 1 state
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [selectedCharId, setSelectedCharId] = useState<string | null>(null);
  const [loadingChars, setLoadingChars] = useState(true);
  // Manual form
  const [manualName, setManualName] = useState("");
  const [manualRealm, setManualRealm] = useState("");
  const [manualFaction, setManualFaction] = useState("horde");
  const [manualClass, setManualClass] = useState("warrior");
  const [manualLevel, setManualLevel] = useState(80);
  const [manualRegion, setManualRegion] = useState("eu");
  const [creating, setCreating] = useState(false);

  // Step 2 state
  const [mode, setMode] = useState("completionist");
  const [duration, setDuration] = useState(120);
  const [soloOnly, setSoloOnly] = useState(false);

  // Step 3 state
  const [syncJobId, setSyncJobId] = useState<string | null>(null);
  const [syncProgress, setSyncProgress] = useState({ processed: 0, total: 0, percent: 0 });
  const [syncStatus, setSyncStatus] = useState("queued");

  const isBattleNet = user?.battlenet_connected;

  // Load characters on mount
  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.get<ApiEnvelope<CharacterSummary[]>>("/characters");
        setCharacters(res.data.data);
      } catch { /* empty */ }
      setLoadingChars(false);
    };
    load();
  }, []);

  // Step 3: Poll sync
  useEffect(() => {
    if (step !== 3 || !syncJobId || !selectedCharId) return;
    const interval = setInterval(async () => {
      try {
        const res = await api.get<ApiEnvelope<{
          status: string;
          progress: { processed: number; total: number; percent: number };
        }>>(`/characters/${selectedCharId}/sync/status/${syncJobId}`);
        const data = res.data.data;
        setSyncProgress(data.progress);
        setSyncStatus(data.status);
        if (data.status === "completed" || data.status === "failed") {
          clearInterval(interval);
          if (data.status === "completed") {
            setTimeout(() => router.push("/dashboard"), 1500);
          }
        }
      } catch { /* keep polling */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [step, syncJobId, selectedCharId, router]);

  const handleCreateManual = async () => {
    setCreating(true);
    try {
      const res = await api.post<ApiEnvelope<CharacterSummary>>("/characters", {
        name: manualName,
        realm: manualRealm,
        faction: manualFaction,
        class: manualClass,
        level: manualLevel,
        region: manualRegion,
      });
      setSelectedCharId(res.data.data.id);
      setStep(2);
    } catch { /* error */ }
    setCreating(false);
  };

  const handleStep2Continue = async () => {
    try {
      if (selectedCharId) {
        await api.put(`/characters/${selectedCharId}/preferences`, {
          priority_mode: mode,
          session_duration_minutes: duration,
          solo_only: soloOnly,
        });
      }
    } catch { /* best effort */ }

    // If Battle.net character, go to sync. Otherwise straight to dashboard.
    if (isBattleNet && selectedCharId) {
      try {
        const res = await api.post<ApiEnvelope<{ job_id: string }>>(`/characters/${selectedCharId}/sync`);
        setSyncJobId(res.data.data.job_id);
        setStep(3);
      } catch {
        router.push("/dashboard");
      }
    } else {
      router.push("/dashboard");
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-2xl">
        {/* Progress */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {[1, 2, 3].map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div className={cn(
                "w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold",
                s < step ? "bg-success text-background" :
                s === step ? "bg-primary text-background" :
                "bg-surface border border-border text-text-secondary"
              )}>
                {s < step ? <Check size={16} /> : s}
              </div>
              {s < 3 && <div className={cn("w-12 h-0.5", s < step ? "bg-success" : "bg-border")} />}
            </div>
          ))}
        </div>

        <div className="bg-surface rounded-lg border border-border p-8">
          {/* ─── Step 1: Character Selection ─── */}
          {step === 1 && (
            <>
              <h2 className="text-xl font-bold mb-4">Select Your Character</h2>

              {loadingChars ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="animate-spin text-primary" size={24} />
                </div>
              ) : characters.length > 0 ? (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
                    {characters.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => setSelectedCharId(c.id)}
                        className={cn(
                          "bg-surface-elevated rounded-lg p-4 text-left border-2 transition-colors",
                          selectedCharId === c.id ? "border-primary" : "border-transparent hover:border-border"
                        )}
                      >
                        <div className={cn("w-8 h-8 rounded-full mb-2", c.faction === "horde" ? "bg-horde" : "bg-alliance")} />
                        <p className="font-semibold text-sm">{c.name}</p>
                        <p className="text-xs text-text-secondary">{c.realm}</p>
                        <p className="text-xs text-text-secondary capitalize">{c.class} &middot; Lv{c.level}</p>
                      </button>
                    ))}
                  </div>
                  <button
                    disabled={!selectedCharId}
                    onClick={() => setStep(2)}
                    className="w-full bg-primary hover:bg-primary-hover text-background font-semibold rounded py-2 disabled:opacity-40"
                  >
                    Continue
                  </button>
                </>
              ) : (
                /* Manual character form */
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm text-text-secondary mb-1">Name</label>
                      <input value={manualName} onChange={(e) => setManualName(e.target.value)} className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary" />
                    </div>
                    <div>
                      <label className="block text-sm text-text-secondary mb-1">Realm</label>
                      <input value={manualRealm} onChange={(e) => setManualRealm(e.target.value)} className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary" />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm text-text-secondary mb-1">Faction</label>
                      <div className="flex gap-2">
                        {["horde", "alliance"].map((f) => (
                          <button key={f} onClick={() => setManualFaction(f)} className={cn("flex-1 py-2 rounded capitalize font-semibold text-sm", manualFaction === f ? (f === "horde" ? "bg-horde text-white" : "bg-alliance text-white") : "bg-surface-elevated text-text-secondary border border-border")}>
                            {f}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-text-secondary mb-1">Region</label>
                      <select value={manualRegion} onChange={(e) => setManualRegion(e.target.value)} className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary">
                        <option value="eu">EU</option>
                        <option value="us">US</option>
                        <option value="kr">KR</option>
                        <option value="tw">TW</option>
                      </select>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm text-text-secondary mb-1">Class</label>
                      <select value={manualClass} onChange={(e) => setManualClass(e.target.value)} className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary capitalize">
                        {VALID_CLASSES.map((c) => (
                          <option key={c} value={c} className="capitalize">{c}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-text-secondary mb-1">Level</label>
                      <input type="number" min={1} max={80} value={manualLevel} onChange={(e) => setManualLevel(Number(e.target.value))} className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary" />
                    </div>
                  </div>
                  <button
                    disabled={!manualName || !manualRealm || creating}
                    onClick={handleCreateManual}
                    className="w-full bg-primary hover:bg-primary-hover text-background font-semibold rounded py-2 disabled:opacity-40"
                  >
                    {creating ? "Creating..." : "Create & Continue"}
                  </button>
                </div>
              )}
            </>
          )}

          {/* ─── Step 2: Preferences ─── */}
          {step === 2 && (
            <>
              <h2 className="text-xl font-bold mb-4">Set Your Preferences</h2>

              <p className="text-sm text-text-secondary mb-3">Priority Mode</p>
              <div className="grid grid-cols-2 gap-3 mb-6">
                {MODES.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setMode(m.id)}
                    className={cn(
                      "bg-surface-elevated rounded-lg p-4 text-left border-2 transition-colors",
                      mode === m.id ? "border-primary" : "border-transparent hover:border-border"
                    )}
                  >
                    <m.icon size={20} className={cn("mb-2", mode === m.id ? "text-primary" : "text-text-secondary")} />
                    <p className="font-semibold text-sm">{m.label}</p>
                    <p className="text-xs text-text-secondary mt-1">{m.desc}</p>
                  </button>
                ))}
              </div>

              <p className="text-sm text-text-secondary mb-2">Session Duration</p>
              <div className="mb-1">
                <input
                  type="range"
                  min={0}
                  max={DURATION_MARKS.length - 1}
                  value={DURATION_MARKS.indexOf(duration) >= 0 ? DURATION_MARKS.indexOf(duration) : 3}
                  onChange={(e) => setDuration(DURATION_MARKS[Number(e.target.value)])}
                  className="w-full accent-primary"
                />
              </div>
              <p className="text-sm text-primary font-semibold mb-6">{durationLabel(duration)}</p>

              <div className="flex items-center justify-between bg-surface-elevated rounded-lg p-4 mb-6">
                <div>
                  <p className="font-semibold text-sm">Solo Only</p>
                  <p className="text-xs text-text-secondary">Exclude achievements that require a group</p>
                </div>
                <button
                  onClick={() => setSoloOnly(!soloOnly)}
                  className={cn("w-11 h-6 rounded-full transition-colors relative", soloOnly ? "bg-primary" : "bg-border")}
                >
                  <span className={cn("block w-4 h-4 bg-white rounded-full absolute top-1 transition-transform", soloOnly ? "translate-x-6" : "translate-x-1")} />
                </button>
              </div>

              <button
                onClick={handleStep2Continue}
                className="w-full bg-primary hover:bg-primary-hover text-background font-semibold rounded py-2"
              >
                Continue
              </button>
            </>
          )}

          {/* ─── Step 3: Sync Progress ─── */}
          {step === 3 && (
            <div className="text-center">
              <h2 className="text-xl font-bold mb-4">Syncing Your Achievements</h2>

              <div className="w-full bg-border rounded-full h-3 mb-4 overflow-hidden">
                <div
                  className="bg-primary h-full rounded-full transition-all duration-500"
                  style={{ width: `${syncProgress.percent}%` }}
                />
              </div>

              {syncStatus === "completed" ? (
                <>
                  <Check className="mx-auto text-success mb-2" size={32} />
                  <p className="text-success font-semibold mb-4">Sync complete!</p>
                  <button
                    onClick={() => router.push("/dashboard")}
                    className="bg-primary hover:bg-primary-hover text-background font-semibold rounded px-8 py-2"
                  >
                    Your route is ready
                  </button>
                </>
              ) : syncStatus === "failed" ? (
                <>
                  <p className="text-error mb-4">Sync failed. You can still use the app with manual data.</p>
                  <button
                    onClick={() => router.push("/dashboard")}
                    className="bg-primary hover:bg-primary-hover text-background font-semibold rounded px-8 py-2"
                  >
                    Continue to Dashboard
                  </button>
                </>
              ) : (
                <>
                  <Loader2 className="animate-spin mx-auto text-primary mb-2" size={24} />
                  <p className="text-text-secondary text-sm">
                    Syncing achievement data... {syncProgress.processed} of ~{syncProgress.total || 847} processed
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
