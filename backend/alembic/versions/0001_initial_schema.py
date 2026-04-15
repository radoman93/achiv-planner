"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("expansion", sa.String(100)),
        sa.Column("continent", sa.String(100)),
        sa.Column("requires_flying", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flying_condition", sa.Text()),
        sa.Column("has_portal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("portal_from", sa.String(255)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "achievements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("blizzard_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("how_to_complete", sa.Text()),
        sa.Column("category", sa.String(255)),
        sa.Column("subcategory", sa.String(255)),
        sa.Column("expansion", sa.String(100)),
        sa.Column("patch_introduced", sa.String(50)),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_account_wide", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_meta", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_faction_specific", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("faction", sa.String(50)),
        sa.Column("is_class_restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_classes", postgresql.JSONB()),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("zones.id", ondelete="SET NULL")),
        sa.Column("estimated_minutes", sa.Integer()),
        sa.Column("requires_flying", sa.Boolean()),
        sa.Column("requires_group", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("min_group_size", sa.Integer()),
        sa.Column("is_seasonal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("seasonal_event", sa.String(255)),
        sa.Column("seasonal_start", sa.Date()),
        sa.Column("seasonal_end", sa.Date()),
        sa.Column("last_scraped_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("staleness_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("manually_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("blizzard_id", name="uq_achievements_blizzard_id"),
    )
    op.create_index("ix_achievements_blizzard_id", "achievements", ["blizzard_id"])

    op.create_table(
        "achievement_criteria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blizzard_criteria_id", sa.Integer()),
        sa.Column("description", sa.Text()),
        sa.Column("required_amount", sa.Integer()),
        sa.Column("criteria_type", sa.String(100)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_achievement_criteria_achievement_id", "achievement_criteria", ["achievement_id"])

    op.create_table(
        "achievement_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("required_achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependent_achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependency_type", sa.String(50)),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("required_achievement_id", "dependent_achievement_id", name="uq_achievement_dependencies_pair"),
    )

    op.create_table(
        "guides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(50)),
        sa.Column("source_url", sa.Text()),
        sa.Column("raw_content", sa.Text()),
        sa.Column("processed_content", postgresql.JSONB()),
        sa.Column("steps", postgresql.JSONB()),
        sa.Column("extracted_zone", sa.String(255)),
        sa.Column("requires_flying_extracted", sa.Boolean()),
        sa.Column("requires_group_extracted", sa.Boolean()),
        sa.Column("min_group_size_extracted", sa.Integer()),
        sa.Column("estimated_minutes_extracted", sa.Integer()),
        sa.Column("confidence_score", sa.Float()),
        sa.Column("confidence_flags", postgresql.JSONB()),
        sa.Column("patch_version_detected", sa.String(50)),
        sa.Column("scraped_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float())),  # placeholder; real vector added below
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE guides DROP COLUMN embedding")
    op.execute("ALTER TABLE guides ADD COLUMN embedding vector(1536)")
    op.create_index("ix_guides_achievement_id", "guides", ["achievement_id"])

    op.create_table(
        "comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("author", sa.String(255)),
        sa.Column("raw_text", sa.Text()),
        sa.Column("comment_date", sa.TIMESTAMP(timezone=True)),
        sa.Column("upvotes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recency_score", sa.Float()),
        sa.Column("vote_score", sa.Float()),
        sa.Column("combined_score", sa.Float()),
        sa.Column("comment_type", sa.String(100)),
        sa.Column("patch_version_mentioned", sa.String(50)),
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_contradictory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_comments_achievement_id", "comments", ["achievement_id"])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("battlenet_id", sa.String(255)),
        sa.Column("battlenet_token", sa.Text()),
        sa.Column("battlenet_token_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("battlenet_region", sa.String(10)),
        sa.Column("priority_mode", sa.String(50), nullable=False, server_default="completionist"),
        sa.Column("session_duration_minutes", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("solo_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tier", sa.String(50), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("battlenet_id", name="uq_users_battlenet_id"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "characters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("realm", sa.String(255), nullable=False),
        sa.Column("faction", sa.String(50)),
        sa.Column("class", sa.String(50)),
        sa.Column("race", sa.String(50)),
        sa.Column("level", sa.Integer()),
        sa.Column("region", sa.String(10)),
        sa.Column("flying_unlocked", postgresql.JSONB()),
        sa.Column("current_expansion", sa.String(100)),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_characters_user_id", "characters", ["user_id"])

    op.create_table(
        "user_achievement_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("criteria_progress", postgresql.JSONB()),
        sa.UniqueConstraint("character_id", "achievement_id", name="uq_user_achievement_state_pair"),
    )
    op.create_index("ix_user_achievement_state_character_id", "user_achievement_state", ["character_id"])
    op.create_index("ix_user_achievement_state_achievement_id", "user_achievement_state", ["achievement_id"])
    op.create_index("ix_user_achievement_state_character_completed", "user_achievement_state", ["character_id", "completed"])

    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(50)),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("total_estimated_minutes", sa.Integer()),
        sa.Column("overall_confidence", sa.Float()),
        sa.Column("session_duration_minutes", sa.Integer()),
        sa.Column("solo_only", sa.Boolean()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_routes_user_id", "routes", ["user_id"])
    op.create_index("ix_routes_character_id", "routes", ["character_id"])

    op.create_table(
        "route_stops",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_number", sa.Integer()),
        sa.Column("sequence_order", sa.Integer()),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("zones.id", ondelete="SET NULL")),
        sa.Column("estimated_minutes", sa.Integer()),
        sa.Column("confidence_tier", sa.String(50)),
        sa.Column("guide_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("guides.id", ondelete="SET NULL")),
        sa.Column("is_seasonal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("days_remaining", sa.Integer()),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_route_stops_route_id", "route_stops", ["route_id"])
    op.create_index("ix_route_stops_route_session_seq", "route_stops", ["route_id", "session_number", "sequence_order"])

    op.create_table(
        "route_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("route_stop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("route_stops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_order", sa.Integer()),
        sa.Column("description", sa.Text()),
        sa.Column("step_type", sa.String(50)),
        sa.Column("location", sa.String(255)),
        sa.Column("source_reference", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_route_steps_route_stop_id", "route_steps", ["route_stop_id"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("achievements_processed", sa.Integer()),
        sa.Column("achievements_errored", sa.Integer()),
        sa.Column("phases_completed", postgresql.JSONB()),
        sa.Column("error_log", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "patch_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patch_version", sa.String(50)),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("source_url", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_patch_events_achievement_id", "patch_events", ["achievement_id"])


def downgrade() -> None:
    op.drop_table("patch_events")
    op.drop_table("pipeline_runs")
    op.drop_table("route_steps")
    op.drop_table("route_stops")
    op.drop_table("routes")
    op.drop_table("user_achievement_state")
    op.drop_table("characters")
    op.drop_table("users")
    op.drop_table("comments")
    op.drop_table("guides")
    op.drop_table("achievement_dependencies")
    op.drop_table("achievement_criteria")
    op.drop_table("achievements")
    op.drop_table("zones")
    op.execute("DROP EXTENSION IF EXISTS vector")
