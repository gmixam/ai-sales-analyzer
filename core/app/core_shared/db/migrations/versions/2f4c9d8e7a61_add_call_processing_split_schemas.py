"""add_call_processing_split_schemas

Revision ID: 2f4c9d8e7a61
Revises: 6b8d0c5e2f31
Create Date: 2026-06-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f4c9d8e7a61"
down_revision = "6b8d0c5e2f31"
branch_labels = None
depends_on = None


CALL_PUBLIC_VIEWS = (
    "processed_calls_v1",
    "transcripts_v1",
    "llm1_artifacts_v1",
    "processing_runs_v1",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS call_core")
    op.execute("CREATE SCHEMA IF NOT EXISTS call_public")
    op.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    op.execute("CREATE SCHEMA IF NOT EXISTS org")

    op.create_table(
        "call_processing_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("required_artifacts", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_processing_runs")),
        schema="call_core",
    )
    op.create_index(
        "ix_call_processing_runs_scope_hash",
        "call_processing_runs",
        ["scope_hash"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_processing_runs_scope_hash_status",
        "call_processing_runs",
        ["scope_hash", "status"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_processing_runs_status",
        "call_processing_runs",
        ["status"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_processing_runs_status_updated",
        "call_processing_runs",
        ["status", "updated_at"],
        unique=False,
        schema="call_core",
    )

    op.create_table(
        "call_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=False),
        sa.Column("interaction_id", sa.UUID(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=50), nullable=False),
        sa.Column("artifact_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("account_alias", sa.String(length=120), nullable=True),
        sa.Column("api_key_env", sa.String(length=120), nullable=True),
        sa.Column("raw_response_ref", sa.Text(), nullable=True),
        sa.Column("error_class", sa.String(length=80), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_artifacts")),
        schema="call_core",
    )
    op.create_index(
        "ix_call_artifacts_department_id",
        "call_artifacts",
        ["department_id"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_artifacts_department_kind_status",
        "call_artifacts",
        ["department_id", "artifact_kind", "status"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_artifacts_interaction_id",
        "call_artifacts",
        ["interaction_id"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_artifacts_interaction_kind",
        "call_artifacts",
        ["interaction_id", "artifact_kind"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_artifacts_source_updated",
        "call_artifacts",
        ["source_updated_at"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "ix_call_artifacts_status",
        "call_artifacts",
        ["status"],
        unique=False,
        schema="call_core",
    )
    op.create_index(
        "uq_call_artifacts_active_kind_version",
        "call_artifacts",
        ["interaction_id", "artifact_kind", "artifact_version"],
        unique=True,
        schema="call_core",
        postgresql_where=sa.text("is_active"),
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'interactions'
                  AND column_name = 'text'
            ) THEN
                INSERT INTO call_core.call_artifacts (
                    id,
                    department_id,
                    interaction_id,
                    artifact_kind,
                    artifact_version,
                    status,
                    is_active,
                    payload_json,
                    text_value,
                    source_updated_at,
                    created_at,
                    updated_at
                )
                SELECT
                    (
                        substr(md5(i.id::text || ':transcript:v1'), 1, 8) || '-' ||
                        substr(md5(i.id::text || ':transcript:v1'), 9, 4) || '-' ||
                        substr(md5(i.id::text || ':transcript:v1'), 13, 4) || '-' ||
                        substr(md5(i.id::text || ':transcript:v1'), 17, 4) || '-' ||
                        substr(md5(i.id::text || ':transcript:v1'), 21, 12)
                    )::uuid,
                    i.department_id,
                    i.id,
                    'transcript',
                    'transcript_v1',
                    'ready',
                    true,
                    json_build_object(
                        'schema_version', 'transcript_v1',
                        'backfilled_from', 'public.interactions.text',
                        'created_at', COALESCE(i.analyzed_at, i.created_at)
                    ),
                    i.text,
                    COALESCE(i.analyzed_at, i.created_at),
                    now(),
                    now()
                FROM public.interactions AS i
                WHERE i.text IS NOT NULL
                  AND btrim(i.text) <> ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM call_core.call_artifacts AS existing
                      WHERE existing.interaction_id = i.id
                        AND existing.artifact_kind = 'transcript'
                        AND existing.artifact_version = 'transcript_v1'
                        AND existing.is_active
                  );
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'interactions'
                  AND column_name = 'metadata'
            ) THEN
                INSERT INTO call_core.call_artifacts (
                    id,
                    department_id,
                    interaction_id,
                    artifact_kind,
                    artifact_version,
                    status,
                    is_active,
                    payload_json,
                    source_updated_at,
                    created_at,
                    updated_at
                )
                SELECT
                    (
                        substr(md5(i.id::text || ':transcript_segments:v1'), 1, 8) || '-' ||
                        substr(md5(i.id::text || ':transcript_segments:v1'), 9, 4) || '-' ||
                        substr(md5(i.id::text || ':transcript_segments:v1'), 13, 4) || '-' ||
                        substr(md5(i.id::text || ':transcript_segments:v1'), 17, 4) || '-' ||
                        substr(md5(i.id::text || ':transcript_segments:v1'), 21, 12)
                    )::uuid,
                    i.department_id,
                    i.id,
                    'transcript_segments',
                    'transcript_segments_v1',
                    'ready',
                    true,
                    json_build_object(
                        'schema_version', 'transcript_segments_v1',
                        'backfilled_from', 'public.interactions.metadata.segments',
                        'segments', i.metadata -> 'segments',
                        'created_at', COALESCE(i.analyzed_at, i.created_at)
                    ),
                    COALESCE(i.analyzed_at, i.created_at),
                    now(),
                    now()
                FROM public.interactions AS i
                WHERE json_typeof(i.metadata -> 'segments') = 'array'
                  AND json_array_length(i.metadata -> 'segments') > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM call_core.call_artifacts AS existing
                      WHERE existing.interaction_id = i.id
                        AND existing.artifact_kind = 'transcript_segments'
                        AND existing.artifact_version = 'transcript_segments_v1'
                        AND existing.is_active
                  );
            END IF;
        END $$;
        """
    )

    _create_call_public_views()
    _grant_call_public_read_only_if_role_exists()


