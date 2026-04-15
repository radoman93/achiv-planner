# Phase 3 — Routing Engine

Depends on: Phase 2 fully complete (enriched achievement data must exist in DB).
Complete all tasks before starting Phase 4.
After each task, verify acceptance criteria and update docs/progress.md.

The routing engine lives in `backend/app/router_engine/` as a Python library.
It is NOT a microservice. It is called directly from FastAPI request handlers and Celery tasks.
LLM enrichment feeds data INTO the engine — the engine itself contains no LLM calls.

---

## TASK 3.1 — Constraint Filter

**File: `backend/app/router_engine/constraint_filter.py`**

**Class: `ConstraintFilter`**

```python
class ConstraintFilter:
    def filter(
        self,
        achievements: list[Achievement],
        character: Character,
        solo_only: bool = False
    ) -> FilterResult
```

**FilterResult dataclass:**
```python
@dataclass
class FilterResult:
    eligible: list[Achievement]
    blocked: list[BlockedAchievement]

@dataclass
class BlockedAchievement:
    achievement: Achievement
    reason: BlockReason
    unlocker: str | None  # What the character needs to do to unblock this

class BlockReason(Enum):
    FLYING_REQUIRED = "flying_required"
    LEVEL_TOO_LOW = "level_too_low"
    WRONG_FACTION = "wrong_faction"
    GROUP_REQUIRED = "group_required"
    LEGACY_UNOBTAINABLE = "legacy_unobtainable"
    PREREQUISITE_MISSING = "prerequisite_missing"
```

**Filter rules (apply in this order, first match wins):**

1. **Legacy gate:** If `achievement.is_legacy = True` → blocked with `LEGACY_UNOBTAINABLE`, unlocker = None

2. **Faction gate:** If `achievement.is_faction_specific = True` and `achievement.faction != character.faction` → blocked with `WRONG_FACTION`, unlocker = None

3. **Level gate:** If `achievement` has minimum level (derive from expansion — BfA requires 50+, Shadowlands 60+, Dragonflight 70+, TWW 80+) and `character.level < minimum` → blocked with `LEVEL_TOO_LOW`, unlocker = f"Reach level {minimum}"

4. **Flying gate:** If `achievement.requires_flying = True`:
   - Check `character.flying_unlocked` dict for the achievement's expansion
   - If not unlocked → blocked with `FLYING_REQUIRED`, unlocker = f"Complete Pathfinder achievement for {expansion}"

5. **Group gate:** If `solo_only = True` and `achievement.requires_group = True` → blocked with `GROUP_REQUIRED`, unlocker = "Find a group or disable solo-only mode"

6. **No zone data:** If achievement has no zone and no guide with steps → do NOT block, but tag as `low_confidence` on the achievement object (this is a data quality issue, not a constraint)

**Acceptance:**
- A character without Shadowlands flying cannot access flying-required Shadowlands achievements
- A Horde character cannot see Alliance-only achievements in eligible pool
- A level 60 character has BfA achievements eligible but TWW achievements blocked
- BlockedAchievement.unlocker contains human-readable instructions for all non-null cases
- Legacy achievements always blocked regardless of character state
- Solo-only filter correctly removes group-required achievements

---

## TASK 3.2 — Dependency Resolver

**File: `backend/app/router_engine/dependency_resolver.py`**

**Class: `DependencyResolver`**

```python
class DependencyResolver:
    def resolve(
        self,
        achievements: list[Achievement],
        dependencies: list[AchievementDependency]
    ) -> ResolvedOrder
```

**ResolvedOrder dataclass:**
```python
@dataclass
class ResolvedOrder:
    ordered: list[AchievementNode]
    meta_groups: list[MetaGroup]
    cycle_breaks: list[CycleBreak]

@dataclass
class AchievementNode:
    achievement: Achievement
    depth: int  # 0 = no dependencies, higher = deeper in graph
    required_by: list[str]  # achievement IDs that require this one
    requires: list[str]  # achievement IDs this one requires

@dataclass
class MetaGroup:
    meta_achievement: Achievement
    children: list[Achievement]  # must all complete before meta

@dataclass
class CycleBreak:
    achievement_a_id: str
    achievement_b_id: str
    broken_edge: str  # which direction was removed
    reason: str  # "lowest confidence edge in cycle"
```

