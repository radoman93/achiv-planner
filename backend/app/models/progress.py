from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserAchievementState(Base):
    __tablename__ = "user_achievement_state"
    __table_args__ = (
        UniqueConstraint("character_id", "achievement_id", name="uq_user_achievement_state_pair"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    character_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    achievement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    criteria_progress: Mapped[dict | None] = mapped_column(JSONB)

    character = relationship("Character", back_populates="achievement_states")
    achievement = relationship("Achievement")

    def __repr__(self) -> str:
        return f"<UserAchievementState id={self.id} completed={self.completed}>"
