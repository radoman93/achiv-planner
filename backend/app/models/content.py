from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import TIMESTAMP, Boolean, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Guide(Base, TimestampMixin):
    __tablename__ = "guides"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    achievement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str | None] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)
    processed_content: Mapped[dict | None] = mapped_column(JSONB)
    steps: Mapped[dict | None] = mapped_column(JSONB)
    extracted_zone: Mapped[str | None] = mapped_column(String(255))
    requires_flying_extracted: Mapped[bool | None] = mapped_column(Boolean)
    requires_group_extracted: Mapped[bool | None] = mapped_column(Boolean)
    min_group_size_extracted: Mapped[int | None] = mapped_column(Integer)
    estimated_minutes_extracted: Mapped[int | None] = mapped_column(Integer)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    confidence_flags: Mapped[dict | None] = mapped_column(JSONB)
    patch_version_detected: Mapped[str | None] = mapped_column(String(50))
    scraped_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    achievement = relationship("Achievement", back_populates="guides")

    def __repr__(self) -> str:
        return f"<Guide id={self.id} source={self.source_type!r}>"


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    achievement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    raw_text: Mapped[str | None] = mapped_column(Text)
    comment_date: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    upvotes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recency_score: Mapped[float | None] = mapped_column(Float)
    vote_score: Mapped[float | None] = mapped_column(Float)
    combined_score: Mapped[float | None] = mapped_column(Float)
    comment_type: Mapped[str | None] = mapped_column(String(100))
    patch_version_mentioned: Mapped[str | None] = mapped_column(String(50))
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_contradictory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False,
    )

    achievement = relationship("Achievement", back_populates="comments")

    def __repr__(self) -> str:
        return f"<Comment id={self.id} author={self.author!r}>"
