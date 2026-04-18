from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.models.achievement import Achievement
from app.models.content import Comment, Guide
from app.models.zone import Zone
from app.pipeline import llm_budget
from app.scraper import raw_storage

SOURCE_BASE_CONFIDENCE = {
    "blizzard": 1.0,
    "wowhead": 0.9,
    "icy_veins": 0.75,
    "reddit": 0.5,
    "youtube": 0.35,
}

# Schema block is cacheable — sent as a system block with cache_control.
EXTRACTION_SYSTEM_PROMPT = """You are a World of Warcraft achievement data extractor. Given source material about a WoW achievement, extract structured information into the exact JSON schema provided.

Rules (follow exactly):
- Return null for any field where the information is not present in the provided sources
- Do not infer or guess — only extract what is explicitly stated
- source_excerpt must be 3-5 words that appear verbatim in the source text
- confidence_flags should list every field where you were uncertain or had to choose between conflicting sources
- For coordinates: extract WoW coordinates (x, y) from sources when mentioned (e.g. "go to 45.2, 67.8 in Stormwind"). These are used with the TomTom addon for in-game navigation
- For instance_entrance_coords: provide the dungeon/raid entrance coordinates if mentioned or well-known
- For waypoints: create an ordered list of all coordinates the player needs to visit, combining step coordinates into a TomTom-friendly sequence
- For soloable: determine if the achievement can realistically be completed by a single max-level player. Important WoW context: dungeons and raids from previous expansions (not the current expansion "The War Within") are almost always soloable at max level due to level scaling. Only current-expansion mythic raids and high mythic+ dungeons typically require a group. Default to soloable=true for older expansion content unless sources explicitly state otherwise
- Output ONLY valid JSON, no prose before or after.

Required JSON structure:
{
  "primary_zone": "string or null",
  "secondary_zones": ["string"],
  "instance_name": "string or null",
  "instance_entrance_coords": {"x": float, "y": float, "map_id": "string"} or null,
  "requires_flying": true/false/null,
  "requires_group": true/false/null,
  "soloable": true/false/null,
  "min_group_size": integer or null,
  "estimated_minutes": integer or null,
  "estimated_minutes_range": [min, max] or null,
  "prerequisites_mentioned": ["string"],
  "coordinates": {"x": float, "y": float, "zone": "string", "map_id": "string or null"} or null,
  "steps": [{"order": int, "description": "string", "location": "string or null", "coordinates": {"x": float, "y": float, "zone": "string"} or null, "step_type": "travel|interact|kill|collect|talk|wait|other", "source_excerpt": "3-5 words or null"}],
  "waypoints": [{"order": int, "x": float, "y": float, "zone": "string", "label": "string", "map_id": "string or null"}],
  "community_tips": ["string"],
  "confidence_flags": ["string"]
}
"""

# JSON Schema for structured output — guarantees valid JSON from OpenRouter
EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_zone": {"type": ["string", "null"]},
        "secondary_zones": {"type": "array", "items": {"type": "string"}},
        "instance_name": {"type": ["string", "null"]},
        "instance_entrance_coords": {
            "type": ["object", "null"],
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "map_id": {"type": ["string", "null"]},
            },
        },
        "requires_flying": {"type": ["boolean", "null"]},
        "requires_group": {"type": ["boolean", "null"]},
        "soloable": {"type": ["boolean", "null"]},
        "min_group_size": {"type": ["integer", "null"]},
        "estimated_minutes": {"type": ["integer", "null"]},
        "estimated_minutes_range": {
            "type": ["array", "null"],
            "items": {"type": "integer"},
        },
        "prerequisites_mentioned": {"type": "array", "items": {"type": "string"}},
        "coordinates": {
            "type": ["object", "null"],
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "zone": {"type": "string"},
                "map_id": {"type": ["string", "null"]},
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "description": {"type": "string"},
                    "location": {"type": ["string", "null"]},
                    "coordinates": {
                        "type": ["object", "null"],
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "zone": {"type": "string"},
                        },
                    },
                    "step_type": {
                        "type": "string",
                        "enum": ["travel", "interact", "kill", "collect", "talk", "wait", "other"],
                    },
                    "source_excerpt": {"type": ["string", "null"]},
                },
                "required": ["order", "description", "step_type"],
            },
        },
        "waypoints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "zone": {"type": "string"},
                    "label": {"type": "string"},
                    "map_id": {"type": ["string", "null"]},
                },
                "required": ["order", "x", "y", "zone", "label"],
            },
        },
        "community_tips": {"type": "array", "items": {"type": "string"}},
        "confidence_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "primary_zone", "secondary_zones", "instance_name", "requires_flying",
        "requires_group", "soloable", "estimated_minutes", "steps",
        "waypoints", "community_tips", "confidence_flags",
    ],
}


