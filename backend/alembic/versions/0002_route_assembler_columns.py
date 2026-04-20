"""Add blocked_pool, deferred_pool to routes and community_tips to route_stops.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("blocked_pool", JSONB, nullable=True))
    op.add_column("routes", sa.Column("deferred_pool", JSONB, nullable=True))
    op.add_column("route_stops", sa.Column("community_tips", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("route_stops", "community_tips")
    op.drop_column("routes", "deferred_pool")
    op.drop_column("routes", "blocked_pool")
