from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core_shared.db.models import CallArtifact, CallProcessingRun


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "core"
    / "app"
    / "core_shared"
    / "db"
    / "migrations"
    / "versions"
    / "2f4c9d8e7a61_add_call_processing_split_schemas.py"
)


def test_call_processing_models_are_schema_qualified() -> None:
    assert CallProcessingRun.__table__.schema == "call_core"
    assert CallArtifact.__table__.schema == "call_core"

    run_columns = set(CallProcessingRun.__table__.columns.keys())
    assert {
        "requested_by",
        "scope_json",
        "scope_hash",
        "required_artifacts",
        "mode",
        "status",
        "heartbeat_at",
        "counts_json",
        "errors_json",
    } <= run_columns

    artifact_columns = set(CallArtifact.__table__.columns.keys())
    assert {
        "department_id",
        "interaction_id",
        "artifact_kind",
        "artifact_version",
        "status",
        "is_active",
        "payload_json",
        "text_value",
        "provider",
        "model",
        "account_alias",
        "api_key_env",
        "raw_response_ref",
        "error_class",
        "error_reason",
        "retryable",
        "source_updated_at",
    } <= artifact_columns


def test_call_artifacts_has_partial_unique_active_artifact_index() -> None:
    indexes = {index.name: index for index in CallArtifact.__table__.indexes}
    active_index = indexes["uq_call_artifacts_active_kind_version"]

    assert active_index.unique is True
    assert [column.name for column in active_index.columns] == [
        "interaction_id",
        "artifact_kind",
        "artifact_version",
    ]
    assert str(active_index.dialect_options["postgresql"]["where"]) == "is_active"

    compiled = str(CreateIndex(active_index).compile(dialect=postgresql.dialect()))
    assert "CREATE UNIQUE INDEX uq_call_artifacts_active_kind_version" in compiled
    assert "ON call_core.call_artifacts" in compiled
    assert "WHERE is_active" in compiled


def test_model_tables_compile_with_call_core_schema() -> None:
    artifact_sql = str(CreateTable(CallArtifact.__table__).compile(dialect=postgresql.dialect()))
    run_sql = str(CreateTable(CallProcessingRun.__table__).compile(dialect=postgresql.dialect()))

    assert "CREATE TABLE call_core.call_artifacts" in artifact_sql
    assert "CREATE TABLE call_core.call_processing_runs" in run_sql
    assert "payload_json JSON" in artifact_sql
    assert "scope_json JSON" in run_sql


def test_migration_creates_required_schemas_tables_views_and_backfill() -> None:
    migration_sql = MIGRATION_PATH.read_text()

    for schema in ("call_core", "call_public", "analysis", "org"):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in migration_sql

    assert '"call_processing_runs"' in migration_sql
    assert '"call_artifacts"' in migration_sql
    assert 'schema="call_core"' in migration_sql
    assert "uq_call_artifacts_active_kind_version" in migration_sql
    assert "postgresql_where=sa.text(\"is_active\")" in migration_sql

    for view_name in (
        "processed_calls_v1",
        "transcripts_v1",
        "llm1_artifacts_v1",
        "processing_runs_v1",
    ):
        assert f"CREATE OR REPLACE VIEW call_public.{view_name}" in migration_sql

    assert "public.interactions" in migration_sql
    assert "column_name = 'text'" in migration_sql
    assert "'backfilled_from', 'public.interactions.text'" in migration_sql
    assert "column_name = 'metadata'" in migration_sql
    assert "'transcript_segments'" in migration_sql
    assert "'backfilled_from', 'public.interactions.metadata.segments'" in migration_sql
    assert "WHERE artifact_kind = 'llm1_first_pass'" in migration_sql
    assert "'llm1_first_pass'," not in migration_sql
