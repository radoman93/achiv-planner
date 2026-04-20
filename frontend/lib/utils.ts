export const TIER_COLORS: Record<string, string> = {
  verified: "bg-tier-verified",
  high: "bg-tier-high",
  medium: "bg-tier-medium",
  low: "bg-tier-low",
  research_required: "bg-tier-research",
};

export const TIER_TEXT_COLORS: Record<string, string> = {
  verified: "text-tier-verified",
  high: "text-tier-high",
  medium: "text-tier-medium",
  low: "text-tier-low",
  research_required: "text-tier-research",
};

export function formatMinutes(m: number | null | undefined): string {
  if (!m) return "—";
  if (m < 60) return `${m}m`;
  const hours = Math.floor(m / 60);
  const mins = m % 60;
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

export function wowheadUrl(blizzardId: number): string {
  return `https://www.wowhead.com/achievement=${blizzardId}`;
}

export function achievementIconUrl(iconName?: string): string {
  return iconName
    ? `https://wow.zamimg.com/images/wow/icons/medium/${iconName}.jpg`
    : "/placeholder-icon.png";
}

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
