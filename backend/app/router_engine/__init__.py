"""Router engine — achievement route optimization library.

This is a library called from FastAPI handlers and Celery tasks.
It contains no LLM calls — LLM enrichment feeds data into the engine.
"""

from app.router_engine.constraint_filter import (
    BlockedAchievement,
    BlockReason,
    ConstraintFilter,
    FilterResult,
)
from app.router_engine.dependency_resolver import (
    AchievementNode,
    CycleBreak,
    DependencyResolver,
    MetaGroup,
    ResolvedOrder,
)
from app.router_engine.geographic_clusterer import GeographicClusterer, ZoneCluster
from app.router_engine.reoptimizer import RateLimitError, Reoptimizer, ReoptimizeResult
from app.router_engine.route_assembler import RouteAssembler
from app.router_engine.seasonal_override import (
    CalendarEntry,
    SeasonalOverride,
    SeasonalResult,
    SeasonalStop,
    UpcomingEvent,
)
from app.router_engine.session_structurer import RouteStop as SessionRouteStop, Session, SessionStructurer
from app.router_engine.zone_graph import ZoneGraph

__all__ = [
    # Constraint Filter
    "ConstraintFilter",
    "FilterResult",
    "BlockedAchievement",
    "BlockReason",
    # Dependency Resolver
    "DependencyResolver",
    "ResolvedOrder",
    "AchievementNode",
    "MetaGroup",
    "CycleBreak",
    # Zone Graph
    "ZoneGraph",
    # Geographic Clusterer
    "GeographicClusterer",
    "ZoneCluster",
    # Session Structurer
    "SessionStructurer",
    "Session",
    "SessionRouteStop",
    # Seasonal Override
    "SeasonalOverride",
    "SeasonalResult",
    "SeasonalStop",
    "UpcomingEvent",
    "CalendarEntry",
    # Route Assembler
    "RouteAssembler",
    # Reoptimizer
    "Reoptimizer",
    "ReoptimizeResult",
    "RateLimitError",
]
