"""HTTP routes for manual pipeline triggers."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.intake import OnlinePBXIntake
from app.agents.calls.orchestrator import CallsManualPilotOrchestrator
from app.agents.calls.reporting import (
    CallsManualReportingOrchestrator,
    ReportArtifact,
    ReportRunFilters,
    resolve_report_preset,
)
from app.agents.calls.scheduled_reporting import (
    SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES,
    SCHEDULED_REVIEWABLE_ALLOWED_RECURRENCE,
    SCHEDULED_REVIEWABLE_BATCH_STATUSES,
    SCHEDULED_REVIEWABLE_OPERATING_MODE,
    ScheduledReviewableReportingService,
)
from app.agents.calls.bitrix_readonly import BitrixManagerMapper, BitrixReadOnlyError
from app.core_shared.config.settings import settings
from app.core_shared.db.models import Department, Interaction, Manager
from app.core_shared.db.session import get_db
from app.core_shared.exceptions import ASAError, DeliveryError

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
UI_ASSET_PATH = Path(__file__).resolve().parents[1] / "assets" / "manual_reporting_operator.html"
logger = logging.getLogger(__name__)


def build_error_envelope(
    *,
    status_code: int,
    title: str,
    detail: str,
    error_type: str,
) -> JSONResponse:
    """Return a stable JSON error envelope for operator-facing routes."""
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "error": {
                "title": title,
                "detail": detail,
                "type": error_type,
                "http_status": status_code,
                "is_json_envelope": True,
            },
        },
    )


class RunIntakeRequest(BaseModel):
    """Payload for manual intake execution."""

    department_id: str
    date: str | None = None


class RunIntakeResponse(BaseModel):
    """Response returned after manual intake execution."""

    date: str
    total_fetched: int
    eligible: int
    created: int
    skipped: int


class RunExtractorRequest(BaseModel):
    """Payload for manual extractor execution."""

    department_id: str
    interaction_id: str | None = None
    limit: int = 10


class RunManualLiveRequest(BaseModel):
    """Payload for manual live pilot execution."""

    department_id: str
    date: str
    external_ids: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)
    limit: int | None = None
    send_notification: bool = True


class RunManualReportRequest(BaseModel):
    """Payload for bounded manual reporting pilot execution."""

    department_id: str
    preset: str
    mode: str = "build_missing_and_report"
    date_from: str
    date_to: str | None = None
    manager_ids: list[str] = Field(default_factory=list)
    manager_extensions: list[str] = Field(default_factory=list)
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None
    model: str | None = None
    send_email: bool = True


class SyncReportManagersRequest(BaseModel):
    """Payload for refreshing one local department manager directory."""

    department_id: str


class CreateReportScheduleRequest(BaseModel):
    """Payload for creating one bounded scheduled reviewable report."""

    department_id: str
    manager_ids: list[str] = Field(default_factory=list)
    preset: str
    enabled: bool = True
    start_date: str
    start_time: str
    timezone: str
    recurrence_type: str
    report_period_rule: str
    mode: str
    business_email_enabled: bool = False


class ToggleReportScheduleRequest(BaseModel):
    """Payload for pause/resume of one schedule."""

    enabled: bool


class EditScheduledDraftRequest(BaseModel):
    """Payload for editing allowed business-facing draft blocks."""

    edited_blocks: dict[str, str] = Field(default_factory=dict)
    editor: str = "operator_ui"


class ApproveScheduledBatchRequest(BaseModel):
    """Payload for approving one scheduled review batch."""

    editor: str = "operator_ui"


def _build_report_filters(request: RunManualReportRequest) -> ReportRunFilters:
    """Normalize UI/API request payload into report filters."""
    return ReportRunFilters(
        manager_ids=set(request.manager_ids),
        manager_extensions=set(request.manager_extensions),
        date_from=request.date_from,
        date_to=request.date_to or request.date_from,
        min_duration_sec=request.min_duration_sec,
        max_duration_sec=request.max_duration_sec,
    )


def _serialize_department(department: Department) -> dict:
    """Return a compact department payload for the operator UI."""
    reporting_settings = dict((department.settings or {}).get("reporting") or {})
    return {
        "id": str(department.id),
        "name": department.name,
        "reporting": {
            "rop_weekly_email": reporting_settings.get("rop_weekly_email"),
            "monitoring_email": reporting_settings.get("monitoring_email"),
        },
    }


def _serialize_manager(manager: Manager) -> dict:
    """Return a compact manager payload for the operator UI."""
    return {
        "id": str(manager.id),
        "department_id": str(manager.department_id),
        "name": manager.name,
        "extension": manager.extension,
        "email": manager.email,
        "bitrix_id": manager.bitrix_id,
        "active": bool(manager.active),
    }


def _split_report_group(
    artifacts: list[ReportArtifact],
) -> tuple[list[ReportArtifact], list[str]]:
    """Separate usable artifacts from missing ones for preview/status purposes."""
    missing: list[str] = []
    usable: list[ReportArtifact] = []
    for artifact in artifacts:
        if artifact.analysis is None:
            missing.append(f"analysis_missing:{artifact.interaction.id}")
            continue
        if not artifact.interaction.text:
            missing.append(f"transcript_missing:{artifact.interaction.id}")
            continue
        usable.append(artifact)
    return usable, missing


@router.get("/calls/report-ui", response_class=FileResponse)
async def get_calls_report_operator_ui() -> FileResponse:
    """Serve a minimal internal operator UI for manual report runs."""
    return FileResponse(UI_ASSET_PATH, media_type="text/html")


@router.get("/calls/report-ui/context")
async def get_calls_report_operator_context() -> dict:
    """Return departments, managers, presets, and modes for the operator UI."""
    with get_db() as db:
        departments = (
            db.query(Department)
            .order_by(Department.name.asc())
            .all()
        )
        managers = (
            db.query(Manager)
            .order_by(Manager.department_id.asc(), Manager.active.desc(), Manager.name.asc())
            .all()
        )
        serialized_departments = [_serialize_department(item) for item in departments]
        serialized_managers = [_serialize_manager(item) for item in managers]
        scheduled_service = ScheduledReviewableReportingService(db=db)
        scheduled_context = {
            "operating_mode": SCHEDULED_REVIEWABLE_OPERATING_MODE,
            "recurrence_types": list(SCHEDULED_REVIEWABLE_ALLOWED_RECURRENCE),
            "report_period_rules": list(SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES),
            "review_required": True,
            "lifecycle": list(SCHEDULED_REVIEWABLE_BATCH_STATUSES),
            "schedules": scheduled_service.list_schedules(),
            "review_queue": scheduled_service.list_review_batches(),
        }

    return {
        "presets": [
            {"code": "manager_daily", "label": "manager_daily"},
            {"code": "rop_weekly", "label": "rop_weekly"},
        ],
        "modes": [
            {"code": "build_missing_and_report", "label": "build_missing_and_report"},
            {"code": "report_from_ready_data_only", "label": "report_from_ready_data_only"},
        ],
        "departments": serialized_departments,
        "managers": serialized_managers,
        "operator_delivery": {
            "mode": "telegram_test" if settings.has_test_telegram_delivery else "email",
            "telegram_chat_id": (
                settings.test_delivery_telegram_chat_id
                if settings.has_test_telegram_delivery
                else None
            ),
        },
        "scheduled_reviewable_reporting": scheduled_context,
    }


@router.post("/calls/report-ui/sync-managers")
async def sync_calls_report_operator_managers(request: SyncReportManagersRequest) -> dict:
    """Refresh the local mirrored manager list for one selected department."""
    try:
        with get_db() as db:
            department = db.query(Department).filter(Department.id == request.department_id).first()
            if department is None:
                raise HTTPException(status_code=404, detail="Department not found")

            mapper = BitrixManagerMapper(db=db)
            summary = mapper.sync_department_directory(department=department)
            managers = (
                db.query(Manager)
                .filter(Manager.department_id == department.id)
                .order_by(Manager.active.desc(), Manager.name.asc())
                .all()
            )
            serialized_department = _serialize_department(department)
            serialized_managers = [_serialize_manager(item) for item in managers]
    except (ASAError, BitrixReadOnlyError) as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc

    return {
        "status": "synced",
        "department": serialized_department,
        "summary": {
            **summary,
            "active_total": sum(1 for item in serialized_managers if item["active"]),
            "inactive_total": sum(1 for item in serialized_managers if not item["active"]),
        },
        "managers": serialized_managers,
    }


@router.post("/calls/report-preview")
async def preview_calls_report_manual(request: RunManualReportRequest) -> dict:
    """Preview resolved recipients and likely blocking reasons before a report run."""
    filters = _build_report_filters(request)
    try:
        with get_db() as db:
            orchestrator = CallsManualReportingOrchestrator(
                department_id=request.department_id,
                db=db,
            )
            preset = resolve_report_preset(request.preset)
            period = orchestrator._build_period(filters=filters, preset=preset)
            interactions = orchestrator._select_interactions(filters=filters, period=period)
            if not interactions:
                return {
                    "status": "no_data",
                    "preset": preset.code,
                    "period": period,
                    "selected_interactions": 0,
                    "groups": [],
                    "errors": ["no_interactions_for_selected_filters"],
                }

            artifacts, build_summary = await orchestrator._prepare_artifacts(
                interactions=interactions,
                mode=request.mode,
            )
            groups = orchestrator._group_artifacts_by_preset(
                preset=preset,
                artifacts=artifacts,
                period=period,
            )

            preview_groups: list[dict] = []
            for group in groups:
                usable, missing = _split_report_group(group)
                group_key = orchestrator._build_group_key(
                    preset=preset,
                    artifacts=group,
                    period=period,
                )
                if not usable:
                    preview_groups.append(
                        {
                            "group_key": group_key,
                            "status": "missing_artifacts",
                            "errors": missing or ["no_usable_artifacts"],
                            "delivery": None,
                        }
                    )
                    continue

                try:
                    targets = orchestrator._resolve_delivery_targets(
                        preset=preset,
                        artifacts=usable,
                    )
                except DeliveryError as exc:
                    preview_groups.append(
                        {
                            "group_key": group_key,
                            "status": "recipient_blocked",
                            "errors": [*missing, str(exc)],
                            "delivery": None,
                        }
                    )
                    continue

                preview_groups.append(
                    {
                        "group_key": group_key,
                        "status": "ready",
                        "errors": missing,
                        "delivery": orchestrator.delivery.preview_report_delivery(
                            primary_email=targets["primary_email"],
                            cc_emails=targets["cc_emails"],
                            send_business_email=True,
                        ),
                    }
                )

            statuses = {item["status"] for item in preview_groups}
            overall_status = (
                "completed"
                if statuses <= {"ready"}
                else "partial"
                if "ready" in statuses
                else "blocked"
            )
            return {
                "status": overall_status,
                "preset": preset.code,
                "period": period,
                "selected_interactions": len(interactions),
                "prepared_artifacts": build_summary,
                "groups": preview_groups,
            }
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc


@router.post("/calls/intake", response_model=RunIntakeResponse)
async def run_calls_intake(request: RunIntakeRequest) -> RunIntakeResponse:
    """Ручной запуск intake звонков для отладки."""
    try:
        with get_db() as db:
            intake = OnlinePBXIntake(
                department_id=request.department_id,
                db=db,
            )
            result = await intake.run(date=request.date)
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc

    return RunIntakeResponse(**result)


@router.post("/calls/extract")
async def run_calls_extract(request: RunExtractorRequest) -> dict:
    """Ручной запуск транскрипции для отладки."""
    try:
        with get_db() as db:
            extractor = CallsExtractor(
                department_id=request.department_id,
                db=db,
            )
            if request.interaction_id:
                interaction = db.query(Interaction).filter(
                    Interaction.id == request.interaction_id
                ).first()
                if not interaction:
                    raise HTTPException(status_code=404, detail="Interaction not found")
                await extractor.process(interaction)
                return {"processed": 1, "interaction_id": str(interaction.id)}

            result = await extractor.run_pending(limit=request.limit)
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc

    return result


@router.post("/calls/live-run")
async def run_calls_live_manual(request: RunManualLiveRequest) -> dict:
    """Ручной live e2e pipeline from OnlinePBX to test delivery."""
    try:
        with get_db() as db:
            orchestrator = CallsManualPilotOrchestrator(
                department_id=request.department_id,
                db=db,
            )
            result = await orchestrator.run_live(
                date=request.date,
                external_ids=request.external_ids,
                phones=request.phones,
                extensions=request.extensions,
                limit=request.limit,
                send_notification=request.send_notification,
            )
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc

    return result


@router.post("/calls/report-run")
async def run_calls_report_manual(request: RunManualReportRequest) -> dict:
    """Run one bounded Manual Reporting Pilot execution."""
    try:
        with get_db() as db:
            orchestrator = CallsManualReportingOrchestrator(
                department_id=request.department_id,
                db=db,
            )
            result = await orchestrator.run_report(
                preset_code=request.preset,
                mode=request.mode,
                filters=ReportRunFilters(
                    manager_ids=set(request.manager_ids),
                    manager_extensions=set(request.manager_extensions),
                    date_from=request.date_from,
                    date_to=request.date_to or request.date_from,
                    min_duration_sec=request.min_duration_sec,
                    max_duration_sec=request.max_duration_sec,
                ),
                model_override=request.model,
                send_email=request.send_email,
            )
    except ASAError as exc:
        detail = f"{exc.__class__.__name__}: {exc}"
        return build_error_envelope(
            status_code=400,
            title="Manual report run failed",
            detail=detail,
            error_type="manual_report_run_error",
        )
    except Exception as exc:  # pragma: no cover - hardened at runtime, exercised via manual smoke
        logger.exception("pipeline.report_run.unexpected_failure")
        detail = f"{exc.__class__.__name__}: {exc}"
        return build_error_envelope(
            status_code=500,
            title="Unexpected manual report run failure",
            detail=detail,
            error_type="unexpected_manual_report_run_failure",
        )

    return result


@router.post("/calls/report-schedules")
async def create_calls_report_schedule(request: CreateReportScheduleRequest) -> dict:
    """Create one bounded scheduled reviewable reporting schedule."""
    try:
        with get_db() as db:
            service = ScheduledReviewableReportingService(db=db)
            schedule = service.create_schedule(
                department_id=request.department_id,
                manager_ids=request.manager_ids,
                preset=request.preset,
                enabled=request.enabled,
                start_date=request.start_date,
                start_time=request.start_time,
                timezone_name=request.timezone,
                recurrence_type=request.recurrence_type,
                report_period_rule=request.report_period_rule,
                mode=request.mode,
                business_email_enabled=request.business_email_enabled,
            )
            return {"status": "created", "schedule": schedule}
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc


@router.post("/calls/report-schedules/{schedule_id}/enabled")
async def toggle_calls_report_schedule(schedule_id: str, request: ToggleReportScheduleRequest) -> dict:
    """Pause or resume one bounded schedule."""
    try:
        with get_db() as db:
            service = ScheduledReviewableReportingService(db=db)
            schedule = service.set_schedule_enabled(schedule_id=schedule_id, enabled=request.enabled)
            return {"status": "updated", "schedule": schedule}
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc


@router.post("/calls/report-review/drafts/{draft_id}/edit")
async def edit_calls_scheduled_report_draft(draft_id: str, request: EditScheduledDraftRequest) -> dict:
    """Edit allowed business-facing blocks for one scheduled draft."""
    try:
        with get_db() as db:
            service = ScheduledReviewableReportingService(db=db)
            draft = service.edit_draft(
                draft_id=draft_id,
                edited_blocks=request.edited_blocks,
                editor=request.editor,
            )
            return {"status": "edited", "draft": draft}
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc


@router.post("/calls/report-review/batches/{batch_id}/approve")
async def approve_calls_scheduled_report_batch(batch_id: str, request: ApproveScheduledBatchRequest) -> dict:
    """Approve one scheduled review batch for business delivery."""
    try:
        with get_db() as db:
            service = ScheduledReviewableReportingService(db=db)
            batch = service.approve_batch(batch_id=batch_id, editor=request.editor)
            return {"status": "approved", "batch": batch}
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc


@router.post("/calls/report-schedules/scan")
async def scan_calls_report_schedules() -> dict:
    """Run one bounded due-schedule scan for scheduled reviewable reporting."""
    try:
        with get_db() as db:
            service = ScheduledReviewableReportingService(db=db)
            summary = service.scan_due_schedules()
            return {"status": "completed", **summary}
    except ASAError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.__class__.__name__}: {exc}") from exc
