"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, {
  type ApiEnvelope,
  type CharacterSummary,
} from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { cn, formatMinutes } from "@/lib/utils";
import {
  Link2,
  LogOut,
  RefreshCw,
  Download,
  Shield,
  Loader2,
  Check,
} from "lucide-react";

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncDone, setSyncDone] = useState<string | null>(null);

  const { data: characters } = useQuery<CharacterSummary[]>({
    queryKey: ["characters"],
    queryFn: async () => {
      const res = await api.get<ApiEnvelope<CharacterSummary[]>>("/characters");
      return res.data.data;
    },
  });

  const handleSync = async (id: string) => {
    setSyncError(null);
    setSyncDone(null);
    setSyncingId(id);
    try {
      const jobRes = await api.post<ApiEnvelope<{ job_id: string }>>(
        `/characters/${id}/sync`,
      );
      const jobId = jobRes.data.data.job_id;
      while (true) {
        const statusRes = await api.get<
          ApiEnvelope<{ status: string; progress: { percent: number } }>
        >(`/characters/${id}/sync/status/${jobId}`);
        if (statusRes.data.data.status === "completed") break;
        if (statusRes.data.data.status === "failed") {
          setSyncError("Sync failed. Try again.");
          setSyncingId(null);
          return;
        }
        await new Promise((r) => setTimeout(r, 2500));
      }
      qc.invalidateQueries({ queryKey: ["characters"] });
      setSyncDone(id);
      setSyncingId(null);
    } catch {
      setSyncError("Could not start sync.");
      setSyncingId(null);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  return (
    <div className="fade-in">
      {/* Page header */}
      <div className="mb-7">
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-1.5 flex items-center gap-2">
          <span
            className="inline-block w-[5px] h-[5px]"
            style={{ transform: "rotate(45deg)", background: "var(--gold-2)" }}
          />
          Characters & Account
        </div>
        <h1 className="font-display text-[28px] font-semibold tracking-tight m-0 mb-1.5">
          Your roster
        </h1>
        <p className="text-[13px] text-fg-3 m-0 max-w-[68ch]">
          Connect Battle.net once; we pull the whole roster automatically. Pick which character
          the engine should plan around.
        </p>
      </div>

      {/* Split layout */}
      <div className="grid gap-6 lg:grid-cols-[1fr_360px] items-start">
        {/* Left column */}
        <div className="grid gap-5">
          {/* Battle.net connection card */}
          <div
            className="p-6"
            style={{
              background:
                "radial-gradient(500px 200px at 0% 0%, rgba(127, 168, 212, 0.06), transparent 60%), var(--bg-1)",
              border: "1px solid var(--border-1)",
              borderRadius: "var(--r-lg)",
            }}
          >
            <div className="flex items-center gap-4 mb-5">
              <div
                className="w-11 h-11 rounded-lg grid place-items-center"
                style={{
                  background: "linear-gradient(135deg, #1F3B6A, #0d1f3a)",
                  color: "#7FA8D4",
                  border: "1px solid #2d4d80",
                }}
              >
                <Link2 size={18} />
              </div>
              <div className="flex-1">
                <div className="font-display text-[18px] font-semibold">Battle.net</div>
                <div className="font-mono text-[12px] text-fg-3 mt-0.5">
                  {user?.battlenet_connected
                    ? `Connected · ${user.battlenet_region?.toUpperCase() ?? "EU"}`
                    : "Not connected"}
                </div>
              </div>
              {user?.battlenet_connected ? (
                <span
                  className="font-mono text-[10px] uppercase tracking-[0.1em] px-2.5 py-1 rounded-full"
                  style={{
                    background: "rgba(143, 191, 122, 0.1)",
                    color: "var(--good)",
                    border: "1px solid rgba(143, 191, 122, 0.3)",
                  }}
                >
                  <Check size={10} className="inline -mt-0.5 mr-1" /> Linked
                </span>
              ) : (
                <button
                  className="btn btn-primary"
                  onClick={() => router.push("/onboarding")}
                >
                  <Link2 size={13} /> Connect
                </button>
              )}
            </div>
          </div>

          {/* Character roster */}
          <div
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
                Characters ({characters?.length ?? 0})
              </h3>
            </div>
            {syncError && (
              <div
                className="px-[18px] py-3 text-sm"
                style={{
                  background: "rgba(200, 100, 100, 0.06)",
                  color: "var(--bad)",
                  borderBottom: "1px solid var(--border-1)",
                }}
              >
                {syncError}
              </div>
            )}
            {characters && characters.length > 0 ? (
              characters.map((c, i) => (
                <CharacterRow
                  key={c.id}
                  char={c}
                  primary={i === 0}
                  syncing={syncingId === c.id}
                  recentlySynced={syncDone === c.id}
                  onSync={() => handleSync(c.id)}
                />
              ))
            ) : (
              <div className="px-[18px] py-10 text-center text-fg-3 text-sm">
                No characters synced yet.{" "}
                <button
                  className="text-gold-1 hover:underline"
                  onClick={() => router.push("/onboarding")}
                >
                  Connect Battle.net
                </button>
              </div>
            )}
          </div>

          {/* Account */}
          <div
            style={{
              background: "var(--bg-1)",
              border: "1px solid var(--border-1)",
              borderRadius: "var(--r-lg)",
              overflow: "hidden",
            }}
          >
            <div
              className="px-[18px] py-3.5"
              style={{ borderBottom: "1px solid var(--border-1)" }}
            >
              <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-fg-3 m-0">
                Account
              </h3>
            </div>
            <div className="p-5 grid gap-4 sm:grid-cols-2">
              <KV label="Email" value={user?.email ?? "—"} />
              <KV label="Tier" value={user?.tier ?? "—"} capitalize />
              <KV
                label="Priority mode"
                value={user?.priority_mode?.replace(/_/g, " ") ?? "—"}
                capitalize
              />
              <KV
                label="Session duration"
                value={
                  user?.session_duration_minutes
                    ? formatMinutes(user.session_duration_minutes)
                    : "—"
                }
              />
            </div>
            <div
              className="px-5 py-4 flex justify-end"
              style={{ borderTop: "1px solid var(--border-1)" }}
            >
              <button
                onClick={handleLogout}
                className="btn"
                style={{
                  background: "rgba(200, 100, 100, 0.08)",
                  color: "var(--bad)",
                  borderColor: "rgba(200, 100, 100, 0.3)",
                }}
              >
                <LogOut size={13} /> Sign out
              </button>
            </div>
          </div>
        </div>

        {/* Right rail */}
        <div className="grid gap-5 lg:sticky lg:top-5">
          <InfoCard
            title="How sync works"
            body="We call Battle.net every time you tap Re-sync. Read-only. We store your achievement log, reputations, and roster metadata — nothing else."
          />
          <div
            style={{
              background: "var(--bg-1)",
              border: "1px solid var(--border-1)",
              borderRadius: "var(--r-lg)",
              overflow: "hidden",
            }}
          >
            <div
              className="px-[18px] py-3.5 flex items-center gap-2"
              style={{ borderBottom: "1px solid var(--border-1)" }}
            >
              <Shield size={12} className="text-gold-2" />
              <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-fg-3 m-0">
                Data residency
              </h3>
            </div>
            <div className="p-5 grid gap-3">
              <Residency
                k="Region"
                v={user?.battlenet_region?.toUpperCase() ?? "—"}
              />
              <Residency k="Retention" v="90 days after disconnect" />
              <Residency k="Scopes" v="read:achievements · profile" />
              <Residency k="Token rotation" v="Every 24h" />
            </div>
          </div>

          <div
            style={{
              background: "var(--bg-1)",
              border: "1px solid var(--border-1)",
              borderRadius: "var(--r-lg)",
              overflow: "hidden",
            }}
          >
            <div
              className="px-[18px] py-3.5"
              style={{ borderBottom: "1px solid var(--border-1)" }}
            >
              <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-fg-3 m-0">
                Quick actions
              </h3>
            </div>
            <div className="grid">
              <ActionRow
                icon={<RefreshCw size={14} />}
                label="Re-sync all characters"
                onClick={() => characters?.forEach((c) => handleSync(c.id))}
              />
              <ActionRow
                icon={<Download size={14} />}
                label="Export your data as JSON"
                onClick={() => {}}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CharacterRow({
  char,
  primary,
  syncing,
  recentlySynced,
  onSync,
}: {
  char: CharacterSummary;
  primary: boolean;
  syncing: boolean;
  recentlySynced: boolean;
  onSync: () => void;
}) {
  const isHorde = char.faction?.toLowerCase() === "horde";
  return (
    <div
      className={cn(
        "grid items-center gap-4 px-4 py-4",
        primary && "",
      )}
      style={{
        gridTemplateColumns: "auto 1fr auto auto",
        borderTop: primary ? undefined : "1px solid var(--border-1)",
        background: primary
          ? "linear-gradient(90deg, var(--gold-glow), transparent 40%)"
          : undefined,
        borderLeft: primary ? "2px solid var(--gold-2)" : undefined,
        paddingLeft: primary ? 14 : undefined,
      }}
    >
      <div
        className="w-12 h-12 rounded-lg grid place-items-center font-display font-semibold text-lg"
        style={{
          background: isHorde
            ? "linear-gradient(135deg, var(--horde-dim), #3d1919)"
            : "linear-gradient(135deg, var(--alliance-dim), #152447)",
          color: isHorde ? "#F5B4B4" : "#B4CCF5",
          border: `1px solid ${isHorde ? "var(--horde)" : "var(--alliance)"}`,
        }}
      >
        {char.name.slice(0, 1).toUpperCase()}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[14px] font-medium">{char.name}</span>
          {primary && (
            <span
              className="font-mono text-[9px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded"
              style={{
                background: "var(--gold-4)",
                color: "var(--gold-1)",
                border: "1px solid var(--gold-3)",
              }}
            >
              Primary
            </span>
          )}
        </div>
        <div className="font-mono text-[11px] text-fg-3 mt-0.5 truncate">
          {char.realm}
          {char.class ? ` · ${char.class}` : ""}
          {char.level ? ` · lvl ${char.level}` : ""}
        </div>
      </div>
      <div className="text-right font-mono text-[12px]">
        <div className="text-gold-1 font-semibold">{char.achievement_completion_pct}%</div>
        <div className="text-[9px] text-fg-4 uppercase tracking-[0.1em] mt-0.5">complete</div>
      </div>
      <button
        className="btn"
        onClick={onSync}
        disabled={syncing}
        style={{ padding: "6px 10px", fontSize: 11 }}
      >
        {syncing ? (
          <Loader2 size={12} className="animate-spin" />
        ) : recentlySynced ? (
          <Check size={12} className="text-good" />
        ) : (
          <RefreshCw size={12} />
        )}
        {syncing ? "Syncing" : recentlySynced ? "Synced" : "Sync"}
      </button>
    </div>
  );
}

function InfoCard({ title, body }: { title: string; body: string }) {
  return (
    <div
      className="p-5"
      style={{
        background:
          "linear-gradient(160deg, rgba(127, 168, 212, 0.06), var(--bg-1))",
        border: "1px solid rgba(127, 168, 212, 0.2)",
        borderRadius: "var(--r-lg)",
      }}
    >
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-info mb-2">
        {title}
      </div>
      <p className="text-[13px] text-fg-2 leading-[1.55] m-0">{body}</p>
    </div>
  );
}

function Residency({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between text-[12px]">
      <span className="font-mono text-fg-3 uppercase tracking-[0.1em]">{k}</span>
      <span className="text-fg-2">{v}</span>
    </div>
  );
}

function ActionRow({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-3 px-4 py-3 text-left text-sm hover:bg-bg-2 transition-colors border-t first:border-t-0 border-border-1"
    >
      <span className="text-gold-2">{icon}</span>
      <span className="flex-1">{label}</span>
    </button>
  );
}

function KV({
  label,
  value,
  capitalize,
}: {
  label: string;
  value: string;
  capitalize?: boolean;
}) {
  return (
    <div>
      <div className="font-mono text-[10px] text-fg-3 uppercase tracking-[0.14em] mb-1">
        {label}
      </div>
      <div className={cn("text-sm", capitalize && "capitalize")}>{value}</div>
    </div>
  );
}
