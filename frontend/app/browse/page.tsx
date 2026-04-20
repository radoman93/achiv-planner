"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import api, { type ApiEnvelope, type AchievementSummary, type AchievementDetail } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { cn, TIER_COLORS } from "@/lib/utils";
import { Search, X, Filter, ExternalLink, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

const EXPANSIONS = [
  "Classic", "The Burning Crusade", "Wrath of the Lich King", "Cataclysm",
  "Mists of Pandaria", "Warlords of Draenor", "Legion", "Battle for Azeroth",
  "Shadowlands", "Dragonflight", "The War Within",
];

export default function BrowsePage() {
  useAuth();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<string | null>(null);

  // Filters
  const [expansionFilter, setExpansionFilter] = useState<string[]>([]);
  const [isSeasonal, setIsSeasonal] = useState<boolean | undefined>(undefined);
  const [soloOnly, setSoloOnly] = useState<boolean | undefined>(undefined);
  const [minPoints, setMinPoints] = useState<number | undefined>(undefined);
  const [maxPoints, setMaxPoints] = useState<number | undefined>(undefined);

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset page on filter change
  useEffect(() => { setPage(1); }, [debouncedSearch, expansionFilter, isSeasonal, soloOnly, minPoints, maxPoints]);

  // Main query — search or browse
  const { data, isLoading } = useQuery({
    queryKey: ["achievements", "browse", debouncedSearch, page, expansionFilter, isSeasonal, soloOnly, minPoints, maxPoints],
    queryFn: async () => {
      if (debouncedSearch.length >= 2) {
        const res = await api.get<ApiEnvelope<{ achievements: AchievementSummary[]; total: number }>>(
          `/achievements/search?q=${encodeURIComponent(debouncedSearch)}&limit=50`,
        );
        return { ...res.data.data, page: 1, per_page: 50, total_pages: 1 };
      }
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", "21");
      if (expansionFilter.length === 1) params.set("expansion", expansionFilter[0]);
      if (isSeasonal !== undefined) params.set("is_seasonal", String(isSeasonal));
      if (soloOnly === true) params.set("requires_group", "false");
      if (minPoints !== undefined) params.set("min_points", String(minPoints));
      if (maxPoints !== undefined) params.set("max_points", String(maxPoints));
      const res = await api.get<ApiEnvelope<{ achievements: AchievementSummary[]; total: number; page: number; per_page: number; total_pages: number }>>(
        `/achievements?${params.toString()}`,
      );
      return res.data.data;
    },
  });

  // Detail query
  const { data: detail, isLoading: detailLoading } = useQuery<AchievementDetail | null>({
    queryKey: ["achievement", "detail", selectedDetail],
    queryFn: async () => {
      if (!selectedDetail) return null;
      const res = await api.get<ApiEnvelope<AchievementDetail>>(`/achievements/${selectedDetail}`);
      return res.data.data;
    },
    enabled: !!selectedDetail,
  });

  const clearFilters = () => {
    setExpansionFilter([]);
    setIsSeasonal(undefined);
    setSoloOnly(undefined);
    setMinPoints(undefined);
    setMaxPoints(undefined);
  };

  const toggleExpansion = (exp: string) => {
    setExpansionFilter((prev) =>
      prev.includes(exp) ? prev.filter((e) => e !== exp) : [...prev, exp],
    );
  };

  return (
    <div className="relative">
      <h1 className="text-2xl font-bold mb-6">Achievement Browser</h1>

      {/* Search bar */}
      <div className="relative mb-6">
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search achievements..."
          className="w-full bg-surface border border-border rounded-lg pl-10 pr-4 py-3 text-text-primary focus:outline-none focus:border-primary"
        />
        {search && (
          <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary">
            <X size={16} />
          </button>
        )}
      </div>

      <div className="flex gap-6">
        {/* Filter panel — desktop sidebar */}
        <aside className={cn("hidden lg:block w-56 shrink-0")}>
          <FilterPanel
            expansionFilter={expansionFilter}
            toggleExpansion={toggleExpansion}
            isSeasonal={isSeasonal}
            setIsSeasonal={setIsSeasonal}
            soloOnly={soloOnly}
            setSoloOnly={setSoloOnly}
            clearFilters={clearFilters}
          />
        </aside>

        {/* Mobile filter button */}
        <button
          onClick={() => setFiltersOpen(true)}
          className="lg:hidden fixed bottom-20 right-4 z-30 bg-primary text-background rounded-full p-3 shadow-lg"
        >
          <Filter size={20} />
        </button>

        {/* Mobile filter sheet */}
        {filtersOpen && (
          <div className="lg:hidden fixed inset-0 z-50 flex flex-col">
            <div className="flex-1 bg-black/50" onClick={() => setFiltersOpen(false)} />
            <div className="bg-surface border-t border-border rounded-t-xl p-6 max-h-[70vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold">Filters</h3>
                <button onClick={() => setFiltersOpen(false)}><X size={20} /></button>
              </div>
              <FilterPanel
                expansionFilter={expansionFilter}
                toggleExpansion={toggleExpansion}
                isSeasonal={isSeasonal}
                setIsSeasonal={setIsSeasonal}
                soloOnly={soloOnly}
                setSoloOnly={setSoloOnly}
                clearFilters={clearFilters}
              />
            </div>
          </div>
        )}

        {/* Achievement grid */}
        <div className="flex-1 min-w-0">
          {isLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="animate-spin text-primary" size={24} /></div>
          ) : data && data.achievements.length > 0 ? (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                {data.achievements.map((ach) => (
                  <button
                    key={ach.id}
                    onClick={() => setSelectedDetail(ach.id)}
                    className="bg-surface rounded-lg border border-border p-4 text-left hover:border-primary transition-colors"
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded bg-surface-elevated flex items-center justify-center text-xs font-mono text-primary shrink-0">
                        {ach.points}
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-primary truncate">{ach.name}</p>
                        <p className="text-xs text-text-secondary truncate">{ach.category}</p>
                        <div className="flex items-center gap-2 mt-1">
                          {ach.zone_name && <span className="text-[10px] text-text-secondary">{ach.zone_name}</span>}
                          <span className={cn("w-1.5 h-1.5 rounded-full", TIER_COLORS[ach.confidence_tier])} />
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              {/* Pagination */}
              {data.total_pages > 1 && (
                <div className="flex items-center justify-center gap-4 mt-6">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="p-2 rounded bg-surface-elevated disabled:opacity-30"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="text-sm text-text-secondary">
                    Page {data.page} of {data.total_pages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(data.total_pages, p + 1))}
                    disabled={page >= data.total_pages}
                    className="p-2 rounded bg-surface-elevated disabled:opacity-30"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-12">
              <p className="text-text-secondary mb-2">No results found</p>
              <button onClick={clearFilters} className="text-sm text-primary hover:underline">Clear all filters</button>
            </div>
          )}
        </div>
      </div>

      {/* Detail drawer */}
      {selectedDetail && (
        <DetailDrawer detail={detail} loading={detailLoading} onClose={() => setSelectedDetail(null)} />
      )}
    </div>
  );
}

// ─── Filter Panel ──────────────────────────────────────────

function FilterPanel({
  expansionFilter, toggleExpansion, isSeasonal, setIsSeasonal, soloOnly, setSoloOnly, clearFilters,
}: {
  expansionFilter: string[];
  toggleExpansion: (exp: string) => void;
  isSeasonal: boolean | undefined;
  setIsSeasonal: (v: boolean | undefined) => void;
  soloOnly: boolean | undefined;
  setSoloOnly: (v: boolean | undefined) => void;
  clearFilters: () => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold text-text-secondary mb-2">Expansion</p>
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {EXPANSIONS.map((exp) => (
            <label key={exp} className="flex items-center gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={expansionFilter.includes(exp)}
                onChange={() => toggleExpansion(exp)}
                className="accent-primary"
              />
              <span className="text-text-primary">{exp}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold text-text-secondary mb-2">Toggles</p>
        <label className="flex items-center gap-2 text-xs cursor-pointer mb-2">
          <input type="checkbox" checked={isSeasonal === true} onChange={() => setIsSeasonal(isSeasonal === true ? undefined : true)} className="accent-primary" />
          Seasonal only
        </label>
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input type="checkbox" checked={soloOnly === true} onChange={() => setSoloOnly(soloOnly === true ? undefined : true)} className="accent-primary" />
          Solo only
        </label>
      </div>

      <button onClick={clearFilters} className="text-xs text-primary hover:underline">Clear all filters</button>
    </div>
  );
}

// ─── Detail Drawer ──────────────────────────────────────────

function DetailDrawer({ detail, loading, onClose }: { detail: AchievementDetail | null | undefined; loading: boolean; onClose: () => void }) {
  // ESC to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />

      {/* Drawer — side on desktop, full-screen on mobile */}
      <div className="fixed inset-y-0 right-0 w-full sm:w-[420px] bg-surface border-l border-border z-50 overflow-y-auto p-6">
        <button onClick={onClose} className="absolute top-4 right-4 text-text-secondary hover:text-text-primary">
          <X size={20} />
        </button>

        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="animate-spin text-primary" size={24} /></div>
        ) : detail ? (
          <div className="space-y-6">
            {/* Header */}
            <div>
              <h2 className="text-lg font-bold text-primary pr-8">{detail.name}</h2>
              <div className="flex items-center gap-2 mt-1">
                <span className="font-mono text-sm text-primary">{detail.points} pts</span>
                <span className={cn("text-xs px-2 py-0.5 rounded capitalize", TIER_COLORS[detail.confidence_tier], "text-background")}>
                  {detail.confidence_tier.replace("_", " ")}
                </span>
              </div>
            </div>

            {/* Description */}
            {detail.description && (
              <p className="text-sm text-text-secondary">{detail.description}</p>
            )}

            {/* Meta */}
            <div className="flex flex-wrap gap-2 text-xs">
              {detail.category && <span className="bg-surface-elevated px-2 py-1 rounded">{detail.category}</span>}
              {detail.expansion && <span className="bg-surface-elevated px-2 py-1 rounded">{detail.expansion}</span>}
              {detail.zone && <span className="bg-surface-elevated px-2 py-1 rounded">{detail.zone.name}</span>}
              {detail.is_seasonal && <span className="bg-warning/20 text-warning px-2 py-1 rounded">Seasonal</span>}
              {detail.requires_group && <span className="bg-alliance/20 text-alliance px-2 py-1 rounded">Group</span>}
            </div>

            {/* Guide steps */}
            {detail.guide && detail.guide.steps && detail.guide.steps.length > 0 ? (
              <div>
                <h3 className="text-sm font-semibold mb-2">Guide Steps</h3>
                <ol className="space-y-2">
                  {detail.guide.steps.map((s, i) => (
                    <li key={i} className="text-sm text-text-secondary flex gap-2">
                      <span className="text-xs font-mono text-primary shrink-0">{i + 1}.</span>
                      <span>{s.label || s.description}</span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <div>
                <p className="text-sm text-text-secondary">No guide available.</p>
                <a
                  href={`https://www.wowhead.com/achievement=${detail.blizzard_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-primary hover:underline inline-flex items-center gap-1 mt-1"
                >
                  View on Wowhead <ExternalLink size={12} />
                </a>
              </div>
            )}

            {/* Community tips */}
            {detail.comments && detail.comments.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2">Community Tips</h3>
                <div className="space-y-2">
                  {detail.comments.slice(0, 3).map((c, i) => (
                    <div key={i} className="bg-surface-elevated rounded p-3 text-xs text-text-secondary">
                      {c.text}
                      {c.author && <p className="text-[10px] mt-1 text-text-secondary/60">— {c.author}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Criteria */}
            {detail.criteria && detail.criteria.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2">Criteria</h3>
                <ul className="space-y-1">
                  {detail.criteria.map((cr) => (
                    <li key={cr.id} className="text-xs text-text-secondary">
                      {cr.description}
                      {cr.required_amount && cr.required_amount > 1 && <span className="text-primary ml-1">x{cr.required_amount}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Dependencies */}
            {(detail.requires.length > 0 || detail.required_by.length > 0) && (
              <div>
                {detail.requires.length > 0 && (
                  <>
                    <h3 className="text-sm font-semibold mb-1">Requires</h3>
                    <ul className="space-y-1 mb-3">
                      {detail.requires.map((d) => (
                        <li key={d.id} className="text-xs text-text-secondary">{d.name}</li>
                      ))}
                    </ul>
                  </>
                )}
                {detail.required_by.length > 0 && (
                  <>
                    <h3 className="text-sm font-semibold mb-1">Required For</h3>
                    <ul className="space-y-1">
                      {detail.required_by.map((d) => (
                        <li key={d.id} className="text-xs text-text-secondary">{d.name}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}

            {/* External link */}
            <a
              href={`https://www.wowhead.com/achievement=${detail.blizzard_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              View on Wowhead <ExternalLink size={12} />
            </a>
          </div>
        ) : null}
      </div>
    </>
  );
}
