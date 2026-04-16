from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.core.redis import get_redis_client

BLIZZARD_RATE_LIMIT_PER_SEC = 100
TOKEN_CACHE_KEY = "blizzard:oauth:token:{region}"
RATE_LIMIT_KEY = "blizzard:ratelimit:{region}"


class BlizzardAPIError(Exception):
    pass


class BlizzardRateLimiter:
    """Token-bucket rate limiter backed by Redis (shared across workers)."""

    def __init__(self, region: str, max_per_sec: int = BLIZZARD_RATE_LIMIT_PER_SEC):
        self.region = region
        self.max_per_sec = max_per_sec
        self.key = RATE_LIMIT_KEY.format(region=region)

    async def acquire(self) -> None:
        redis = get_redis_client()
        try:
            while True:
                now = time.time()
                window_start = now - 1.0
                pipe = redis.pipeline()
                pipe.zremrangebyscore(self.key, 0, window_start)
                pipe.zcard(self.key)
                _, count = await pipe.execute()
                if count < self.max_per_sec:
                    await redis.zadd(self.key, {f"{now}:{id(self)}": now})
                    await redis.expire(self.key, 2)
                    return
                await asyncio.sleep(0.01)
        finally:
            await redis.aclose()


class BlizzardClient:
    def __init__(self, region: str = "us"):
        self.region = region
        self.client_id = settings.BATTLENET_CLIENT_ID
        self.client_secret = settings.BATTLENET_CLIENT_SECRET
        self.rate_limiter = BlizzardRateLimiter(region)
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> "BlizzardClient":
        await self._get_http()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _get_access_token(self) -> str:
        redis = get_redis_client()
        key = TOKEN_CACHE_KEY.format(region=self.region)
        try:
            cached = await redis.get(key)
            if cached:
                return cached
            http = await self._get_http()
            resp = await http.post(
                f"https://{self.region}.battle.net/oauth/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
            )
            resp.raise_for_status()
            payload = resp.json()
            token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 86400))
            ttl = max(expires_in - 60, 60)
            await redis.set(key, token, ex=ttl)
            return token
        finally:
            await redis.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        token: Optional[str] = None,
        max_retries: int = 5,
    ) -> dict[str, Any]:
        http = await self._get_http()
        attempt = 0
        backoff = 1.0
        while True:
            attempt += 1
            await self.rate_limiter.acquire()
            auth_token = token or await self._get_access_token()
            headers = {"Authorization": f"Bearer {auth_token}"}
            try:
                resp = await http.request(method, url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                if attempt > max_retries:
                    raise BlizzardAPIError(f"HTTP error after {max_retries} retries: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                logger.warning("blizzard.rate_limited", url=url, retry_after=retry_after)
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code == 503:
                if attempt > max_retries:
                    raise BlizzardAPIError(f"503 after {max_retries} retries: {url}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            if resp.status_code == 401 and not token:
                # token may have expired mid-flight; force refresh
                redis = get_redis_client()
                try:
                    await redis.delete(TOKEN_CACHE_KEY.format(region=self.region))
                finally:
                    await redis.aclose()
                continue
            if resp.status_code == 404:
                raise BlizzardAPIError(f"404 Not Found: {url}")
            resp.raise_for_status()
            return resp.json()

    # ---- Public API ----

    async def get_all_achievements(self, region: Optional[str] = None) -> list[dict]:
        region = region or self.region
        cache_key = f"blizzard:achievements:index:{region}"
        redis = get_redis_client()
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        finally:
            await redis.aclose()

        url = f"https://{region}.api.blizzard.com/data/wow/achievement/index"
        params = {"namespace": f"static-{region}", "locale": "en_US"}
        data = await self._request("GET", url, params=params)

        achievements: list[dict] = []
        # index endpoint returns {"achievements": [{id, name, key:{href}}, ...]}
        entries = data.get("achievements", [])
        # Expand each entry minimally — caller can fetch details as needed.
        for entry in entries:
            achievements.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "key": entry.get("key", {}).get("href"),
                }
            )

        redis = get_redis_client()
        try:
            await redis.set(cache_key, json.dumps(achievements), ex=86400)
        finally:
            await redis.aclose()
        return achievements

    async def get_achievement_detail(
        self, achievement_id: int, region: Optional[str] = None
    ) -> dict:
        region = region or self.region
        cache_key = f"blizzard:achievement:{achievement_id}:{region}"
        redis = get_redis_client()
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        finally:
            await redis.aclose()

        url = f"https://{region}.api.blizzard.com/data/wow/achievement/{achievement_id}"
        params = {"namespace": f"static-{region}", "locale": "en_US"}
        data = await self._request("GET", url, params=params)

        redis = get_redis_client()
        try:
            await redis.set(cache_key, json.dumps(data), ex=21600)
        finally:
            await redis.aclose()
        return data

    async def get_achievement_categories(self, region: Optional[str] = None) -> list[dict]:
        region = region or self.region
        cache_key = f"blizzard:achievement_categories:{region}"
        redis = get_redis_client()
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        finally:
            await redis.aclose()

        url = f"https://{region}.api.blizzard.com/data/wow/achievement-category/index"
        params = {"namespace": f"static-{region}", "locale": "en_US"}
        data = await self._request("GET", url, params=params)
        categories = data.get("categories", [])

        redis = get_redis_client()
        try:
            await redis.set(cache_key, json.dumps(categories), ex=86400)
        finally:
            await redis.aclose()
        return categories

    async def get_character_achievements(
        self,
        realm: str,
        character_name: str,
        token: str,
        region: Optional[str] = None,
    ) -> dict:
        region = region or self.region
        url = (
            f"https://{region}.api.blizzard.com/profile/wow/character/"
            f"{realm.lower()}/{character_name.lower()}/achievements"
        )
        params = {"namespace": f"profile-{region}", "locale": "en_US"}
        return await self._request("GET", url, params=params, token=token)