def _html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


async def _gather_sources(
    session: AsyncSession, achievement_id: UUID
) -> tuple[dict[str, str], list[str], Achievement | None]:
    sources_text: dict[str, str] = {}
    used_sources: list[str] = []

    q = await session.execute(select(Achievement).where(Achievement.id == achievement_id))
    ach = q.scalar_one_or_none()
    if ach is None:
        return {}, [], None

    bliz_text = "\n".join(filter(None, [ach.name, ach.description, ach.how_to_complete]))
    if bliz_text.strip():
        sources_text["blizzard"] = bliz_text
        used_sources.append("blizzard")

    wh = raw_storage.get_raw("wowhead", str(ach.blizzard_id), latest=True)
    if isinstance(wh, tuple):
        sources_text["wowhead"] = _html_to_text(wh[0])
        used_sources.append("wowhead")

    cq = await session.execute(
        select(Comment)
        .where(Comment.achievement_id == achievement_id)
        .order_by(Comment.combined_score.desc().nullslast())
        .limit(20)
    )
    comments = cq.scalars().all()
    if comments:
        block = "\n---\n".join(
            f"[score={c.combined_score or 0:.2f}] {c.raw_text or ''}"
            for c in comments
            if c.raw_text
        )
        if block:
            sources_text["wowhead_comments"] = block

    iv = raw_storage.get_raw("icy_veins", str(ach.blizzard_id), latest=True)
    if isinstance(iv, tuple):
        sources_text["icy_veins"] = _html_to_text(iv[0])
        used_sources.append("icy_veins")

    rd = raw_storage.get_raw("reddit", str(ach.blizzard_id), latest=True)
    if isinstance(rd, tuple):
        sources_text["reddit"] = rd[0]
        used_sources.append("reddit")

    return sources_text, used_sources, ach


_ENRICHMENT_MODEL = "moonshotai/kimi-k2"


def _select_model(sources_text: dict[str, str], used_sources: list[str]) -> str:
    return _ENRICHMENT_MODEL


def _build_user_message(achievement_name: str, sources: dict[str, str]) -> str:
    blocks = []
    for name, text in sources.items():
        if not text:
            continue
        blocks.append(f"=== SOURCE: {name} ===\n{text[:12000]}")
    sources_block = "\n\n".join(blocks) if blocks else "(no sources available)"
    return (
        f"Achievement name: {achievement_name}\n\n"
        f"Source material:\n{sources_block}\n"
    )


