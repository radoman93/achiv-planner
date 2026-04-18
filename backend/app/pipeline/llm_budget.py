from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.core.logging import logger
from app.core.redis import get_redis_client

TOTAL_KEY = "llm:spend:total_usd_cents"
MONTH_KEY_FMT = "llm:spend:month:{ym}"
KILL_SWITCH_KEY = "llm:kill_switch"
THRESHOLDS_KEY = "llm:spend:thresholds_hit"


@dataclass(frozen=True)
class ModelPricing:
    """Per million-token pricing in USD (as of 2026-04)."""

    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float  # price for reading from prompt cache


PRICING: dict[str, ModelPricing] = {
    "claude-haiku-4-5-20251001": ModelPricing(1.0, 5.0, 0.10),
    "claude-sonnet-4-20250514": ModelPricing(3.0, 15.0, 0.30),
    "claude-opus-4-6": ModelPricing(15.0, 75.0, 1.50),
    "moonshotai/kimi-k2.5": ModelPricing(0.38, 1.72, 0.15),
    "moonshotai/kimi-k2": ModelPricing(0.60, 2.50, 0.15),
    "qwen/qwen3-max": ModelPricing(0.78, 3.90, 0.10),
}

BATCH_DISCOUNT = 0.50  # Batch API = 50% off real-time pricing


def _pricing_for(model: str) -> ModelPricing:
    pricing = PRICING.get(model)
    if pricing is None:
        # Unknown model → fall back to conservative estimate
        logger.warning("llm_budget.unknown_model", model=model)
        return ModelPricing(1.0, 5.0, 0.10)
    return pricing


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    batch: bool = False,
) -> float:
    pricing = _pricing_for(model)
    regular_input = max(0, input_tokens - cached_input_tokens)
    cost = (
        (regular_input / 1_000_000) * pricing.input_per_mtok
        + (cached_input_tokens / 1_000_000) * pricing.cached_input_per_mtok
        + (output_tokens / 1_000_000) * pricing.output_per_mtok
    )
    if batch:
        cost *= BATCH_DISCOUNT
    return cost


def _month_key(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return MONTH_KEY_FMT.format(ym=now.strftime("%Y-%m"))


async def record_spend(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    batch: bool = False,
    achievement_id: Optional[str] = None,
) -> dict:
    cost_usd = estimate_cost_usd(
        model, input_tokens, output_tokens, cached_input_tokens, batch
    )
    cost_cents = int(round(cost_usd * 10_000))  # store in 1/100-cent to avoid float rounding drift

    redis = get_redis_client()
    try:
        pipe = redis.pipeline()
        pipe.incrby(TOTAL_KEY, cost_cents)
        pipe.incrby(_month_key(), cost_cents)
        pipe.expire(_month_key(), 60 * 60 * 24 * 60)  # 60-day TTL
        total_cents, month_cents, _ = await pipe.execute()
        total_usd = int(total_cents) / 10_000
        month_usd = int(month_cents) / 10_000

        logger.info(
            "llm.call_complete",
            achievement_id=achievement_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            batch=batch,
            cost_usd=round(cost_usd, 6),
            cumulative_total_usd=round(total_usd, 4),
            cumulative_month_usd=round(month_usd, 4),
        )

        # One-shot threshold alerts
        for threshold in (5.0, 10.0, 15.0, 20.0):
            if total_usd >= threshold:
                added = await redis.sadd(THRESHOLDS_KEY, str(threshold))
                if added:
                    logger.warning(
                        "llm.budget_threshold_hit",
                        threshold_usd=threshold,
                        total_usd=round(total_usd, 4),
                    )

        return {
            "cost_usd": cost_usd,
            "total_usd": total_usd,
            "month_usd": month_usd,
        }
    finally:
        await redis.aclose()


async def current_total_usd() -> float:
    redis = get_redis_client()
    try:
        val = await redis.get(TOTAL_KEY)
        if not val:
            return 0.0
        return int(val) / 10_000
    finally:
        await redis.aclose()


async def current_month_usd() -> float:
    redis = get_redis_client()
    try:
        val = await redis.get(_month_key())
        if not val:
            return 0.0
        return int(val) / 10_000
    finally:
        await redis.aclose()


async def check_budget() -> tuple[bool, float]:
    """Returns (under_budget, current_total_usd). Hard-stops at $50."""
    total = await current_total_usd()
    return (total < 50.0, total)


async def is_killed() -> bool:
    redis = get_redis_client()
    try:
        val = await redis.get(KILL_SWITCH_KEY)
        return bool(val) and val not in ("0", "false", "False")
    finally:
        await redis.aclose()


async def set_kill_switch(enabled: bool) -> None:
    redis = get_redis_client()
    try:
        if enabled:
            await redis.set(KILL_SWITCH_KEY, "1")
        else:
            await redis.delete(KILL_SWITCH_KEY)
    finally:
        await redis.aclose()
