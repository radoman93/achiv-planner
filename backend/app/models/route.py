from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, Boolean, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Route(Base, TimestampMixin):
    __tablename__ = "routes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    total_estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    session_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    solo_only: Mapped[bool | None] = mapped_column(Boolean)
    archived_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    stops = relationship(
        "RouteStop",
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="(RouteStop.session_number, RouteStop.sequence_order)",
    )

    def __repr__(self) -> str:
        return f"<Route id={self.id} mode={self.mode!r} status={self.status!r}>"


class RouteStop(Base):
    __tablename__ = "route_stops"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    route_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    achievement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False
    )
    session_number: Mapped[int | None] = mapped_column(Integer)
    sequence_order: Mapped[int | None] = mapped_column(Integer)
    zone_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    confidence_tier: Mapped[str | None] = mapped_column(String(50))
    guide_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("guides.id", ondelete="SET NULL"))
    is_seasonal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    days_remaining: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    route = relationship("Route", back_populates="stops")
    achievement = relationship("Achievement")
    zone = relationship("Zone")
    guide = relationship("Guide")
    steps = relationship(
        "RouteStep",
        back_populates="route_stop",
        cascade="all, delete-orphan",
        order_by="RouteStep.sequence_order",
    )

    def __repr__(self) -> str:
        return f"<RouteStop id={self.id} seq={self.sequence_order}>"


class RouteStep(Base):
    __tablename__ = "route_steps"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    route_stop_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("route_stops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_order: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    step_type: Mapped[str | None] = mapped_column(String(50))
    location: Mapped[str | None] = mapped_column(String(255))
    source_reference: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    route_stop = relationship("RouteStop", back_populates="steps")

    def __repr__(self) -> str:
        return f"<RouteStep id={self.id} seq={self.sequence_order}>"
