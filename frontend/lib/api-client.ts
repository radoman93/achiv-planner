import axios, { AxiosError } from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

export class RateLimitError extends Error {
  retryAfterSeconds: number;
  constructor(message: string, retryAfter: number) {
    super(message);
    this.name = "RateLimitError";
    this.retryAfterSeconds = retryAfter;
  }
}

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ error?: { code?: string; message?: string }; detail?: Record<string, unknown> | string }>) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      // Only redirect if not already on auth pages
      if (
        !window.location.pathname.startsWith("/login") &&
        !window.location.pathname.startsWith("/register")
      ) {
        window.location.href = "/login";
      }
    }
    if (err.response?.status === 429) {
      const detail = err.response.data?.detail;
      const retryAfter =
        typeof detail === "object" && detail !== null && "retry_after_seconds" in detail
          ? (detail.retry_after_seconds as number)
          : 60;
      const msg =
        typeof detail === "string"
          ? detail
          : typeof detail === "object" && detail !== null && "message" in detail
            ? String(detail.message)
            : "Rate limited";
      throw new RateLimitError(msg, retryAfter);
    }
    return Promise.reject(err);
  },
);

export default api;

// ─── Response types ──────────────────────────────────────────────

export interface ApiEnvelope<T> {
  data: T;
  error: { code: string; message: string } | null;
}

export interface AchievementSummary {
  id: string;
  blizzard_id: number;
  name: string;
  category: string | null;
  subcategory: string | null;
  expansion: string | null;
  points: number;
  zone_name: string | null;
  is_seasonal: boolean;
  requires_group: boolean;
  confidence_tier: string;
  is_meta: boolean;
  relevance_score?: number;
}

export interface AchievementDetail extends AchievementSummary {
  description: string | null;
  how_to_complete: string | null;
  zone: { id: string; name: string } | null;
  is_legacy: boolean;
  seasonal_event: string | null;
  seasonal_start: string | null;
  seasonal_end: string | null;
  requires_flying: boolean | null;
  min_group_size: number | null;
  estimated_minutes: number | null;
  confidence_score: number;
  last_scraped_at: string | null;
  guide: GuideData | null;
  comments: CommentData[];
  criteria: CriteriaData[];
  requires: { id: string; name: string }[];
  required_by: { id: string; name: string }[];
}

export interface GuideData {
  id: string;
  source_type: string | null;
  source_url: string | null;
  steps: StepData[] | null;
  confidence_score: number | null;
  confidence_tier?: string;
  scraped_at: string | null;
}

export interface StepData {
  order?: number;
  label?: string;
  description?: string;
  type?: string;
  zone?: string;
  location?: string;
  step_type?: string;
}

export interface CommentData {
  id?: string;
  author: string | null;
  text: string;
  combined_score?: number | null;
  score?: number | null;
  comment_type: string | null;
  upvotes?: number;
  type?: string | null;
}

export interface CriteriaData {
  id: string;
  description: string | null;
  required_amount: number | null;
}

export interface CharacterSummary {
  id: string;
  name: string;
  realm: string;
  faction: string | null;
  class: string | null;
  level: number | null;
  region: string | null;
  last_synced_at: string | null;
  achievement_completion_pct: number;
}

export interface UserProfile {
  id: string;
  email: string;
  tier: string;
  battlenet_connected: boolean;
  battlenet_region: string | null;
  priority_mode: string;
  session_duration_minutes: number;
  solo_only: boolean;
  created_at: string | null;
}

export interface RouteStopData {
  id: string;
  achievement: {
    id: string;
    blizzard_id: number;
    name: string;
    points: number;
    category: string | null;
  } | null;
  zone: { name: string; expansion: string | null } | null;
  estimated_minutes: number | null;
  confidence_tier: string | null;
  is_seasonal: boolean;
  days_remaining: number | null;
  steps: StepData[];
  community_tips: CommentData[];
  wowhead_url: string | null;
  completed: boolean;
  skipped: boolean;
}

export interface RouteSessionData {
  session_number: number;
  estimated_minutes: number;
  primary_zone: string;
  stops: RouteStopData[];
}

export interface RouteData {
  id: string;
  mode: string | null;
  status: string;
  created_at: string | null;
  overall_confidence: number | null;
  total_estimated_minutes: number | null;
  seasonal_block: { stops: RouteStopData[] };
  sessions: RouteSessionData[];
  blocked_pool: {
    achievement_name?: string;
    reason: string;
    unlocker: string | null;
  }[];
}

export interface RouteSummary {
  id: string;
  mode: string | null;
  status: string;
  created_at: string | null;
  overall_confidence: number | null;
  total_estimated_minutes: number | null;
}

export interface SeasonalEvent {
  event_name: string;
  opens_at: string;
  closes_at: string;
  days_remaining?: number;
  days_until_open?: number;
  achievement_count: number;
  achievements?: AchievementSummary[];
}

export interface UserStats {
  total_achievement_points: number;
  total_achievements_completed: number;
  total_achievements_eligible: number;
  overall_completion_pct: number;
  completion_by_expansion: Record<
    string,
    { completed: number; total: number; pct: number }
  >;
  estimated_hours_remaining: number;
  achievements_completed_this_month: number;
  favorite_category: string | null;
}