**Algorithm — Kahn's topological sort:**
1. Build adjacency list from `dependencies` (hard dependencies only — ignore soft)
2. Calculate in-degree for each node
3. Initialize queue with all zero in-degree nodes
4. While queue not empty:
   - Pop node with lowest `staleness_score` (prefer fresh data first, as a tiebreaker)
   - Add to result
   - Reduce in-degree of all dependents
   - Add newly zero in-degree nodes to queue
5. If result length < input length: cycles detected (see below)

**Cycle detection and breaking:**
- After Kahn's, identify nodes not in result (these are in cycles)
- For each cycle: find the `AchievementDependency` with lowest `confidence` score — this is the most uncertain relationship
- Remove that edge from the graph
- Re-run Kahn's on the remaining cycle nodes
- Repeat until no cycles remain
- Record each break in `cycle_breaks`

**Meta-achievement identification:**
- An achievement is a meta if `achievement.is_meta = True` OR if it appears as `dependent_achievement_id` in more than 3 dependency rows with children all in the current pool
- Group meta + all its required children into a `MetaGroup`
- In the `ordered` list, children always appear before their meta parent

**Soft dependency handling:**
- Soft dependencies are NOT edges in the graph (don't affect ordering)
- They are stored on `AchievementNode.soft_requires` as hints to the clusterer

**Acceptance:**
- Correctly orders a 10-achievement chain where A→B→C→D (A must be first, D last)
- Cycle detection triggers on a manually created A→B→A cycle
- Cycle break removes the lower-confidence edge
- Meta-achievements always appear after all their children in output
- Achievements with no dependencies have `depth = 0`
- Performance: resolves 1000 achievements in under 1 second

---

## TASK 3.3 — Zone Connectivity Graph

**File: `backend/app/router_engine/zone_graph.py`**

**Class: `ZoneGraph`**

Builds and caches a weighted graph of travel costs between all WoW zones.

**Graph structure:**
- Nodes: Zone objects
- Edges: travel cost in minutes (float)
- Stored in Redis as serialized adjacency list (key: `router:zone_graph:v1`)
- Rebuilt when zone data changes or on first call if not cached

**Travel cost rules (encode these as edge weights):**

| Connection Type | Cost (minutes) |
|---|---|
| Same zone | 0 |
| Direct portal from major city | 2 |
| Flight path (same continent) | 8 |
| Flight path (cross-continent) | 15 |
| Boat/zeppelin | 10 |
| Requires flying (character has it) | 5 |
| Requires flying (character doesn't) | 999 (effectively blocked) |
| Hearthstone to capital then portal | 5 |

**Hardcode the major portal/transport connections:**
- Stormwind/Orgrimmar: portals to all major expansion zones
- Dalaran (Legion): portals to many Broken Isles zones
- Oribos: portals to Shadowlands zones
- etc.
Store these as a JSON file at `backend/app/router_engine/data/zone_connections.json` that can be updated without code changes.

**Methods:**

`build_graph(zones: list[Zone], character: Character) -> None`:
- Build the weighted adjacency list
- Account for character's flying status per expansion when calculating costs
- Cache in Redis for 1 hour

`travel_cost(zone_a_id: str, zone_b_id: str, character: Character) -> float`:
- Run Dijkstra's algorithm on cached graph
- Cache individual zone-pair results in Redis (key: `router:travel:{char_id}:{zone_a}:{zone_b}`, TTL: 1 hour)
- Return minutes as float

`nearest_zone(from_zone_id: str, candidate_zone_ids: list[str], character: Character) -> str`:
- Returns the zone_id from candidates with lowest travel_cost from from_zone
- Used by clusterer's nearest-neighbor algorithm

**Acceptance:**
- Stormwind → Northrend zone returns travel cost > 10 minutes
- Stormwind → Elwynn Forest returns 0 (same region)
- Portal connection returns ~2 minutes
- Character without flying in BfA zones gets 999 cost to flying-required zones
- Dijkstra correctly finds shortest path through multi-hop routes
- Graph builds and caches in under 2 seconds for full zone list

---

## TASK 3.4 — Geographic Clusterer

**File: `backend/app/router_engine/geographic_clusterer.py`**

**Class: `GeographicClusterer`**

```python
class GeographicClusterer:
    def cluster(
        self,
        resolved_order: ResolvedOrder,
        character: Character,
        zone_graph: ZoneGraph,
        starting_zone_id: str | None = None  # character's capital city if None
    ) -> list[ZoneCluster]
```

**ZoneCluster dataclass:**
```python
@dataclass
class ZoneCluster:
    zone: Zone
    achievements: list[Achievement]  # ordered within cluster
    estimated_minutes: int  # sum of achievement times + intra-zone travel
    entry_travel_cost: float  # cost to reach this cluster from previous
    exit_zone_id: str  # zone to depart from after completing cluster
```

**Step 1 — Group by zone:**
- Group all achievements by `achievement.zone_id`
- Achievements with null zone get their own "unknown zone" cluster (presented separately)
- Achievements in the same instance (dungeon/raid) get grouped even if their zone differs — use `achievement.instance_name` as a secondary grouping key

**Step 2 — Respect dependency ordering between clusters:**
- Build a cluster-level dependency graph: Cluster A must come before Cluster B if any achievement in A is required by any achievement in B
- This produces a partial ordering of clusters that must be respected

**Step 3 — Nearest-neighbor cluster sequence:**
Starting from `starting_zone_id` (default: character's faction capital):
1. Mark all clusters unvisited
2. Set current = starting zone cluster (or nearest cluster to starting zone)
3. Repeat until all clusters visited:
   a. Find unvisited cluster with lowest `travel_cost(current.exit_zone, candidate.zone)` that doesn't violate dependency ordering
   b. Visit that cluster, set as current
4. This produces an initial sequence

**Step 4 — 2-opt improvement:**
- Run 2-opt on the cluster sequence for exactly 200 iterations
- For each iteration: pick two random non-adjacent positions, reverse the subsequence between them, keep if it reduces total travel cost AND doesn't violate any dependency constraints
- Track total travel cost before and after — log improvement percentage

**Step 5 — Order achievements within each cluster:**
- Within a cluster, order achievements by: dependency order first, then by `estimated_minutes` ascending (quick wins first within the zone)

**Acceptance:**
- Achievements in the same zone are always in the same cluster
- Dependency between clusters is never violated (achievement A always in earlier cluster than achievement that requires A)
- 2-opt produces lower total travel cost than nearest-neighbor alone (verify with before/after logs)
- Clusters with unknown zones appear at end of sequence
- Same-instance achievements grouped correctly regardless of zone assignment
- Performance: clusters 500 achievements across 50 zones in under 3 seconds

---

## TASK 3.5 — Session Structurer

**File: `backend/app/router_engine/session_structurer.py`**

**Class: `SessionStructurer`**

```python
class SessionStructurer:
    def structure(
        self,
        clusters: list[ZoneCluster],
        session_budget_minutes: int,
        partially_completed: dict[str, float]  # achievement_id → % complete
    ) -> list[Session]
```

**Session dataclass:**
```python
@dataclass
class Session:
    session_number: int
    clusters: list[ZoneCluster]
    stops: list[RouteStop]  # flattened achievements in order
    estimated_minutes: int
    primary_zone: Zone  # zone with most achievements in session
    entry_zone: Zone  # first zone in session (should be well-connected)
    is_well_connected: bool  # True if entry zone has portal access
```

**Algorithm:**

1. **Promote partially completed achievements:**
   - Achievements in `partially_completed` with > 0% progress get a priority boost
   - Within their cluster, move them to first position
   - Log which achievements were promoted

2. **Accumulate into sessions:**
   - Walk through ordered clusters
   - Track `session_minutes = 0`
   - For each cluster:
     - Calculate cluster cost: `sum(achievement.estimated_minutes) + intra_cluster_travel + entry_travel_cost`
     - If `session_minutes + cluster_cost <= session_budget`: add cluster to current session, add cost to session_minutes
     - If cluster alone > session_budget: split cluster (only case where cluster is split). Add achievements one by one until budget reached, carry remainder to next session
     - If adding would exceed budget: close current session, start new session with this cluster

3. **Session opener optimization:**
   - For each session's first cluster: if the first cluster is not well-connected (no portal), check if there's a nearby well-connected cluster that could come first without violating dependencies
   - If yes and the swap adds < 5 minutes travel overhead: swap them
   - Mark session `is_well_connected` based on entry cluster

4. **Flatten to stops:**
   - Convert cluster list to flat `stops` list in order
   - Each stop has: achievement, zone, estimated_minutes, session_number, sequence_order

**Acceptance:**
- A 360-minute total route with 120-minute budget produces 3 sessions
- No session exceeds budget by more than 10% (only when a single achievement exceeds budget)
- Cluster boundaries respected — no cluster split across sessions unless it alone exceeds budget
- Partially completed achievements appear first within their cluster
- Well-connected zones preferred as session openers
- Performance: structures 200 achievements into sessions in under 500ms

---

## TASK 3.6 — Seasonal Override Layer

**File: `backend/app/router_engine/seasonal_override.py`**

**Class: `SeasonalOverride`**

```python
class SeasonalOverride:
    def process(
        self,
        all_achievements: list[Achievement],  # full unfiltered eligible pool
        character: Character,
        current_date: date,
        lookahead_days: int = 60
    ) -> SeasonalResult
```

**SeasonalResult dataclass:**
```python
@dataclass
class SeasonalResult:
    active_block: list[SeasonalStop]  # currently open, sorted by urgency
    upcoming_events: list[UpcomingEvent]
    calendar_projection: list[CalendarEntry]

@dataclass
class SeasonalStop:
    achievement: Achievement
    event_name: str
    days_remaining: int
    urgency: str  # 'critical' (<3 days), 'high' (3-7 days), 'normal' (>7 days)
    zone_cluster: ZoneCluster | None  # geographically clustered with other seasonal stops

@dataclass
class UpcomingEvent:
    event_name: str
    opens_at: date
    closes_at: date
    days_until_open: int
    achievement_count: int
    user_completion_pct: float

@dataclass
class CalendarEntry:
    event_name: str
    opens_at: date
    closes_at: date
    achievements: list[Achievement]
    completed_count: int
    total_count: int
```

**Active window detection:**
- Filter `all_achievements` where `is_seasonal = True`
- Check `seasonal_start <= current_date <= seasonal_end`
- Handle year-wrap events (Hallow's End is late October — if month of start > month of end, the event wraps the new year)
- Sort active by `days_remaining` ascending (most urgent first)

**Urgency classification:**
- `critical`: ≤ 3 days remaining — surface prominently in UI
- `high`: 4-7 days remaining
- `normal`: 8+ days remaining

**Geographic clustering of active seasonal:**
- Run a mini version of the geographic clusterer on just the active seasonal achievements
- Group by zone, sequence by travel cost
- Attach resulting ZoneClusters to SeasonalStops

**Upcoming events (lookahead_days window):**
- Find all seasonal events with `seasonal_start` between `current_date + 1` and `current_date + lookahead_days`
- For each event: count achievements, calculate user completion percentage from `user_achievement_state`

**Calendar projection:**
- Generate one CalendarEntry per event in the lookahead window
- Include both upcoming and currently active events
- Sort by opens_at date

**Acceptance:**
- Correctly identifies active achievements on a simulated date mid-Hallow's End (Oct 18-Nov 1)
- Year-wrap events correctly detected
- Days remaining accurate (verified against known event end dates)
- Urgency classification correct for each threshold
- Calendar projection covers 60-day window correctly
- User completion percentage accurate against mock user_achievement_state data

---

## TASK 3.7 — Route Assembler

**File: `backend/app/router_engine/route_assembler.py`**

**Class: `RouteAssembler`**

```python
class RouteAssembler:
    async def assemble(
        self,
        character: Character,
        mode: str,
        filter_result: FilterResult,
        resolved_order: ResolvedOrder,
        sessions: list[Session],
        seasonal_result: SeasonalResult,
        db: AsyncSession
    ) -> Route
```

**Assembly steps:**

1. **Build Route record:**
   - `user_id`, `character_id`, `mode`, `status = 'active'`
   - `total_estimated_minutes` = sum of all session minutes
   - `session_duration_minutes` = character preference
   - `solo_only` = character preference
   - `overall_confidence` = mean of all stop confidence scores
   - Insert to DB, get route_id

2. **Build seasonal block stops:**
   - For each SeasonalStop in `seasonal_result.active_block`:
     - Create RouteStop with `is_seasonal = True`, `days_remaining` set, `session_number = 0` (seasonal block is session 0)
     - Load guide for this achievement — use highest confidence guide
     - Load top 3 comments by combined_score
     - Determine confidence_tier from achievement.confidence_score:
       - ≥ 0.85: 'verified'
       - ≥ 0.65: 'high'
       - ≥ 0.40: 'medium'
       - ≥ 0.20: 'low'
       - < 0.20: 'research_required'
     - Create RouteSteps from guide.steps JSON
     - Insert RouteStop and RouteSteps

3. **Build main route stops:**
   - For each Session, for each stop in session.stops:
     - Create RouteStop with correct session_number, sequence_order
     - Load guide and top 3 comments (same as seasonal above)
     - Assign confidence_tier
     - Create RouteSteps
     - Insert RouteStop and RouteSteps

4. **Build blocked pool:**
   - Store `filter_result.blocked` as JSON on the Route record (`blocked_pool` JSONB column — add this column to routes table migration)
   - Each entry: achievement_id, achievement_name, reason, unlocker

5. **Attach community tips:**
   - For each RouteStop: fetch top 3 comments by combined_score where comment_type IN ('route_tip', 'correction', 'time_estimate')
   - Store as JSON on RouteStop (`community_tips` JSONB column — add to route_stops migration)

6. **Return fully populated Route:**
   - Eagerly load all RouteStops and RouteSteps
   - Return Route ORM object

**Acceptance:**
- Assembler produces a valid Route with stops for a test character with 50 uncompleted achievements
- Seasonal block correctly appears as session_number = 0
- Confidence tiers correctly mapped from scores
- Blocked pool populated with human-readable unlocker messages
- Community tips attached to stops where comments exist
- All data persisted to DB and retrievable by route_id
- Route with 200 stops assembles and persists in under 5 seconds

---

## TASK 3.8 — Reoptimization Handler

**File: `backend/app/router_engine/reoptimizer.py`**

**Class: `Reoptimizer`**

**Method 1: Mark Complete**
```python
async def mark_complete(
    self,
    route_id: str,
    achievement_id: str,
    db: AsyncSession
) -> ReoptimizeResult
```
Steps:
1. Set `route_stop.completed = True`, `completed_at = now()`
2. Check if this achievement is required by any other stops in the route (query dependency graph)
3. For each dependent that was in the blocked pool (not yet in route): check if all its requirements are now complete
4. If a previously blocked achievement is now unblocked: add it to the route in the appropriate session and position (use zone to find correct cluster)
5. Adjust session estimated_minutes for the session this stop was in
6. Return `ReoptimizeResult` with: completed_achievement_id, newly_unblocked (list), sessions_adjusted (list)

**Method 2: Mark Skipped**
```python
async def mark_skipped(
    self,
    route_id: str,
    achievement_id: str,
    db: AsyncSession
) -> ReoptimizeResult
```
Steps:
1. Set `route_stop.skipped = True`
2. Move achievement to a `deferred` pool stored as JSON on Route (`deferred_pool` JSONB column)
3. Adjust session estimated_minutes
4. Do NOT resequence the rest of the route — just remove the stop
5. Return `ReoptimizeResult` with: skipped_achievement_id, session_time_freed (int, minutes)

**Method 3: Full Reoptimize**
```python
async def full_reoptimize(
    self,
    character_id: str,
    mode: str,
    db: AsyncSession
) -> Route
```
Steps:
1. **Rate limit check:** Query Redis for `reoptimize:last:{character_id}` — if exists and < 1 hour ago, raise `RateLimitError` with minutes until next allowed
2. Archive existing active route: set `status = 'archived'`, `archived_at = now()`
3. Load current `user_achievement_state` for character
4. Run full routing pipeline:
   - Load eligible achievements (all uncompleted, not skipped)
   - `ConstraintFilter.filter()`
   - `DependencyResolver.resolve()`
   - `ZoneGraph.build_graph()`
   - `GeographicClusterer.cluster()`
   - `SessionStructurer.structure()`
   - `SeasonalOverride.process()`
   - `RouteAssembler.assemble()`
5. Set Redis key `reoptimize:last:{character_id}` with TTL 3600
6. Return new Route

**ReoptimizeResult dataclass:**
```python
@dataclass
class ReoptimizeResult:
    success: bool
    action: str  # 'completed' | 'skipped' | 'full_reoptimize'
    newly_unblocked: list[str]  # achievement IDs now accessible
    sessions_adjusted: list[int]  # session numbers that changed
    session_time_freed: int  # minutes freed by skip/complete
    new_route: Route | None  # only set for full_reoptimize
```

**Acceptance:**
- Marking an achievement complete correctly removes it from route
- Completing a prerequisite correctly adds its dependent to the route
- Skipping moves achievement to deferred pool without resequencing others
- Full reoptimize rate limit correctly enforced (second call within 1 hour raises error)
- Full reoptimize archives old route and creates new one
- Full reoptimize reflects completed achievements (they don't appear in new route)
