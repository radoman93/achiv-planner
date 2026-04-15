from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import Character, User

BNET_OAUTH_HOST = "https://oauth.battle.net"
BNET_API_HOST_TMPL = "https://{region}.api.blizzard.com"
BNET_USERINFO_TMPL = "https://oauth.battle.net/userinfo"


def authorize_url(region: str, state: str) -> str:
    return (
        f"{BNET_OAUTH_HOST}/authorize"
        f"?client_id={settings.BATTLENET_CLIENT_ID}"
        f"&scope=wow.profile"
        f"&state={state}"
        f"&redirect_uri={settings.BATTLENET_REDIRECT_URI}"
        f"&response_type=code"
        f"&region={region}"
    )


async def exchange_code(code: str, region: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BNET_OAUTH_HOST}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.BATTLENET_REDIRECT_URI,
            },
            auth=(settings.BATTLENET_CLIENT_ID, settings.BATTLENET_CLIENT_SECRET),
        )
    resp.raise_for_status()
    return resp.json()


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            BNET_USERINFO_TMPL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    resp.raise_for_status()
    return resp.json()


async def fetch_character_list(user: User, region: str, db: AsyncSession) -> list[Character]:
    host = BNET_API_HOST_TMPL.format(region=region)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{host}/profile/user/wow",
            headers={"Authorization": f"Bearer {user.battlenet_token}"},
            params={"namespace": f"profile-{region}", "locale": "en_US"},
        )
    resp.raise_for_status()
    data = resp.json()
    characters: list[Character] = []
    for account in data.get("wow_accounts", []):
        for c in account.get("characters", []):
            realm_slug = c.get("realm", {}).get("slug") or c.get("realm", {}).get("name", "")
            name = c.get("name", "")
            existing_res = await db.execute(
                select(Character).where(
                    Character.user_id == user.id,
                    Character.name == name,
                    Character.realm == realm_slug,
                )
            )
            character = existing_res.scalar_one_or_none()
            if character is None:
                character = Character(user_id=user.id, name=name, realm=realm_slug)
                db.add(character)
            character.level = c.get("level")
            character.class_ = c.get("playable_class", {}).get("name")
            character.race = c.get("playable_race", {}).get("name")
            character.faction = c.get("faction", {}).get("type")
            character.region = region
            character.last_synced_at = datetime.now(timezone.utc)
            characters.append(character)
    await db.commit()
    for ch in characters:
        await db.refresh(ch)
    return characters


async def fetch_character_achievements(character: Character, region: str, access_token: str) -> dict[str, Any]:
    host = BNET_API_HOST_TMPL.format(region=region)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{host}/profile/wow/character/{character.realm}/{character.name.lower()}/achievements",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"namespace": f"profile-{region}", "locale": "en_US"},
        )
    resp.raise_for_status()
    return resp.json()


async def refresh_battlenet_token(user: User, db: AsyncSession) -> None:
    if not user.battlenet_token_expires_at:
        return
    now = datetime.now(timezone.utc)
    if user.battlenet_token_expires_at - now > timedelta(minutes=5):
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BNET_OAUTH_HOST}/token",
            data={"grant_type": "client_credentials"},
            auth=(settings.BATTLENET_CLIENT_ID, settings.BATTLENET_CLIENT_SECRET),
        )
    resp.raise_for_status()
    data = resp.json()
    user.battlenet_token = data["access_token"]
    user.battlenet_token_expires_at = now + timedelta(seconds=data.get("expires_in", 3600))
    await db.commit()