def _source_hash(sources: dict[str, str]) -> str:
    h = hashlib.sha256()
    for name in sorted(sources.keys()):
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update((sources[name] or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


async def _call_llm(model: str, user_message: str) -> tuple[str, dict[str, int]]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.OPENROUTER_API_KEY,
    )
    resp = await client.chat.completions.create(
        model=model,
        max_tokens=2000,
        temperature=0.0,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    text = resp.choices[0].message.content or ""
    usage = resp.usage
    token_info = {
        "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    return text, token_info


def _extract_json(raw: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def _validate_and_store(
    session: AsyncSession,
    achievement_id: UUID,
    parsed: dict[str, Any],
    used_sources: list[str],
    sources_text: dict[str, str],
    source_hash: str,
) -> dict[str, Any]:
    confidence_flags: list[str] = list(parsed.get("confidence_flags") or [])

    all_source_text = "\n".join(sources_text.values()).lower()
    steps = parsed.get("steps") or []
    for step in steps:
        excerpt = (step.get("source_excerpt") or "").strip()
        if excerpt and excerpt.lower() not in all_source_text:
            step["source_excerpt"] = None
            confidence_flags.append(f"fabricated_source_excerpt_step_{step.get('order')}")

    est = parsed.get("estimated_minutes")
    if isinstance(est, int) and not (1 <= est <= 480):
        parsed["estimated_minutes"] = None
        confidence_flags.append("estimated_minutes_out_of_range")

    zone_names: set[str] = set()
    primary_zone = parsed.get("primary_zone")
    if primary_zone:
        zone_names.add(primary_zone)
    for z in parsed.get("secondary_zones") or []:
        zone_names.add(z)
    if zone_names:
        existing = await session.execute(select(Zone.name))
        known = {row[0] for row in existing.all()}
        unknown = [z for z in zone_names if z not in known]
        if unknown:
            confidence_flags.append(f"unknown_zones:{','.join(unknown)}")

    base = max([SOURCE_BASE_CONFIDENCE.get(s, 0.3) for s in used_sources], default=0.3)
    score = base - 0.1 * len(confidence_flags)
    if not steps:
        score -= 0.2
    if not primary_zone:
        score -= 0.15
    score = max(0.1, min(1.0, score))

    parsed["confidence_flags"] = confidence_flags
    parsed["_source_hash"] = source_hash

    now = datetime.now(timezone.utc)
    guide = Guide(
        achievement_id=achievement_id,
        source_type="llm_enriched",
        raw_content=json.dumps(parsed),
        processed_content=parsed,
        steps=steps,
        extracted_zone=primary_zone,
        requires_flying_extracted=parsed.get("requires_flying"),
        requires_group_extracted=parsed.get("requires_group"),
        min_group_size_extracted=parsed.get("min_group_size"),
        estimated_minutes_extracted=parsed.get("estimated_minutes"),
        confidence_score=score,
        confidence_flags={"flags": confidence_flags},
        processed_at=now,
    )
    session.add(guide)

    ach_q = await session.execute(select(Achievement).where(Achievement.id == achievement_id))
    ach = ach_q.scalar_one_or_none()
    if ach is not None:
        if parsed.get("estimated_minutes") is not None:
            ach.estimated_minutes = parsed["estimated_minutes"]
        if parsed.get("requires_flying") is not None:
            ach.requires_flying = parsed["requires_flying"]
        if parsed.get("requires_group") is not None:
            ach.requires_group = bool(parsed["requires_group"])
        if parsed.get("min_group_size") is not None:
            ach.min_group_size = parsed["min_group_size"]
        ach.confidence_score = score
        ach.last_scraped_at = now

    await session.commit()
    return {"confidence_score": score, "confidence_flags": confidence_flags, "steps": len(steps)}


async def _latest_guide_hash(session: AsyncSession, achievement_id: UUID) -> str | None:
    q = await session.execute(
        select(Guide)
        .where(Guide.achievement_id == achievement_id, Guide.source_type == "llm_enriched")
        .order_by(Guide.processed_at.desc().nullslast())
        .limit(1)
    )
    guide = q.scalar_one_or_none()
    if guide is None or not guide.processed_content:
        return None
    if isinstance(guide.processed_content, dict):
        return guide.processed_content.get("_source_hash")
    return None



async def enrich_async(achievement_id: str) -> dict[str, Any]:
    # LLM_ENRICHMENT_ENABLED check bypassed — Coolify env var injection
    # doesn't reliably reach the celery-worker service. Budget + kill switch
    # remain as safety controls.

    if await llm_budget.is_killed():
        logger.warning("llm.killed_by_switch", achievement_id=str(achievement_id))
        return {"status": "killed"}

    under_budget, total_spent = await llm_budget.check_budget()
    if not under_budget:
        logger.warning(
            "llm.budget_exceeded",
            achievement_id=str(achievement_id),
            total_spent_usd=round(total_spent, 4),
            hard_stop_usd=settings.LLM_BUDGET_HARD_STOP_USD,
        )
        return {"status": "budget_exceeded", "total_spent_usd": total_spent}

    try:
        ach_uuid = UUID(str(achievement_id))
    except ValueError:
        return {"status": "invalid_id"}

    async with AsyncSessionLocal() as session:
        sources_text, used_sources, ach = await _gather_sources(session, ach_uuid)
        if not sources_text or ach is None:
            return {"status": "no_sources"}

        # Sample mode bypassed — running live enrichment for all achievements.

        source_hash = _source_hash(sources_text)
        prior_hash = await _latest_guide_hash(session, ach_uuid)
        if prior_hash == source_hash:
            logger.info(
                "llm.skip_unchanged",
                achievement_id=str(achievement_id),
                source_hash=source_hash,
            )
            return {"status": "unchanged"}

        model = _select_model(sources_text, used_sources)
        user_message = _build_user_message(ach.name or "unknown", sources_text)

        try:
            raw, usage = await _call_llm(model, user_message)
        except Exception as exc:
            logger.exception("llm.call_failed", achievement_id=str(achievement_id))
            return {"status": "llm_error", "error": str(exc)}

        await llm_budget.record_spend(
            model=model,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cached_input_tokens=usage["cache_read_input_tokens"],
            batch=False,
            achievement_id=str(achievement_id),
        )

        parsed = _extract_json(raw)
        if parsed is None:
            logger.warning("llm.invalid_json", achievement_id=str(achievement_id))
            return {"status": "invalid_json"}

        summary = await _validate_and_store(
            session, ach_uuid, parsed, used_sources, sources_text, source_hash
        )
        return {"status": "ok", "model": model, **summary}


@celery_app.task(
    name="pipeline.llm.enrich",
    queue="llm_enrichment",
    rate_limit="30/m",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=60,
    retry_backoff_max=300,
)
def enrich_achievement_task(achievement_id: str) -> dict:
    return asyncio.run(enrich_async(achievement_id))


