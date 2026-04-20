"""Dependency resolver — topological ordering with cycle detection and meta-achievement grouping."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from uuid import UUID

from app.models.achievement import Achievement, AchievementDependency

logger = logging.getLogger(__name__)


@dataclass
class AchievementNode:
    achievement: Achievement
    depth: int = 0  # 0 = no dependencies, higher = deeper in graph
    required_by: list[str] = field(default_factory=list)  # achievement IDs that require this one
    requires: list[str] = field(default_factory=list)  # achievement IDs this one requires
    soft_requires: list[str] = field(default_factory=list)  # soft dependency hints for clusterer


@dataclass
class MetaGroup:
    meta_achievement: Achievement
    children: list[Achievement] = field(default_factory=list)


@dataclass
class CycleBreak:
    achievement_a_id: str
    achievement_b_id: str
    broken_edge: str  # which direction was removed
    reason: str


@dataclass
class ResolvedOrder:
    ordered: list[AchievementNode] = field(default_factory=list)
    meta_groups: list[MetaGroup] = field(default_factory=list)
    cycle_breaks: list[CycleBreak] = field(default_factory=list)


class DependencyResolver:
    """Topological sort via Kahn's algorithm with cycle detection and breaking."""

    def resolve(
        self,
        achievements: list[Achievement],
        dependencies: list[AchievementDependency],
    ) -> ResolvedOrder:
        if not achievements:
            return ResolvedOrder()

        ach_by_id: dict[str, Achievement] = {str(a.id): a for a in achievements}
        pool_ids = set(ach_by_id.keys())

        # Separate hard and soft dependencies
        hard_deps: list[AchievementDependency] = []
        soft_deps: list[AchievementDependency] = []
        for dep in dependencies:
            req_id = str(dep.required_achievement_id)
            dep_id = str(dep.dependent_achievement_id)
            if req_id not in pool_ids or dep_id not in pool_ids:
                continue
            if dep.dependency_type == "soft":
                soft_deps.append(dep)
            else:
                hard_deps.append(dep)

        # Build adjacency structures
        adj: dict[str, list[str]] = defaultdict(list)  # required → [dependents]
        reverse_adj: dict[str, list[str]] = defaultdict(list)  # dependent → [required]
        edge_confidence: dict[tuple[str, str], float] = {}

        for dep in hard_deps:
            req_id = str(dep.required_achievement_id)
            dep_id = str(dep.dependent_achievement_id)
            adj[req_id].append(dep_id)
            reverse_adj[dep_id].append(req_id)
            edge_confidence[(req_id, dep_id)] = dep.confidence

        # Run Kahn's algorithm
        ordered_ids, cycle_nodes = self._kahns_sort(pool_ids, adj, reverse_adj, ach_by_id)

        # Handle cycles
        cycle_breaks: list[CycleBreak] = []
        if cycle_nodes:
            logger.warning("Detected %d nodes in dependency cycles", len(cycle_nodes))
            extra_ordered, breaks = self._break_cycles(
                cycle_nodes, adj, reverse_adj, edge_confidence, ach_by_id
            )
            ordered_ids.extend(extra_ordered)
            cycle_breaks.extend(breaks)

        # Compute depth and relationships for each node
        depth_map = self._compute_depths(ordered_ids, reverse_adj)

        # Build soft dependency map
        soft_map: dict[str, list[str]] = defaultdict(list)
        for dep in soft_deps:
            dep_id = str(dep.dependent_achievement_id)
            req_id = str(dep.required_achievement_id)
            soft_map[dep_id].append(req_id)

        nodes: list[AchievementNode] = []
        for aid in ordered_ids:
            ach = ach_by_id[aid]
            nodes.append(
                AchievementNode(
                    achievement=ach,
                    depth=depth_map.get(aid, 0),
                    required_by=[x for x in adj.get(aid, []) if x in pool_ids],
                    requires=[x for x in reverse_adj.get(aid, []) if x in pool_ids],
                    soft_requires=soft_map.get(aid, []),
                )
            )

        # Add any achievements that had no dependency edges at all
        ordered_set = set(ordered_ids)
        for aid in pool_ids - ordered_set:
            ach = ach_by_id[aid]
            nodes.append(
                AchievementNode(
                    achievement=ach,
                    depth=0,
                    required_by=[],
                    requires=[],
                    soft_requires=soft_map.get(aid, []),
                )
            )

        # Identify meta-achievements and group them
        meta_groups = self._identify_meta_groups(ach_by_id, reverse_adj, pool_ids)

        logger.info(
            "Dependency resolver: %d ordered, %d meta groups, %d cycle breaks",
            len(nodes),
            len(meta_groups),
            len(cycle_breaks),
        )

        return ResolvedOrder(
            ordered=nodes,
            meta_groups=meta_groups,
            cycle_breaks=cycle_breaks,
        )

    # ------------------------------------------------------------------
    # Kahn's topological sort
    # ------------------------------------------------------------------

    def _kahns_sort(
        self,
        pool_ids: set[str],
        adj: dict[str, list[str]],
        reverse_adj: dict[str, list[str]],
        ach_by_id: dict[str, Achievement],
    ) -> tuple[list[str], set[str]]:
        in_degree: dict[str, int] = {aid: 0 for aid in pool_ids}
        for aid in pool_ids:
            for dep_id in adj.get(aid, []):
                if dep_id in pool_ids:
                    in_degree[dep_id] = in_degree.get(dep_id, 0) + 1

        # Priority queue: prefer lower staleness_score (fresher data) as tiebreaker
        queue: deque[str] = deque()
        zero_nodes = [
            aid for aid in pool_ids if in_degree.get(aid, 0) == 0
        ]
        zero_nodes.sort(key=lambda x: ach_by_id[x].staleness_score)
        queue.extend(zero_nodes)

        result: list[str] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            dependents = [d for d in adj.get(node, []) if d in pool_ids]
            dependents.sort(key=lambda x: ach_by_id[x].staleness_score)
            for dep_id in dependents:
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)

        cycle_nodes = pool_ids - set(result) if len(result) < len(pool_ids) else set()
        return result, cycle_nodes

    # ------------------------------------------------------------------
    # Cycle breaking — remove lowest-confidence edge iteratively
    # ------------------------------------------------------------------

    def _break_cycles(
        self,
        cycle_nodes: set[str],
        adj: dict[str, list[str]],
        reverse_adj: dict[str, list[str]],
        edge_confidence: dict[tuple[str, str], float],
        ach_by_id: dict[str, Achievement],
    ) -> tuple[list[str], list[CycleBreak]]:
        breaks: list[CycleBreak] = []
        remaining = set(cycle_nodes)

        # Work on copies to avoid mutating the originals
        local_adj: dict[str, list[str]] = {
            k: [v for v in vs if v in remaining]
            for k, vs in adj.items()
            if k in remaining
        }
        local_rev: dict[str, list[str]] = {
            k: [v for v in vs if v in remaining]
            for k, vs in reverse_adj.items()
            if k in remaining
        }

        max_iterations = len(remaining) * 2
        iteration = 0

        while remaining and iteration < max_iterations:
            iteration += 1

            # Find the lowest-confidence edge among remaining nodes
            min_conf = float("inf")
            min_edge: tuple[str, str] | None = None
            for src in remaining:
                for dst in local_adj.get(src, []):
                    if dst in remaining:
                        conf = edge_confidence.get((src, dst), 1.0)
                        if conf < min_conf:
                            min_conf = conf
                            min_edge = (src, dst)

            if min_edge is None:
                break

            # Remove the edge
            src, dst = min_edge
            if dst in local_adj.get(src, []):
                local_adj[src].remove(dst)
            if src in local_rev.get(dst, []):
                local_rev[dst].remove(src)

            breaks.append(
                CycleBreak(
                    achievement_a_id=src,
                    achievement_b_id=dst,
                    broken_edge=f"{src} -> {dst}",
                    reason="lowest confidence edge in cycle",
                )
            )

            # Re-run Kahn's on remaining
            ordered, still_cycling = self._kahns_sort(
                remaining, local_adj, local_rev, ach_by_id
            )
            if ordered:
                remaining -= set(ordered)
                # Update local structures
                local_adj = {
                    k: [v for v in vs if v in remaining]
                    for k, vs in local_adj.items()
                    if k in remaining
                }
                local_rev = {
                    k: [v for v in vs if v in remaining]
                    for k, vs in local_rev.items()
                    if k in remaining
                }

            if not still_cycling:
                break

        # Any stragglers just get appended
        final_ordered = list(remaining)
        return final_ordered if not remaining else final_ordered, breaks

    # ------------------------------------------------------------------
    # Depth computation
    # ------------------------------------------------------------------

    def _compute_depths(
        self,
        ordered_ids: list[str],
        reverse_adj: dict[str, list[str]],
    ) -> dict[str, int]:
        depth: dict[str, int] = {}
        for aid in ordered_ids:
            prereqs = reverse_adj.get(aid, [])
            if not prereqs:
                depth[aid] = 0
            else:
                depth[aid] = max(depth.get(p, 0) for p in prereqs) + 1
        return depth

    # ------------------------------------------------------------------
    # Meta-achievement identification
    # ------------------------------------------------------------------

    def _identify_meta_groups(
        self,
        ach_by_id: dict[str, Achievement],
        reverse_adj: dict[str, list[str]],
        pool_ids: set[str],
    ) -> list[MetaGroup]:
        # Count how many children point to each parent (parent = dependent_achievement)
        # reverse_adj: dependent → [required_achievements]
        # We need: for each achievement that is a dependent, count its required children
        # But meta = achievement that has >3 children depending on it, OR is_meta flag

        # Build forward map: parent_id → [children] where children must complete before parent
        parent_children: dict[str, list[str]] = defaultdict(list)
        for dep_id, req_ids in reverse_adj.items():
            if dep_id in pool_ids:
                for req_id in req_ids:
                    if req_id in pool_ids:
                        parent_children[dep_id].append(req_id)

        meta_groups: list[MetaGroup] = []
        seen_metas: set[str] = set()

        for aid, ach in ach_by_id.items():
            is_meta = ach.is_meta or len(parent_children.get(aid, [])) > 3
            if is_meta and aid not in seen_metas:
                children = [
                    ach_by_id[cid]
                    for cid in parent_children.get(aid, [])
                    if cid in ach_by_id
                ]
                if children:
                    meta_groups.append(MetaGroup(meta_achievement=ach, children=children))
                    seen_metas.add(aid)

        return meta_groups
