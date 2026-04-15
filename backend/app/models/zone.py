from uuid import UUID, uuid4

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Zone(Base, TimestampMixin):
    __tablename__ = "zones"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expansion: Mapped[str | None] = mapped_column(String(100))
    continent: Mapped[str | None] = mapped_column(String(100))
    requires_flying: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flying_condition: Mapped[str | None] = mapped_column(Text)
    has_portal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    portal_from: Mapped[str | None] = mapped_column(String(255))

    achievements = relationship("Achievement", back_populates="zone")

    def __repr__(self) -> str:
        return f"<Zone id={self.id} name={self.name!r}>"
