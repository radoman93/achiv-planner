from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("battlenet_id", name="uq_users_battlenet_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    battlenet_id: Mapped[str | None] = mapped_column(String(255))
    battlenet_token: Mapped[str | None] = mapped_column(Text)
    battlenet_token_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    battlenet_region: Mapped[str | None] = mapped_column(String(10))
    priority_mode: Mapped[str] = mapped_column(String(50), default="completionist", nullable=False)
    session_duration_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    solo_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tier: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    characters = relationship("Character", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class Character(Base, TimestampMixin):
    __tablename__ = "characters"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    realm: Mapped[str] = mapped_column(String(255), nullable=False)
    faction: Mapped[str | None] = mapped_column(String(50))
    class_: Mapped[str | None] = mapped_column("class", String(50))
    race: Mapped[str | None] = mapped_column(String(50))
    level: Mapped[int | None] = mapped_column(Integer)
    region: Mapped[str | None] = mapped_column(String(10))
    flying_unlocked: Mapped[dict | None] = mapped_column(JSONB)
    current_expansion: Mapped[str | None] = mapped_column(String(100))
    last_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    user = relationship("User", back_populates="characters")
    achievement_states = relationship(
        "UserAchievementState", back_populates="character", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Character id={self.id} name={self.name!r} realm={self.realm!r}>"
