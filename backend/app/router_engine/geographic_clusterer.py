"""Geographic clusterer — groups achievements by zone and sequences clusters by travel cost."""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from dataclasses import dataclass, field

from app.models.achievement import Achievement
from app.models.user import Character
from app.models.zone import Zone
from app.router_engine.dependency_resolver import AchievementNode, ResolvedOrder
from app.router_engine.zone_graph import ZoneGraph

logger = logging.getLogger(__name__)

# Faction → default capital zone name
FACTION_CAPITALS = {
    "alliance": "Stormwind City",
    "horde": "Orgrimmar",
}

_TWO_OPT_ITERATIONS = 200


@dataclass
class ZoneCluster:
    zone: Zone | None
    achievements: list[Achievement] = field(default_factory=list)
    estimated_minutes: int = 0
    entry_travel_cost: float = 0.0
    exit_zone_id: str = ""


class GeographicClusterer:
    """Groups achievements by zone and sequences clusters for minimal travel."""

    async def cluster(
        self,
        resolved_order: ResolvedOrder,
        character: Character,
        zone_graph: ZoneGraph,
        starting_zone_id: str | None = None,
    ) -> list[ZoneCluster]:
        if not resolved_order.ordered:
            return []

        # Build node lookup and dependency index
        node_map: dict[str, AchievementNode] = {
            str(n.achievement.id): n for n in resolved_order.ordered
        }

        # Step 1: Group by zone (with instance grouping)
        clusters = self._group_by_zone(resolved_order.ordered)

        if not clusters:
            return []

        # Step 2: Build cluster-level dependency partial ordering
        cluster_deps = self._build_cluster_deps(clusters, node_map)

        # Step 3: Nearest-neighbor sequencing
        start_id = starting_zone_id or self._default_start(character, zone_graph)
        sequence = await self._nearest_neighbor(
            clusters, cluster_deps, zone_graph, character, start_id
        )

        # Step 4: 2-opt improvement
        sequence = await self._two_opt(
            sequence, cluster_deps, zone_graph, character
        )

        # Step 5: Order achievements within each cluster
        self._order_within_clusters(sequence, node_map)

        # Compute entry travel costs
        await self._compute_entry_costs(sequence, zone_graph, character, start_id)

        logger.info("Geographic clusterer: %d clusters from %d achievements",
                     len(sequence), len(resolved_order.ordered))
        return sequence

    # ------------------------------------------------------------------
    # Step 1: Group by zone
    # ------------------------------------------------------------------

    def _group_by_zone(
        self, nodes: list[AchievementNode]
    ) -> list[ZoneCluster]:
        # Group by instance_name first (from guide processed_content), then zone_id
        instance_groups: dict[str, list[Achievement]] = defaultdict(list)
        zone_groups: dict[str, list[Achievement]] = defaultdict(list)
        zone_objs: dict[str, Zone | None] = {}
        unknown: list[Achievement] = []

        for node in nodes:
            ach = node.achievement
            # Check for instance grouping via guide data
            instance_name = self._get_instance_name(ach)

            if instance_name:
                instance_groups[instance_name].append(ach)
            elif ach.zone_id:
                zid = str(ach.zone_id)
                zone_groups[zid].append(ach)
                if zid not in zone_objs:
                    zone_objs[zid] = ach.zone if hasattr(ach, "zone") else None
            else:
                unknown.append(ach)

        clusters: list[ZoneCluster] = []

        # Instance-based clusters
        for inst_name, achs in instance_groups.items():
            # Use the zone of the first achievement as representative
            representative_zone = None
            exit_id = ""
            for a in achs:
                if a.zone_id:
                    representative_zone = a.zone if hasattr(a, "zone") else None
                    exit_id = str(a.zone_id)
                    break
            clusters.append(
                ZoneCluster(
                    zone=representative_zone,
                    achievements=achs,
                    estimated_minutes=sum(a.estimated_minutes or 0 for a in achs),
                    exit_zone_id=exit_id,
                )
            )

        # Zone-based clusters
        for zid, achs in zone_groups.items():
            clusters.append(
                ZoneCluster(
                    zone=zone_objs.get(zid),
                    achievements=achs,
                    estimated_minutes=sum(a.estimated_minutes or 0 for a in achs),
                    exit_zone_id=zid,
                )
            )

        # Unknown zone cluster (appended at end)
        if unknown:
            clusters.append(
                ZoneCluster(
                    zone=None,
                    achievements=unknown,
                    estimated_minutes=sum(a.estimated_minutes or 0 for a in unknown),
                    exit_zone_id="",
                )
            )

        return clusters

    def _get_instance_name(self, ach: Achievement) -> str | None:
        """Extract instance_name from guide processed_content if available."""
        if not hasattr(ach, "guides") or not ach.guides:
            return None
        for guide in ach.guides:
            if guide.processed_content and isinstance(guide.processed_content, dict):
                inst = guide.processed_content.get("instance_name")
                if inst:
                    return inst
        return None

    # ------------------------------------------------------------------
    # Step 2: Cluster-level dependency graph
    # ------------------------------------------------------------------

    def _build_cluster_deps(
        self,
        clusters: list[ZoneCluster],
        node_map: dict[str, AchievementNode],
    ) -> dict[int, set[int]]:
        """Returns {cluster_idx: set of cluster_idxs that must come before it}."""
        # Map achievement_id → cluster index
        ach_to_cluster: dict[str, int] = {}
        for idx, cl in enumerate(clusters):
            for ach in cl.achievements:
                ach_to_cluster[str(ach.id)] = idx

        deps: dict[int, set[int]] = defaultdict(set)
        for idx, cl in enumerate(clusters):
            for ach in cl.achievements:
                aid = str(ach.id)
                node = node_map.get(aid)
                if not node:
                    continue
                for req_id in node.requires:
                    req_cluster = ach_to_cluster.get(req_id)
                    if req_cluster is not None and req_cluster != idx:
                        deps[idx].add(req_cluster)

        return deps

    def _respects_deps(
        self,
        sequence: list[int],
        cluster_deps: dict[int, set[int]],
    ) -> bool:
        """Check if a sequence respects all cluster dependencies."""
        position = {idx: pos for pos, idx in enumerate(sequence)}
        for cl_idx, prereqs in cluster_deps.items():
            if cl_idx not in position:
                continue
            for prereq in prereqs:
                if prereq not in position:
                    continue
                if position[prereq] > position[cl_idx]:
                    return False
        return True

    # ------------------------------------------------------------------
    # Step 3: Nearest-neighbor sequencing
    # ------------------------------------------------------------------

    def _default_start(self, character: Character, zone_graph: ZoneGraph) -> str:
        faction = (character.faction or "alliance").lower()
        capital_name = FACTION_CAPITALS.get(faction, "Stormwind City")
        return zone_graph._zone_name_to_id.get(capital_name, "")

    async def _nearest_neighbor(
        self,
        clusters: list[ZoneCluster],
        cluster_deps: dict[int, set[int]],
        zone_graph: ZoneGraph,
        character: Character,
        start_zone_id: str,
    ) -> list[ZoneCluster]:
        n = len(clusters)
        visited = [False] * n
        completed: set[int] = set()
        sequence: list[int] = []
        current_zone = start_zone_id

        for _ in range(n):
            best_idx = -1
            best_cost = float("inf")

            for i in range(n):
                if visited[i]:
                    continue
                # Check dependency: all prereqs must be completed
                prereqs = cluster_deps.get(i, set())
                if not prereqs.issubset(completed):
                    continue

                zone_id = clusters[i].exit_zone_id
                if not zone_id or not current_zone:
                    cost = 15.0  # default cross-continent
                else:
                    cost = await zone_graph.travel_cost(current_zone, zone_id, character)

                if cost < best_cost:
                    best_cost = cost
                    best_idx = i

            if best_idx == -1:
                # Pick first unvisited (fallback for dependency deadlock edge case)
                for i in range(n):
                    if not visited[i]:
                        best_idx = i
                        break
                if best_idx == -1:
                    break

            visited[best_idx] = True
            completed.add(best_idx)
            sequence.append(best_idx)
            current_zone = clusters[best_idx].exit_zone_id

        return [clusters[i] for i in sequence]

    # ------------------------------------------------------------------
    # Step 4: 2-opt improvement
    # ------------------------------------------------------------------

    async def _two_opt(
        self,
        clusters: list[ZoneCluster],
        cluster_deps: dict[int, set[int]],
        zone_graph: ZoneGraph,
        character: Character,
    ) -> list[ZoneCluster]:
        if len(clusters) < 4:
            return clusters

        # Work with indices into the current list
        n = len(clusters)
        # Build index mapping for dependency checks
        original_indices = list(range(n))

        # Remap deps to use current list positions
        ach_to_orig: dict[str, int] = {}
        for i, cl in enumerate(clusters):
            for ach in cl.achievements:
                ach_to_orig[str(ach.id)] = i

        total_before = await self._total_travel_cost(clusters, zone_graph, character)

        rng = random.Random(42)  # deterministic for reproducibility
        for _ in range(_TWO_OPT_ITERATIONS):
            i = rng.randint(0, n - 2)
            j = rng.randint(i + 1, min(i + 10, n - 1))  # limit reversal span

            # Try reversing segment [i+1 .. j]
            new_clusters = clusters[:i + 1] + clusters[i + 1:j + 1][::-1] + clusters[j + 1:]

            # Check dependencies
            new_idx_map = {id(cl): pos for pos, cl in enumerate(new_clusters)}
            valid = True
            for ci, cl in enumerate(new_clusters):
                for ach in cl.achievements:
                    aid = str(ach.id)
                    # This is a simplified check — full check deferred to _respects_deps
                    pass

            # Full dependency check using original cluster identity
            orig_sequence = []
            cl_id_to_orig = {id(clusters[k]): k for k in range(n)}
            for cl in new_clusters:
                orig_sequence.append(cl_id_to_orig.get(id(cl), 0))

            if not self._respects_deps(orig_sequence, cluster_deps):
                continue

            new_cost = await self._total_travel_cost(new_clusters, zone_graph, character)
            if new_cost < total_before:
                clusters = new_clusters
                total_before = new_cost

        total_after = await self._total_travel_cost(clusters, zone_graph, character)
        if total_before > 0:
            improvement = ((total_before - total_after) / total_before) * 100
            logger.info("2-opt improvement: %.1f%% travel cost reduction", improvement)

        return clusters

    async def _total_travel_cost(
        self,
        clusters: list[ZoneCluster],
        zone_graph: ZoneGraph,
        character: Character,
    ) -> float:
        total = 0.0
        for i in range(1, len(clusters)):
            prev_zone = clusters[i - 1].exit_zone_id
            curr_zone = clusters[i].exit_zone_id
            if prev_zone and curr_zone:
                total += await zone_graph.travel_cost(prev_zone, curr_zone, character)
            else:
                total += 15.0
        return total

    # ------------------------------------------------------------------
    # Step 5: Order within clusters
    # ------------------------------------------------------------------

    def _order_within_clusters(
        self,
        clusters: list[ZoneCluster],
        node_map: dict[str, AchievementNode],
    ) -> None:
        """Within each cluster: dependency order first, then quick wins (lowest estimated_minutes)."""
        for cl in clusters:
            # Build local dependency ordering
            local_ids = {str(a.id) for a in cl.achievements}
            # Sort: depth ascending (prerequisites first), then estimated_minutes ascending
            cl.achievements.sort(
                key=lambda a: (
                    node_map.get(str(a.id), AchievementNode(achievement=a)).depth,
                    a.estimated_minutes or 0,
                )
            )

    # ------------------------------------------------------------------
    # Compute entry costs
    # ------------------------------------------------------------------

    async def _compute_entry_costs(
        self,
        clusters: list[ZoneCluster],
        zone_graph: ZoneGraph,
        character: Character,
        start_zone_id: str,
    ) -> None:
        prev_zone = start_zone_id
        for cl in clusters:
            if prev_zone and cl.exit_zone_id:
                cl.entry_travel_cost = await zone_graph.travel_cost(
                    prev_zone, cl.exit_zone_id, character
                )
            else:
                cl.entry_travel_cost = 0.0
            prev_zone = cl.exit_zone_id
