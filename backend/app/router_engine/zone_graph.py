"""Zone connectivity graph — weighted travel cost graph with Dijkstra shortest path."""

from __future__ import annotations

import heapq
import json
import logging
from collections import defaultdict
from pathlib import Path

import redis.asyncio as aioredis

from app.models.user import Character
from app.models.zone import Zone

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"
_ZONE_CONNECTIONS_FILE = _DATA_DIR / "zone_connections.json"

# Travel cost constants (minutes)
COST_SAME_ZONE = 0.0
COST_PORTAL = 2.0
COST_FLIGHT_SAME_CONTINENT = 8.0
COST_FLIGHT_CROSS_CONTINENT = 15.0
COST_BOAT_ZEPPELIN = 10.0
COST_FLYING_HAS = 5.0
COST_FLYING_MISSING = 999.0
COST_HEARTHSTONE_PORTAL = 5.0

GRAPH_CACHE_KEY = "router:zone_graph:v1"
GRAPH_CACHE_TTL = 3600  # 1 hour


class ZoneGraph:
    """Builds and caches a weighted graph of travel costs between WoW zones."""

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._adj: dict[str, dict[str, float]] = defaultdict(dict)
        self._zone_name_to_id: dict[str, str] = {}
        self._zone_id_to_name: dict[str, str] = {}
        self._connections_data: dict = {}
        self._loaded = False

    def _load_connections(self) -> dict:
        if not self._connections_data:
            with open(_ZONE_CONNECTIONS_FILE) as f:
                self._connections_data = json.load(f)
        return self._connections_data

    async def build_graph(
        self, zones: list[Zone], character: Character
    ) -> None:
        """Build the weighted adjacency list, accounting for character flying status."""
        data = self._load_connections()
        flying_unlocked: dict[str, bool] = character.flying_unlocked or {}
        char_faction = (character.faction or "").lower()

        # Map zone names ↔ IDs
        self._zone_name_to_id = {z.name: str(z.id) for z in zones}
        self._zone_id_to_name = {str(z.id): z.name for z in zones}
        zone_continent: dict[str, str] = {}
        zone_expansion: dict[str, str] = {}
        zone_requires_flying: dict[str, bool] = {}

        for z in zones:
            zid = str(z.id)
            zone_requires_flying[zid] = z.requires_flying
            if z.expansion:
                zone_expansion[zid] = z.expansion

        # Build continent lookup from connections data
        continent_zones = data.get("continent_zones", {})
        for continent, zone_names in continent_zones.items():
            for zname in zone_names:
                if zname in self._zone_name_to_id:
                    zone_continent[self._zone_name_to_id[zname]] = continent

        self._adj = defaultdict(dict)

        # 1. Same-continent flight paths
        continent_groups: dict[str, list[str]] = defaultdict(list)
        for zid, cont in zone_continent.items():
            continent_groups[cont].append(zid)

        for cont, zone_ids in continent_groups.items():
            for i, za in enumerate(zone_ids):
                for zb in zone_ids[i + 1:]:
                    cost = COST_FLIGHT_SAME_CONTINENT
                    # If destination requires flying and character doesn't have it
                    for dest, src in [(zb, za), (za, zb)]:
                        if zone_requires_flying.get(dest, False):
                            exp = zone_expansion.get(dest, "")
                            if not flying_unlocked.get(exp, False):
                                self._set_edge(src, dest, COST_FLYING_MISSING)
                                continue
                            else:
                                self._set_edge(src, dest, COST_FLYING_HAS)
                                continue
                        self._set_edge(src, dest, cost)

        # 2. Cross-continent default connections
        all_continents = list(continent_groups.keys())
        for i, ca in enumerate(all_continents):
            for cb in all_continents[i + 1:]:
                for za in continent_groups[ca]:
                    for zb in continent_groups[cb]:
                        # Only set if not already set (portals take priority)
                        if zb not in self._adj.get(za, {}):
                            self._set_edge(za, zb, COST_FLIGHT_CROSS_CONTINENT)
                        if za not in self._adj.get(zb, {}):
                            self._set_edge(zb, za, COST_FLIGHT_CROSS_CONTINENT)

        # 3. Portal connections (override with lower cost)
        portal_hubs = data.get("portal_hubs", {})
        for hub_name, hub_info in portal_hubs.items():
            hub_faction = hub_info.get("faction", "neutral").lower()
            if hub_faction != "neutral" and hub_faction != char_faction:
                continue

            hub_id = self._zone_name_to_id.get(hub_name)
            if not hub_id:
                continue

            for dest_name in hub_info.get("portals_to", []):
                dest_id = self._zone_name_to_id.get(dest_name)
                if dest_id:
                    self._set_edge(hub_id, dest_id, COST_PORTAL)
                    # Return portal (most hubs have bidirectional portals)
                    if dest_name in portal_hubs:
                        self._set_edge(dest_id, hub_id, COST_PORTAL)

        # 4. Transport links (boats/zeppelins)
        for link in data.get("transport_links", []):
            from_id = self._zone_name_to_id.get(link["from"])
            to_id = self._zone_name_to_id.get(link["to"])
            cost = link.get("cost", COST_BOAT_ZEPPELIN)
            if from_id and to_id:
                self._set_edge(from_id, to_id, cost)
                self._set_edge(to_id, from_id, cost)

        # 5. Hearthstone shortcut — every zone connects to faction capital cheaply
        capital = (
            self._zone_name_to_id.get("Stormwind City")
            if char_faction == "alliance"
            else self._zone_name_to_id.get("Orgrimmar")
        )
        if capital:
            for zid in self._zone_name_to_id.values():
                if zid != capital:
                    # Can always hearth back to capital
                    current = self._adj.get(zid, {}).get(capital, float("inf"))
                    if COST_HEARTHSTONE_PORTAL < current:
                        self._set_edge(zid, capital, COST_HEARTHSTONE_PORTAL)

        # Cache in Redis
        await self._cache_graph()
        self._loaded = True

        logger.info(
            "Zone graph built: %d zones, character=%s",
            len(self._zone_name_to_id),
            character.name,
        )

    def _set_edge(self, from_id: str, to_id: str, cost: float) -> None:
        """Set edge, keeping the cheaper cost if one already exists."""
        existing = self._adj[from_id].get(to_id, float("inf"))
        if cost < existing:
            self._adj[from_id][to_id] = cost

    async def _cache_graph(self) -> None:
        serialized = json.dumps(dict(self._adj))
        await self._redis.set(GRAPH_CACHE_KEY, serialized, ex=GRAPH_CACHE_TTL)

    async def _load_cached_graph(self) -> bool:
        cached = await self._redis.get(GRAPH_CACHE_KEY)
        if cached:
            self._adj = defaultdict(dict, json.loads(cached))
            self._loaded = True
            return True
        return False

    async def travel_cost(
        self,
        zone_a_id: str,
        zone_b_id: str,
        character: Character,
    ) -> float:
        """Shortest path cost between two zones using Dijkstra's algorithm."""
        za = str(zone_a_id)
        zb = str(zone_b_id)

        if za == zb:
            return COST_SAME_ZONE

        # Check per-pair cache
        cache_key = f"router:travel:{character.id}:{za}:{zb}"
        cached = await self._redis.get(cache_key)
        if cached is not None:
            return float(cached)

        cost = self._dijkstra(za, zb)

        # Cache the result
        await self._redis.set(cache_key, str(cost), ex=GRAPH_CACHE_TTL)
        return cost

    def _dijkstra(self, start: str, end: str) -> float:
        """Run Dijkstra's shortest path on the adjacency list."""
        dist: dict[str, float] = {start: 0.0}
        heap: list[tuple[float, str]] = [(0.0, start)]
        visited: set[str] = set()

        while heap:
            d, node = heapq.heappop(heap)
            if node == end:
                return d
            if node in visited:
                continue
            visited.add(node)

            for neighbor, weight in self._adj.get(node, {}).items():
                new_dist = d + weight
                if new_dist < dist.get(neighbor, float("inf")):
                    dist[neighbor] = new_dist
                    heapq.heappush(heap, (new_dist, neighbor))

        # No path found
        return COST_FLYING_MISSING

    async def nearest_zone(
        self,
        from_zone_id: str,
        candidate_zone_ids: list[str],
        character: Character,
    ) -> str | None:
        """Return the candidate zone_id with the lowest travel cost from from_zone."""
        if not candidate_zone_ids:
            return None

        best_id: str | None = None
        best_cost = float("inf")

        for cid in candidate_zone_ids:
            cost = await self.travel_cost(from_zone_id, cid, character)
            if cost < best_cost:
                best_cost = cost
                best_id = cid

        return best_id
