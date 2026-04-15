from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import logger

VALID_SOURCES = {"wowhead", "icy_veins", "reddit", "youtube", "blizzard"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _base_dir() -> Path:
    return Path(settings.RAW_STORAGE_PATH)


def _dir_for(source: str, achievement_id: str) -> Path:
    return _base_dir() / source / str(achievement_id)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def store_raw(
    source: str,
    achievement_id: str,
    content: str,
    metadata: Optional[dict] = None,
) -> str:
    if source not in VALID_SOURCES:
        raise ValueError(f"Unknown source: {source}")
    ts = _timestamp()
    target_dir = _dir_for(source, achievement_id)
    html_path = target_dir / f"{ts}.html"
    meta_path = target_dir / f"{ts}.meta.json"

    _atomic_write(html_path, content)

    meta = {
        "source": source,
        "achievement_id": str(achievement_id),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url": (metadata or {}).get("url"),
        "content_length": len(content),
        "metadata": metadata or {},
    }
    _atomic_write(meta_path, json.dumps(meta, indent=2))
    logger.debug(
        "raw_storage.stored",
        source=source,
        achievement_id=str(achievement_id),
        path=str(html_path),
        bytes=len(content),
    )
    return str(html_path)


def _list_html_files(source: str, achievement_id: str) -> list[Path]:
    d = _dir_for(source, achievement_id)
    if not d.exists():
        return []
    return sorted([p for p in d.iterdir() if p.suffix == ".html"], key=lambda p: p.name)


def get_raw(
    source: str, achievement_id: str, latest: bool = True
) -> Optional[tuple[str, dict]] | list[tuple[str, str]]:
    files = _list_html_files(source, achievement_id)
    if not files:
        return None if latest else []
    if latest:
        path = files[-1]
        content = path.read_text(encoding="utf-8")
        meta_path = path.with_suffix(".meta.json")
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        return content, meta
    return [(p.stem, str(p)) for p in files]


def raw_exists(source: str, achievement_id: str, max_age_hours: int = 720) -> bool:
    files = _list_html_files(source, achievement_id)
    if not files:
        return False
    latest = files[-1]
    mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    return mtime > datetime.now(timezone.utc) - timedelta(hours=max_age_hours)


def list_achievements_with_raw(source: str) -> list[str]:
    base = _base_dir() / source
    if not base.exists():
        return []
    return sorted([p.name for p in base.iterdir() if p.is_dir()])


def cleanup_old_raw(max_age_days: int = 90) -> dict[str, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    deleted_by_source: dict[str, int] = defaultdict(int)
    base = _base_dir()
    if not base.exists():
        return {}
    for source_dir in base.iterdir():
        if not source_dir.is_dir():
            continue
        for ach_dir in source_dir.iterdir():
            if not ach_dir.is_dir():
                continue
            htmls = sorted(
                [p for p in ach_dir.iterdir() if p.suffix == ".html"],
                key=lambda p: p.name,
            )
            if not htmls:
                continue
            keep = htmls[-1]
            for p in htmls:
                if p == keep:
                    continue
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    try:
                        p.unlink()
                        meta = p.with_suffix(".meta.json")
                        if meta.exists():
                            meta.unlink()
                        deleted_by_source[source_dir.name] += 1
                    except OSError as exc:
                        logger.warning("raw_storage.cleanup_failed", path=str(p), error=str(exc))
    for source, count in deleted_by_source.items():
        logger.info("raw_storage.cleanup", source=source, deleted=count)
    return dict(deleted_by_source)