def downgrade() -> None:
    for view_name in CALL_PUBLIC_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS call_public.{view_name}")

    op.drop_index(
        "uq_call_artifacts_active_kind_version",
        table_name="call_artifacts",
        schema="call_core",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_index("ix_call_artifacts_status", table_name="call_artifacts", schema="call_core")
    op.drop_index("ix_call_artifacts_source_updated", table_name="call_artifacts", schema="call_core")
    op.drop_index("ix_call_artifacts_interaction_kind", table_name="call_artifacts", schema="call_core")
    op.drop_index("ix_call_artifacts_interaction_id", table_name="call_artifacts", schema="call_core")
    op.drop_index("ix_call_artifacts_department_kind_status", table_name="call_artifacts", schema="call_core")
    op.drop_index("ix_call_artifacts_department_id", table_name="call_artifacts", schema="call_core")
    op.drop_table("call_artifacts", schema="call_core")

    op.drop_index("ix_call_processing_runs_status_updated", table_name="call_processing_runs", schema="call_core")
    op.drop_index("ix_call_processing_runs_status", table_name="call_processing_runs", schema="call_core")
    op.drop_index(
        "ix_call_processing_runs_scope_hash_status",
        table_name="call_processing_runs",
        schema="call_core",
    )
    op.drop_index("ix_call_processing_runs_scope_hash", table_name="call_processing_runs", schema="call_core")
    op.drop_table("call_processing_runs", schema="call_core")

    op.execute("DROP SCHEMA IF EXISTS call_public")
    op.execute("DROP SCHEMA IF EXISTS call_core")
    op.execute("DROP SCHEMA IF EXISTS analysis")
    op.execute("DROP SCHEMA IF EXISTS org")


def _create_call_public_views() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW call_public.processed_calls_v1 AS
        SELECT
            i.id AS interaction_id,
            i.department_id,
            i.manager_id,
            i.type AS interaction_type,
            i.source,
            i.external_id,
            i.raw_ref,
            i.duration_sec,
            i.status AS legacy_status,
            i.week_id,
            i.counted,
            i.used_for_reco,
            i.created_at,
            i.analyzed_at,
            transcript.status AS transcript_status,
            transcript.artifact_version AS transcript_version,
            transcript.updated_at AS transcript_updated_at,
            llm1.status AS llm1_status,
            llm1.artifact_version AS llm1_version,
            llm1.updated_at AS llm1_updated_at,
            (transcript.id IS NOT NULL AND transcript.status = 'ready') AS has_transcript,
            (llm1.id IS NOT NULL AND llm1.status = 'ready') AS has_llm1_first_pass,
            GREATEST(
                i.created_at,
                COALESCE(transcript.updated_at, i.created_at),
                COALESCE(llm1.updated_at, i.created_at)
            ) AS call_processing_updated_at
        FROM public.interactions AS i
        LEFT JOIN call_core.call_artifacts AS transcript
          ON transcript.interaction_id = i.id
         AND transcript.artifact_kind = 'transcript'
         AND transcript.is_active
        LEFT JOIN call_core.call_artifacts AS llm1
          ON llm1.interaction_id = i.id
         AND llm1.artifact_kind = 'llm1_first_pass'
         AND llm1.is_active;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW call_public.transcripts_v1 AS
        SELECT
            id AS artifact_id,
            department_id,
            interaction_id,
            artifact_version,
            status,
            text_value AS transcript_text,
            payload_json,
            provider,
            model,
            account_alias,
            error_class,
            error_reason,
            retryable,
            source_updated_at,
            created_at,
            updated_at
        FROM call_core.call_artifacts
        WHERE artifact_kind = 'transcript'
          AND is_active;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW call_public.llm1_artifacts_v1 AS
        SELECT
            id AS artifact_id,
            department_id,
            interaction_id,
            artifact_version,
            status,
            payload_json,
            provider,
            model,
            account_alias,
            raw_response_ref,
            error_class,
            error_reason,
            retryable,
            source_updated_at,
            created_at,
            updated_at
        FROM call_core.call_artifacts
        WHERE artifact_kind = 'llm1_first_pass'
          AND is_active;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW call_public.processing_runs_v1 AS
        SELECT
            id AS run_id,
            requested_by,
            scope_json,
            scope_hash,
            required_artifacts,
            mode,
            status,
            started_at,
            finished_at,
            heartbeat_at,
            counts_json,
            errors_json,
            created_at,
            updated_at
        FROM call_core.call_processing_runs;
        """
    )


def _grant_call_public_read_only_if_role_exists() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'asa_analysis_reader') THEN
                GRANT USAGE ON SCHEMA call_public TO asa_analysis_reader;
                GRANT SELECT ON ALL TABLES IN SCHEMA call_public TO asa_analysis_reader;
                ALTER DEFAULT PRIVILEGES IN SCHEMA call_public
                    GRANT SELECT ON TABLES TO asa_analysis_reader;
            END IF;
        END $$;
        """
    )
