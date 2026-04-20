"""Constraint filter — hard elimination of achievements a character cannot complete."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from app.models.achievement import Achievement
from app.models.user import Character

logger = logging.getLogger(__name__)

# Expansion → minimum character level required
EXPANSION_LEVEL_GATES: dict[str, int] = {
    "Battle for Azeroth": 50,
    "Shadowlands": 60,
    "Dragonflight": 70,
    "The War Within": 80,
}


class BlockReason(Enum):
    FLYING_REQUIRED = "flying_required"
    LEVEL_TOO_LOW = "level_too_low"
    WRONG_FACTION = "wrong_faction"
    GROUP_REQUIRED = "group_required"
    LEGACY_UNOBTAINABLE = "legacy_unobtainable"
    PREREQUISITE_MISSING = "prerequisite_missing"


@dataclass
class BlockedAchievement:
    achievement: Achievement
    reason: BlockReason
    unlocker: str | None  # What the character needs to do to unblock this


@dataclass
class FilterResult:
    eligible: list[Achievement] = field(default_factory=list)
    blocked: list[BlockedAchievement] = field(default_factory=list)


class ConstraintFilter:
    """Applies hard constraint checks in priority order.

    First match wins — an achievement is blocked by at most one reason.
    """

    def filter(
        self,
        achievements: list[Achievement],
        character: Character,
        solo_only: bool = False,
    ) -> FilterResult:
        result = FilterResult()

        flying_unlocked: dict[str, bool] = character.flying_unlocked or {}
        char_level: int = character.level or 0
        char_faction: str | None = character.faction

        for ach in achievements:
            blocked = self._check_constraints(
                ach, char_level, char_faction, flying_unlocked, solo_only
            )
            if blocked is not None:
                result.blocked.append(blocked)
            else:
                # Tag low-confidence if no zone and no guide steps (data quality issue)
                if ach.zone_id is None:
                    has_guide_steps = any(
                        g.steps for g in (ach.guides or []) if g.steps
                    )
                    if not has_guide_steps:
                        ach.confidence_score = min(ach.confidence_score, 0.2)
                result.eligible.append(ach)

        logger.info(
            "Constraint filter: %d eligible, %d blocked (of %d total)",
            len(result.eligible),
            len(result.blocked),
            len(achievements),
        )
        return result

    # ------------------------------------------------------------------
    # Private — ordered constraint checks (first match wins)
    # ------------------------------------------------------------------

    def _check_constraints(
        self,
        ach: Achievement,
        char_level: int,
        char_faction: str | None,
        flying_unlocked: dict[str, bool],
        solo_only: bool,
    ) -> BlockedAchievement | None:
        # 1. Legacy gate
        if ach.is_legacy:
            return BlockedAchievement(ach, BlockReason.LEGACY_UNOBTAINABLE, None)

        # 2. Faction gate
        if ach.is_faction_specific and ach.faction and char_faction:
            if ach.faction.lower() != char_faction.lower():
                return BlockedAchievement(ach, BlockReason.WRONG_FACTION, None)

        # 3. Level gate
        if ach.expansion and ach.expansion in EXPANSION_LEVEL_GATES:
            minimum = EXPANSION_LEVEL_GATES[ach.expansion]
            if char_level < minimum:
                return BlockedAchievement(
                    ach,
                    BlockReason.LEVEL_TOO_LOW,
                    f"Reach level {minimum}",
                )

        # 4. Flying gate
        if ach.requires_flying:
            expansion = ach.expansion or ""
            if not flying_unlocked.get(expansion, False):
                return BlockedAchievement(
                    ach,
                    BlockReason.FLYING_REQUIRED,
                    f"Complete Pathfinder achievement for {expansion}"
                    if expansion
                    else "Unlock flying for the required zone",
                )

        # 5. Group gate
        if solo_only and ach.requires_group:
            return BlockedAchievement(
                ach,
                BlockReason.GROUP_REQUIRED,
                "Find a group or disable solo-only mode",
            )

        return None
