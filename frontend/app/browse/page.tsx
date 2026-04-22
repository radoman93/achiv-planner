"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import api, {
  type ApiEnvelope,
  type AchievementSummary,
  type AchievementDetail,
} from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import {
  Search,
  X,
  Filter,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from "lucide-react";

const EXPANSIONS = [
  "Classic",
  "The Burning Crusade",
  "Wrath of the Lich King",
  "Cataclysm",
  "Mists of Pandaria",
  "Warlords of Draenor",
  "Legion",
  "Battle for Azeroth",
  "Shadowlands",
  "Dragonflight",
  "The War Within",
];

const CONF_COLOR: Record<string, string> = {
  verified: "#8FBF7A",
  high: "#D4A04A",
  medium: "#C88A5A",
  low: "#8A6B6B",
  research_required: "#C86464",
};

const CONF_LABEL: Record<string, string> = {
  verified: "Verified",
  high: "Trusted",
  medium: "Community",
  low: "Unverified",
  research_required: "Research",
};

export default function BrowsePage() {
  useAuth();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<string | null>(null);
  const [expansionFilter, setExpansionFilter] = useState<string[]>([]);
  const [isSeasonal, setIsSeasonal] = useState<boolean | undefined>(undefined);
  const [soloOnly, setSoloOnly] = useState<boolean | undefined>(undefined);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, expansionFilter, isSeasonal, soloOnly]);

  const { data, isLoading } = useQuery({
    queryKey: [
      "achievements",
      "browse",
      debouncedSearch,
      page,
      expansionFilter,
      isSeasonal,
      soloOnly,
    ],
    queryFn: async () => {
      if (debouncedSearch.length >= 2) {
        const res = await api.get<
          ApiEnvelope<{ achievements: AchievementSummary[]; total: number }>
        >(`/achievements/search?q=${encodeURIComponent(debouncedSearch)}&limit=50`);
        return { ...res.data.data, page: 1, per_page: 50, total_pages: 1 };
      }
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", "24");
      if (expansionFilter.length === 1) params.set("expansion", expansionFilter[0]);
      if (isSeasonal !== undefined) params.set("is_seasonal", String(isSeasonal));
      if (soloOnly === true) params.set("requires_group", "false");
      const res = await api.get<
        ApiEnvelope<{
          achievements: AchievementSummary[];
          total: number;
          page: number;
          per_page: number;
          total_pages: number;
        }>
      >(`/achievements?${params.toString()}`);
      return res.data.data;
    },
  });

  const { data: detail, isLoading: detailLoading } = useQuery<AchievementDetail | null>({
    queryKey: ["achievement", "detail", selectedDetail],
    queryFn: async () => {
      if (!selectedDetail) return null;
      const res = await api.get<ApiEnvelope<AchievementDetail>>(
        `/achievements/${selectedDetail}`,
      );
      return res.data.data;
    },
    enabled: !!selectedDetail,
  });

  const clearFilters = () => {
    setExpansionFilter([]);
    setIsSeasonal(undefined);
    setSoloOnly(undefined);
  };

  const toggleExpansion = (exp: string) => {
    setExpansionFilter((prev) =>
      prev.includes(exp) ? prev.filter((e) => e !== exp) : [...prev, exp],
    );
  };

  return (
    <div className="fade-in relative">
      {/* Page header */}
      <div className="mb-7">
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-1.5 flex items-center gap-2">
          <span
            className="inline-block w-[5px] h-[5px]"
            style={{ transform: "rotate(45deg)", background: "var(--gold-2)" }}
          />
          Library
        </div>
        <h1 className="font-display text-[28px] font-semibold tracking-tight m-0 mb-1.5">
          Browse achievements
        </h1>
        <p className="text-[13px] text-fg-3 m-0 max-w-[68ch]">
          Every achievement Blizzard exposes, indexed, scored, and cross-referenced with Wowhead
          & community sources.
        </p>
      </div>

      {/* Filter bar */}
      <div
        className="flex items-center gap-2 mb-5 p-3"
        style={{
          background: "var(--bg-1)",
          border: "1px solid var(--border-1)",
          borderRadius: "var(--r-md)",
        }}
      >
        <div className="relative flex-1 max-w-md">
          <Search
            size={14}
            className="absolute top-1/2 -translate-y-1/2"
            style={{ left: 10, color: "var(--fg-3)" }}
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search achievements…"
            className="w-full"
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border-2)",
              borderRadius: "var(--r-md)",
              padding: "8px 32px 8px 32px",
              fontSize: 13,
              color: "var(--fg-1)",
              outline: "none",
            }}
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-fg-3 hover:text-fg-1"
            >
              <X size={14} />
            </button>
          )}
        </div>

        <button
          onClick={() => setFiltersOpen((v) => !v)}
          className={cn("btn", filtersOpen && "btn-primary")}
          style={{ padding: "7px 12px", fontSize: 12 }}
        >
          <Filter size={12} /> Filters
        </button>

        {(expansionFilter.length > 0 || isSeasonal !== undefined || soloOnly !== undefined) && (
          <button
            onClick={clearFilters}
            className="font-mono text-[11px] text-fg-3 hover:text-gold-1 uppercase tracking-[0.08em]"
          >
            Clear
          </button>
        )}
      </div>

      {/* Filter panel */}
      {filtersOpen && (
        <div
          className="p-5 mb-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-3"
          style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--r-md)",
          }}
        >
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-fg-3 mb-2">
              Expansion
            </div>
            <div className="max-h-40 overflow-y-auto grid gap-1.5">
              {EXPANSIONS.map((exp) => (
                <label
                  key={exp}
                  className="flex items-center gap-2 text-[12px] cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={expansionFilter.includes(exp)}
                    onChange={() => toggleExpansion(exp)}
                    className="accent-[var(--gold-1)]"
                  />
                  <span>{exp}</span>
                </label>
              ))}
            </div>
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-fg-3 mb-2">
              Type
            </div>
            <label className="flex items-center gap-2 text-[12px] cursor-pointer mb-2">
              <input
                type="checkbox"
                checked={isSeasonal === true}
                onChange={() =>
                  setIsSeasonal(isSeasonal === true ? undefined : true)
                }
                className="accent-[var(--gold-1)]"
              />
              Seasonal only
            </label>
            <label className="flex items-center gap-2 text-[12px] cursor-pointer">
              <input
                type="checkbox"
                checked={soloOnly === true}
                onChange={() => setSoloOnly(soloOnly === true ? undefined : true)}
                className="accent-[var(--gold-1)]"
              />
              Solo-able only
            </label>
          </div>
        </div>
      )}

      {/* Table card */}
      <div
        style={{
          background: "var(--bg-1)",
          border: "1px solid var(--border-1)",
          borderRadius: "var(--r-md)",
          overflow: "hidden",
        }}
      >
        <div
          className="grid px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.12em] text-fg-3"
          style={{
            borderBottom: "1px solid var(--border-1)",
            gridTemplateColumns: "minmax(0, 1fr) 120px 100px 60px",
          }}
        >
          <div>Achievement</div>
          <div>Zone</div>
          <div>Confidence</div>
          <div className="text-right">Pts</div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="animate-spin text-gold-1" size={24} />
          </div>
        ) : data && data.achievements.length > 0 ? (
          data.achievements.map((ach) => (
            <AchievementRow
              key={ach.id}
              ach={ach}
              onClick={() => setSelectedDetail(ach.id)}
            />
          ))
        ) : (
          <div className="py-10 text-center text-fg-3">
            <p className="mb-2">No results found</p>
            <button
              onClick={clearFilters}
              className="text-sm text-gold-1 hover:underline"
            >
              Clear all filters
            </button>
          </div>
        )}
      </div>

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-6">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="btn"
            style={{ padding: "6px 10px", fontSize: 12, opacity: page <= 1 ? 0.3 : 1 }}
          >
            <ChevronLeft size={14} />
          </button>
          <span className="font-mono text-[12px] text-fg-3">
            Page {data.page} of {data.total_pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(data.total_pages, p + 1))}
            disabled={page >= data.total_pages}
            className="btn"
            style={{
              padding: "6px 10px",
              fontSize: 12,
              opacity: page >= data.total_pages ? 0.3 : 1,
            }}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      )}

      {/* Detail drawer */}
      {selectedDetail && (
        <DetailDrawer
          detail={detail}
          loading={detailLoading}
          onClose={() => setSelectedDetail(null)}
        />
      )}
    </div>
  );
}

