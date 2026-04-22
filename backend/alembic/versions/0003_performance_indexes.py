"""Performance indexes + character completion materialized view.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-21
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Composite indexes -------------------------------------------------
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_achievement_state_character_incomplete
        ON user_achievement_state (character_id, achievement_id)
        WHERE completed = FALSE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_route_stops_route_session_sequence
        ON route_stops (route_id, session_number, sequence_order)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_achievements_expansion_zone
        ON achievements (expansion, zone_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_comments_achievement_score
        ON comments (achievement_id, combined_score DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_guides_achievement_confidence
        ON guides (achievement_id, confidence_score DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_achievements_seasonal_dates
        ON achievements (seasonal_start, seasonal_end)
        WHERE is_seasonal = TRUE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_achievements_staleness
        ON achievements (staleness_score DESC)
        WHERE is_legacy = FALSE
        """
    )

    # --- Materialized view: character_completion_stats --------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS character_completion_stats AS
        SELECT
            c.id AS character_id,
            COUNT(uas.id) FILTER (WHERE uas.completed = TRUE) AS total_completed,
            COUNT(uas.id) AS total_eligible,
            ROUND(
                COUNT(uas.id) FILTER (WHERE uas.completed = TRUE)::numeric
                / NULLIF(COUNT(uas.id), 0) * 100,
                1
            ) AS completion_pct,
            SUM(a.points) FILTER (WHERE uas.completed = TRUE) AS total_points,
            jsonb_object_agg(
                COALESCE(a.expansion, 'unknown'),
                jsonb_build_object(
                    'completed', COUNT(uas.id) FILTER (WHERE uas.completed = TRUE),
                    'total', COUNT(uas.id)
                )
            ) AS by_expansion
        FROM characters c
        LEFT JOIN user_achievement_state uas ON uas.character_id = c.id
        LEFT JOIN achievements a ON a.id = uas.achievement_id
        GROUP BY c.id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_character_completion_stats_character_id
        ON character_completion_stats (character_id)
        """
    )

    # refresh function — CONCURRENTLY avoids blocking reads but requires
    # the unique index above.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refresh_character_stats(char_id UUID DEFAULT NULL)
        RETURNS VOID AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY character_completion_stats;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS refresh_character_stats(UUID)")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS character_completion_stats")

    op.execute("DROP INDEX IF EXISTS idx_achievements_staleness")
    op.execute("DROP INDEX IF EXISTS idx_achievements_seasonal_dates")
    op.execute("DROP INDEX IF EXISTS idx_guides_achievement_confidence")
    op.execute("DROP INDEX IF EXISTS idx_comments_achievement_score")
    op.execute("DROP INDEX IF EXISTS idx_achievements_expansion_zone")
    op.execute("DROP INDEX IF EXISTS idx_route_stops_route_session_sequence")
    op.execute("DROP INDEX IF EXISTS idx_user_achievement_state_character_incomplete")
