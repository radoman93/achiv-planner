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
EXTRACTION_SCHEMA_DOC = """Return a JSON object with these exact fields:
{
  "primary_zone": "string or null",
  "secondary_zones": ["string"] or [],
  "instance_name": "string or null",
  "requires_flying": true/false/null,
  "requires_group": true/false,
  "min_group_size": integer or null,
  "estimated_minutes": integer or null,
  "estimated_minutes_range": [min, max] or null,
  "prerequisites_mentioned": ["string"],
  "steps": [
    {
      "order": integer,
      "description": "string",
      "location": "string or null",
      "step_type": "travel|interact|kill|collect|talk|wait|other",
      "source_excerpt": "3-5 words from source this was extracted from"
    }
  ],
  "community_tips": ["string"],
  "confidence_flags": ["string describing what was uncertain or inferred"]
}

Rules (follow exactly):
- Return null for any field where the information is not present in the provided sources
- Do not infer or guess — only extract what is explicitly stated
- source_excerpt must be 3-5 words that appear verbatim in the source text
- confidence_flags should list every field where you were uncertain or had to choose between conflicting sources
- Output ONLY valid JSON, no prose before or after.
"""


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


def _select_model(sources_text: dict[str, str], used_sources: list[str]) -> str:
    has_fallback = any(s in used_sources for s in ("icy_veins", "reddit", "youtube"))
    total_chars = sum(len(v) for v in sources_text.values())
    if not has_fallback and total_chars < 4000:
        return settings.LLM_DEFAULT_MODEL  # Haiku
    return settings.LLM_COMPLEX_MODEL  # Sonnet


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


async def _call_claude(model: str, user_message: str) -> tuple[str, dict[str, int]]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = await client.messages.create(
        model=model,
        max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        temperature=0.0,
        system=[
            {
                "type": "text",
                "text": EXTRACTION_SCHEMA_DOC,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)

    usage = resp.usage
    token_info = {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }
    return "".join(parts), token_info


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


def _sample_ids() -> set[str]:
    raw = (settings.LLM_SAMPLE_IDS or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


async def enrich_async(achievement_id: str) -> dict[str, Any]:
    if not settings.LLM_ENRICHMENT_ENABLED:
        logger.info("llm.disabled_by_config", achievement_id=str(achievement_id))
        return {"status": "disabled"}

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

        mode = (settings.LLM_ENRICHMENT_MODE or "live").lower()
        if mode == "sample":
            allowed = _sample_ids()
            if allowed and str(ach.blizzard_id) not in allowed:
                return {"status": "skipped_not_in_sample"}

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

        if mode == "dry_run":
            logger.info(
                "llm.dry_run",
                achievement_id=str(achievement_id),
                model=model,
                prompt_chars=len(user_message),
                sources=list(sources_text.keys()),
            )
            return {"status": "dry_run", "model": model, "prompt_chars": len(user_message)}

        try:
            raw, usage = await _call_claude(model, user_message)
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


async def enrich_batch_async(achievement_ids: list[str]) -> dict[str, Any]:
    """Route bulk enrichment through the Anthropic Batch API (50% cheaper)."""
    if not settings.LLM_ENRICHMENT_ENABLED:
        return {"status": "disabled", "count": 0}

    if await llm_budget.is_killed():
        return {"status": "killed", "count": 0}

    under_budget, total_spent = await llm_budget.check_budget()
    if not under_budget:
        return {"status": "budget_exceeded", "total_spent_usd": total_spent, "count": 0}

    from anthropic import AsyncAnthropic

    prepared: list[dict[str, Any]] = []
    meta_by_custom_id: dict[str, dict[str, Any]] = {}

    async with AsyncSessionLocal() as session:
        sample_ids = _sample_ids()
        for ach_id in achievement_ids:
            try:
                ach_uuid = UUID(str(ach_id))
            except ValueError:
                continue
            sources_text, used_sources, ach = await _gather_sources(session, ach_uuid)
            if not sources_text or ach is None:
                continue
            if (settings.LLM_ENRICHMENT_MODE or "live").lower() == "sample":
                if sample_ids and str(ach.blizzard_id) not in sample_ids:
                    continue

            source_hash = _source_hash(sources_text)
            prior_hash = await _latest_guide_hash(session, ach_uuid)
            if prior_hash == source_hash:
                continue

            model = _select_model(sources_text, used_sources)
            user_message = _build_user_message(ach.name or "unknown", sources_text)
            custom_id = f"ach-{ach.blizzard_id}"
            prepared.append(
                {
                    "custom_id": custom_id,
                    "params": {
                        "model": model,
                        "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
                        "temperature": 0.0,
                        "system": [
                            {
                                "type": "text",
                                "text": EXTRACTION_SCHEMA_DOC,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                        "messages": [{"role": "user", "content": user_message}],
                    },
                }
            )
            meta_by_custom_id[custom_id] = {
                "achievement_uuid": ach_uuid,
                "blizzard_id": ach.blizzard_id,
                "model": model,
                "used_sources": used_sources,
                "sources_text": sources_text,
                "source_hash": source_hash,
            }

    if not prepared:
        return {"status": "nothing_to_do", "count": 0}

    if (settings.LLM_ENRICHMENT_MODE or "live").lower() == "dry_run":
        logger.info(
            "llm.batch_dry_run",
            requests=len(prepared),
            models={p["params"]["model"] for p in prepared},
        )
        return {"status": "dry_run", "count": len(prepared)}

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    batch = await client.messages.batches.create(requests=prepared)
    batch_id = batch.id
    logger.info("llm.batch_submitted", batch_id=batch_id, count=len(prepared))

    # Poll for completion
    while True:
        status = await client.messages.batches.retrieve(batch_id)
        if status.processing_status == "ended":
            break
        await asyncio.sleep(30)

    stored = 0
    async with AsyncSessionLocal() as session:
        async for result in await client.messages.batches.results(batch_id):
            custom_id = result.custom_id
            meta = meta_by_custom_id.get(custom_id)
            if meta is None:
                continue
            if result.result.type != "succeeded":
                logger.warning(
                    "llm.batch_entry_failed",
                    custom_id=custom_id,
                    type=result.result.type,
                )
                continue
            message = result.result.message
            text_parts = [
                b.text for b in message.content if getattr(b, "type", None) == "text"
            ]
            raw = "".join(text_parts)

            usage = message.usage
            await llm_budget.record_spend(
                model=meta["model"],
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                batch=True,
                achievement_id=str(meta["achievement_uuid"]),
            )

            parsed = _extract_json(raw)
            if parsed is None:
                logger.warning("llm.batch_invalid_json", custom_id=custom_id)
                continue

            await _validate_and_store(
                session,
                meta["achievement_uuid"],
                parsed,
                meta["used_sources"],
                meta["sources_text"],
                meta["source_hash"],
            )
            stored += 1

    return {"status": "ok", "submitted": len(prepared), "stored": stored, "batch_id": batch_id}


@celery_app.task(
    name="pipeline.llm.enrich",
    queue="llm_enrichment",
    rate_limit="50/m",
)
def enrich_achievement_task(achievement_id: str) -> dict:
    return asyncio.run(enrich_async(achievement_id))


@celery_app.task(
    name="pipeline.llm.enrich_batch",
    queue="llm_enrichment",
)
def enrich_batch_task(achievement_ids: list[str]) -> dict:
    return asyncio.run(enrich_batch_async(achievement_ids))