function AchievementRow({
  ach,
  onClick,
}: {
  ach: AchievementSummary;
  onClick: () => void;
}) {
  const confColor = CONF_COLOR[ach.confidence_tier] ?? "#8A6B6B";
  const confLabel = CONF_LABEL[ach.confidence_tier] ?? "—";
  return (
    <button
      onClick={onClick}
      className="grid items-center gap-3 px-4 py-3 w-full text-left border-t hover:bg-bg-2 transition-colors"
      style={{
        borderColor: "var(--border-1)",
        gridTemplateColumns: "minmax(0, 1fr) 120px 100px 60px",
      }}
    >
      <div className="min-w-0 flex items-center gap-3">
        <span
          className="conf-dot shrink-0"
          style={{ background: confColor }}
          title={confLabel}
        />
        <div className="min-w-0">
          <div className="text-[13px] font-medium truncate">{ach.name}</div>
          {ach.category && (
            <div className="font-mono text-[11px] text-fg-3 truncate">
              {ach.category}
              {ach.is_seasonal && (
                <span className="ml-2 text-ember">· Seasonal</span>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="font-mono text-[11px] text-fg-3 truncate">
        {ach.zone_name ?? "—"}
      </div>
      <div className="font-mono text-[11px]" style={{ color: confColor }}>
        {confLabel}
      </div>
      <div className="text-right font-display text-[14px] text-gold-1 font-semibold">
        {ach.points}
      </div>
    </button>
  );
}

function DetailDrawer({
  detail,
  loading,
  onClose,
}: {
  detail: AchievementDetail | null | undefined;
  loading: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <>
      <div
        className="fixed inset-0 z-40"
        style={{ background: "rgba(0, 0, 0, 0.6)" }}
        onClick={onClose}
      />
      <div
        className="fixed inset-y-0 right-0 w-full sm:w-[440px] z-50 overflow-y-auto p-6"
        style={{
          background: "var(--bg-1)",
          borderLeft: "1px solid var(--border-2)",
        }}
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-fg-3 hover:text-fg-1"
        >
          <X size={20} />
        </button>

        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="animate-spin text-gold-1" size={24} />
          </div>
        ) : detail ? (
          <div className="grid gap-6">
            <div>
              <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-gold-2 mb-2">
                Achievement
              </div>
              <h2 className="font-display text-[22px] font-semibold m-0 mb-2 pr-8">
                {detail.name}
              </h2>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-display text-[16px] text-gold-1 font-semibold">
                  {detail.points} pts
                </span>
                <span
                  className="font-mono text-[10px] uppercase tracking-[0.08em] px-2 py-0.5 rounded"
                  style={{
                    background: "var(--bg-3)",
                    color: CONF_COLOR[detail.confidence_tier] ?? "var(--fg-3)",
                    border: `1px solid ${
                      CONF_COLOR[detail.confidence_tier] ?? "var(--border-2)"
                    }`,
                  }}
                >
                  {CONF_LABEL[detail.confidence_tier] ?? "—"}
                </span>
              </div>
            </div>

            {detail.description && (
              <p className="text-[13px] text-fg-2 leading-[1.6] m-0">
                {detail.description}
              </p>
            )}

            <div className="flex flex-wrap gap-2 text-xs">
              {detail.category && <Chip>{detail.category}</Chip>}
              {detail.expansion && <Chip>{detail.expansion}</Chip>}
              {detail.zone && <Chip>{detail.zone.name}</Chip>}
              {detail.is_seasonal && (
                <Chip
                  style={{
                    background: "rgba(224, 138, 60, 0.1)",
                    color: "var(--ember)",
                    border: "1px solid rgba(224, 138, 60, 0.3)",
                  }}
                >
                  Seasonal
                </Chip>
              )}
              {detail.requires_group && (
                <Chip
                  style={{
                    background: "rgba(74, 120, 196, 0.1)",
                    color: "var(--alliance)",
                    border: "1px solid rgba(74, 120, 196, 0.3)",
                  }}
                >
                  Group
                </Chip>
              )}
            </div>

            {detail.guide?.steps && detail.guide.steps.length > 0 && (
              <div>
                <h3 className="font-mono text-[11px] uppercase tracking-[0.12em] text-fg-3 m-0 mb-3">
                  Guide Steps
                </h3>
                <ol className="grid gap-2 m-0 pl-0 list-none">
                  {detail.guide.steps.map((s, i) => (
                    <li
                      key={i}
                      className="text-[13px] text-fg-2 flex gap-3"
                    >
                      <span className="font-mono text-xs text-gold-1 shrink-0">
                        {i + 1}.
                      </span>
                      <span>{s.label || s.description}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {detail.comments && detail.comments.length > 0 && (
              <div>
                <h3 className="font-mono text-[11px] uppercase tracking-[0.12em] text-fg-3 m-0 mb-3">
                  Community Tips
                </h3>
                <div className="grid gap-2">
                  {detail.comments.slice(0, 3).map((c, i) => (
                    <div
                      key={i}
                      className="p-3 text-[12px] text-fg-2"
                      style={{
                        background: "var(--bg-2)",
                        border: "1px solid var(--border-1)",
                        borderRadius: "var(--r-md)",
                      }}
                    >
                      {c.text}
                      {c.author && (
                        <p className="text-[10px] mt-1 text-fg-3 m-0">— {c.author}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <a
              href={`https://www.wowhead.com/achievement=${detail.blizzard_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm text-gold-1 hover:underline"
            >
              View on Wowhead <ExternalLink size={12} />
            </a>
          </div>
        ) : null}
      </div>
    </>
  );
}

function Chip({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <span
      className="px-2 py-1 text-[11px] font-mono uppercase tracking-[0.05em]"
      style={{
        background: "var(--bg-2)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--r-sm)",
        color: "var(--fg-2)",
        ...style,
      }}
    >
      {children}
    </span>
  );
}
