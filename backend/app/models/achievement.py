from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Achievement(Base, TimestampMixin):
    __tablename__ = "achievements"
    __table_args__ = (UniqueConstraint("blizzard_id", name="uq_achievements_blizzard_id"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    blizzard_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    how_to_complete: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(255))
    subcategory: Mapped[str | None] = mapped_column(String(255))
    expansion: Mapped[str | None] = mapped_column(String(100))
    patch_introduced: Mapped[str | None] = mapped_column(String(50))
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_account_wide: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_meta: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_legacy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_faction_specific: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    faction: Mapped[str | None] = mapped_column(String(50))
    is_class_restricted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_classes: Mapped[dict | None] = mapped_column(JSONB)
    zone_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    requires_flying: Mapped[bool | None] = mapped_column(Boolean)
    requires_group: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    min_group_size: Mapped[int | None] = mapped_column(Integer)
    is_seasonal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seasonal_event: Mapped[str | None] = mapped_column(String(255))
    seasonal_start: Mapped[date | None] = mapped_column(Date)
    seasonal_end: Mapped[date | None] = mapped_column(Date)
    last_scraped_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    staleness_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    manually_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    zone = relationship("Zone", back_populates="achievements")
    criteria = relationship("AchievementCriteria", back_populates="achievement", cascade="all, delete-orphan")
    guides = relationship("Guide", back_populates="achievement", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="achievement", cascade="all, delete-orphan")
    dependencies = relationship(
        "AchievementDependency",
        foreign_keys="AchievementDependency.required_achievement_id",
        back_populates="required_achievement",
        cascade="all, delete-orphan",
    )
    dependents = relationship(
        "AchievementDependency",
        foreign_keys="AchievementDependency.dependent_achievement_id",
        back_populates="dependent_achievement",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Achievement id={self.id} name={self.name!r}>"


class AchievementCriteria(Base, TimestampMixin):
    __tablename__ = "achievement_criteria"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    achievement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blizzard_criteria_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    required_amount: Mapped[int | None] = mapped_column(Integer)
    criteria_type: Mapped[str | None] = mapped_column(String(100))

    achievement = relationship("Achievement", back_populates="criteria")

    def __repr__(self) -> str:
        return f"<AchievementCriteria id={self.id} description={self.description!r}>"


class AchievementDependency(Base):
    __tablename__ = "achievement_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "required_achievement_id", "dependent_achievement_id", name="uq_achievement_dependencies_pair"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    required_achievement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False
    )
    dependent_achievement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False
    )
    dependency_type: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    required_achievement = relationship(
        "Achievement", foreign_keys=[required_achievement_id], back_populates="dependencies"
    )
    dependent_achievement = relationship(
        "Achievement", foreign_keys=[dependent_achievement_id], back_populates="dependents"
    )

    def __repr__(self) -> str:
        return f"<AchievementDependency id={self.id} type={self.dependency_type!r}>"
