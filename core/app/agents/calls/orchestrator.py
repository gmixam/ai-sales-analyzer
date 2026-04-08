"""Manual pilot orchestration for a live end-to-end call run."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy.orm import Session

from app.agents.calls.analyzer import APPROVED_INSTRUCTION_VERSION, CallsAnalyzer
from app.agents.calls.delivery import CallsDelivery
from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.intake import OnlinePBXIntake
from app.agents.calls.schemas import CDRRecord
from app.core_shared.config.settings import settings
from app.core_shared.db.models import Agreement, Analysis, Insight, Interaction
from app.core_shared.exceptions import ASAError, DatabaseError, DeliveryError, SemanticAnalysisError


@dataclass(slots=True)
class PilotTargetConfig:
    """Explicit manual pilot selection filters."""

    external_ids: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    extensions: set[str] = field(default_factory=set)

    @classmethod
    def from_settings(cls) -> PilotTargetConfig:
        """Build pilot target config from environment settings."""
        return cls(
            external_ids=set(settings.manual_pilot_external_ids),
            phones=set(settings.manual_pilot_phones),
            extensions=set(settings.manual_pilot_extensions),
        )

    def merge(
        self,
        *,
        external_ids: list[str] | None = None,
        phones: list[str] | None = None,
        extensions: list[str] | None = None,
    ) -> PilotTargetConfig:
        """Return a merged copy with request-level filters added."""
        return PilotTargetConfig(
            external_ids=self.external_ids | set(external_ids or []),
            phones=self.phones | set(phones or []),
            extensions=self.extensions | set(extensions or []),
        )

    def is_configured(self) -> bool:
        """Return True when at least one explicit target filter is present."""
        return bool(self.external_ids or self.phones or self.extensions)

    def matches(self, record: CDRRecord) -> bool:
        """Return True when the record matches any configured pilot target."""
        return any(
            [
                record.call_id in self.external_ids if self.external_ids else False,
                record.phone in self.phones if self.phones else False,
                record.extension in self.extensions if self.extensions else False,
            ]
        )


class CallsManualPilotOrchestrator:
    """Run one manual live-flow from OnlinePBX to test delivery."""

    def __init__(self, department_id: str, db: Session):
        self.department_id = UUID(department_id)
        self.db = db
        self.logger = structlog.get_logger().bind(
            module="calls.orchestrator",
            department_id=department_id,
        )
        self.intake = OnlinePBXIntake(department_id=department_id, db=db)
        self.extractor = CallsExtractor(department_id=department_id, db=db)
        self.analyzer = CallsAnalyzer(department_id=department_id, db=db)
        self.delivery = CallsDelivery(department_id=department_id, db=db)

    async def run_live(
        self,
        *,
        date: str,
        external_ids: list[str] | None = None,
        phones: list[str] | None = None,
        extensions: list[str] | None = None,
        limit: int | None = None,
        send_notification: bool = True,
    ) -> dict[str, Any]:
        """Execute a manual live run for a narrow, explicit pilot target."""
        if not settings.manual_pilot_enabled:
            raise ASAError("Manual pilot mode is disabled. Set MANUAL_PILOT_ENABLED=true.")

        target_config = PilotTargetConfig.from_settings().merge(
            external_ids=external_ids,
            phones=phones,
            extensions=extensions,
        )
        if not target_config.is_configured():
            raise ASAError(
                "Manual pilot target is not configured. Set whitelist env vars or pass "
                "external_ids / phones / extensions explicitly."
            )

        max_calls = limit or settings.manual_pilot_max_calls
        self.logger.info("manual_live.start", date=date, max_calls=max_calls)

        records = self.intake.get_cdr_list(date)
        eligible = self.intake.filter_eligible(records)
        targeted = [record for record in eligible if target_config.matches(record)]
        if not targeted:
            raise ASAError("No eligible OnlinePBX calls matched the manual pilot target.")

        targeted = targeted[:max_calls]
        for record in targeted:
            if not record.record_url:
                record.record_url = self.intake.get_recording_url(record.call_id)
        self.intake.save_interactions(targeted)

        results: list[dict[str, Any]] = []
        for record in targeted:
            interaction = self._get_interaction_by_external_id(record.call_id)
            if interaction is None:
                raise DatabaseError(
                    f"Interaction for external_id={record.call_id} was not persisted."
                )

            results.append(
                await self._run_single_interaction(
                    interaction=interaction,
                    send_notification=send_notification,
                )
            )

        response = {
            "date": date,
            "fetched": len(records),
            "eligible": len(eligible),
            "targeted": len(targeted),
            "processed": len(results),
            "results": results,
        }
        self.logger.info("manual_live.done", processed=len(results))
        return response

    async def _run_single_interaction(
        self,
        *,
        interaction: Interaction,
        send_notification: bool,
    ) -> dict[str, Any]:
        """Run extract -> analyze -> persist -> deliver for one interaction."""
        stt_provider = settings.effective_manual_live_stt_provider
        if interaction.status != "TRANSCRIBED" or not interaction.text:
            await self.extractor.process(interaction, stt_provider=stt_provider)

        try:
            analysis_result = self.analyzer.analyze_call(interaction)
            analysis_row = self.persist_analysis(interaction=interaction, result=analysis_result)
            interaction.analyzed_at = datetime.now(UTC)
            interaction.error_message = None
        except SemanticAnalysisError as exc:
            analysis_row = self.persist_failed_analysis(interaction=interaction, error=exc)
            interaction.analyzed_at = datetime.now(UTC)
            interaction.status = "FAILED"
            interaction.error_message = str(exc)
            self.db.commit()
            raise

        delivery_result: dict[str, Any] | None = None
        if send_notification:
            try:
                delivery_result = self.delivery.deliver_test_result(
                    interaction=interaction,
                    analysis_result=analysis_result,
                )
                self._mark_delivery_success(
                    interaction=interaction,
                    delivery_result=delivery_result,
                    mode="live_run",
                )
            except DeliveryError as exc:
                self._mark_delivery_failure(
                    interaction=interaction,
                    error_message=str(exc),
                    mode="live_run",
                )
                self.db.commit()
                raise
        else:
            interaction.status = "ANALYZED"

        self.db.commit()

        return {
            "interaction_id": str(interaction.id),
            "external_id": interaction.external_id,
            "status": interaction.status,
            "analysis_id": str(analysis_row.id),
            "stt_provider": stt_provider,
            "ai_routing": (interaction.metadata_ or {}).get("ai_routing") or {},
            "legacy_card_score": analysis_result["score"].get("legacy_card_score"),
            "legacy_card_level": analysis_result["score"].get("legacy_card_level"),
            "delivery": delivery_result,
        }

    def replay_delivery(
        self,
        *,
        interaction_id: str | None = None,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        """Replay test-only delivery for an already persisted interaction/analysis."""
        interaction = self._get_interaction(
            interaction_id=interaction_id,
            external_id=external_id,
        )
        if interaction is None:
            raise DatabaseError("Replay target interaction was not found.")

        analysis = self._get_analysis_for_interaction(interaction.id)
        if analysis is None:
            raise DatabaseError(
                f"No persisted analysis found for interaction_id={interaction.id}."
            )
        if not isinstance(analysis.scores_detail, dict) or not analysis.scores_detail:
            raise DatabaseError(
                f"Analysis {analysis.id} does not contain a replayable scores_detail payload."
            )

        try:
            delivery_result = self.delivery.deliver_test_result(
                interaction=interaction,
                analysis_result=analysis.scores_detail,
            )
            self._mark_delivery_success(
                interaction=interaction,
                delivery_result=delivery_result,
                mode="delivery_replay",
            )
        except DeliveryError as exc:
            self._mark_delivery_failure(
                interaction=interaction,
                error_message=str(exc),
                mode="delivery_replay",
            )
            self.db.commit()
            raise

        self.db.commit()
        return {
            "interaction_id": str(interaction.id),
            "external_id": interaction.external_id,
            "status": interaction.status,
            "analysis_id": str(analysis.id),
            "delivery": delivery_result,
        }

    def persist_analysis(self, *, interaction: Interaction, result: dict[str, Any]) -> Analysis:
        """Store the analysis contract and derived entities in PostgreSQL."""
        analysis = self._get_or_create_analysis(
            interaction=interaction,
            instruction_version=result["instruction_version"],
        )
        forensics = CallsAnalyzer.consume_analysis_forensics(interaction)
        analysis.score_total = result["score"]["checklist_score"].get("score_percent")
        analysis.scores_detail = result
        analysis.strengths = result.get("strengths") or []
        analysis.weaknesses = result.get("gaps") or []
        analysis.recommendations = result.get("recommendations") or []
        analysis.call_topic = result["summary"].get("call_goal") or result["summary"].get("short_summary")
        analysis.topics = result.get("analytics_tags") or []
        analysis.is_failed = False
        analysis.fail_reason = None
        analysis.raw_llm_response = str(forensics.get("raw_llm_response") or json.dumps(result, ensure_ascii=False))

        self._replace_agreements(interaction=interaction, agreements=result.get("agreements") or [])
        self._replace_insights(interaction=interaction, result=result)
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def persist_failed_analysis(self, *, interaction: Interaction, error: SemanticAnalysisError) -> Analysis:
        """Persist a semantically invalid analysis attempt for bounded forensic debugging."""
        forensics = CallsAnalyzer.consume_analysis_forensics(interaction)
        normalized_result = dict(error.normalized_result or forensics.get("normalized_result") or {})
        instruction_version = str(
            normalized_result.get("instruction_version")
            or APPROVED_INSTRUCTION_VERSION
        )
        analysis = self._get_or_create_analysis(
            interaction=interaction,
            instruction_version=instruction_version,
        )

        checklist_score = dict(dict(normalized_result.get("score") or {}).get("checklist_score") or {})
        analysis.score_total = checklist_score.get("score_percent")
        analysis.scores_detail = normalized_result or None
        analysis.strengths = list(normalized_result.get("strengths") or [])
        analysis.weaknesses = list(normalized_result.get("gaps") or [])
        analysis.recommendations = list(normalized_result.get("recommendations") or [])
        summary = dict(normalized_result.get("summary") or {})
        analysis.call_topic = summary.get("call_goal") or summary.get("short_summary")
        analysis.topics = list(normalized_result.get("analytics_tags") or [])
        analysis.is_failed = True
        analysis.fail_reason = error.reason_code or str(error)
        analysis.raw_llm_response = str(forensics.get("raw_llm_response") or error.raw_response or "")

        self._replace_agreements(interaction=interaction, agreements=[])
        self._replace_insights(interaction=interaction, result={})
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def _get_or_create_analysis(self, *, interaction: Interaction, instruction_version: str) -> Analysis:
        """Return one analysis row keyed by interaction and instruction version."""
        analysis = (
            self.db.query(Analysis)
            .filter(
                Analysis.interaction_id == interaction.id,
                Analysis.instruction_version == instruction_version,
            )
            .first()
        )
        if analysis is None:
            analysis = Analysis(
                id=uuid4(),
                department_id=interaction.department_id,
                interaction_id=interaction.id,
                manager_id=interaction.manager_id,
                instruction_version=instruction_version,
            )
            self.db.add(analysis)

        analysis.department_id = interaction.department_id
        analysis.manager_id = interaction.manager_id
        analysis.instruction_version = instruction_version
        return analysis

    def _replace_agreements(self, *, interaction: Interaction, agreements: list[dict[str, Any]]) -> None:
        """Replace derived agreements for the current interaction."""
        (
            self.db.query(Agreement)
            .filter(Agreement.interaction_id == interaction.id)
            .delete(synchronize_session=False)
        )
        for item in agreements:
            self.db.add(
                Agreement(
                    id=uuid4(),
                    department_id=interaction.department_id,
                    interaction_id=interaction.id,
                    manager_id=interaction.manager_id,
                    text=item.get("agreement_text") or "",
                    responsible=item.get("owner"),
                    deadline=self._normalize_agreement_deadline(item),
                    next_step=item.get("next_step"),
                    status=item.get("status_initial") or "open",
                )
            )

    @staticmethod
    def _normalize_agreement_deadline(item: dict[str, Any]) -> str | None:
        """Fit agreement deadline into the current bounded DB schema without losing meaning."""
        due_date_text = str(item.get("due_date_text") or "").strip()
        if due_date_text and len(due_date_text) <= 20:
            return due_date_text

        due_date_iso = str(item.get("due_date_iso") or "").strip()
        if due_date_iso:
            normalized_iso = due_date_iso.replace("T", " ")
            if normalized_iso.endswith("+00:00"):
                normalized_iso = normalized_iso[:-6] + " UTC"
            if normalized_iso.endswith("Z"):
                normalized_iso = normalized_iso[:-1] + " UTC"
            if len(normalized_iso) <= 20:
                return normalized_iso
            if len(normalized_iso) >= 16:
                return normalized_iso[:16]

        if due_date_text:
            return due_date_text[:20]
        return None

    def _replace_insights(self, *, interaction: Interaction, result: dict[str, Any]) -> None:
        """Replace derived insight rows for the current interaction."""
        (
            self.db.query(Insight)
            .filter(Insight.interaction_id == interaction.id)
            .delete(synchronize_session=False)
        )

        for item in result.get("strengths") or []:
            self.db.add(
                Insight(
                    id=uuid4(),
                    department_id=interaction.department_id,
                    interaction_id=interaction.id,
                    category="strength",
                    topic=item.get("title"),
                    quote=item.get("evidence"),
                )
            )
        for item in result.get("gaps") or []:
            self.db.add(
                Insight(
                    id=uuid4(),
                    department_id=interaction.department_id,
                    interaction_id=interaction.id,
                    category="gap",
                    topic=item.get("title"),
                    quote=item.get("evidence"),
                )
            )
        for item in result.get("product_signals") or []:
            self.db.add(
                Insight(
                    id=uuid4(),
                    department_id=interaction.department_id,
                    interaction_id=interaction.id,
                    category=item.get("signal_type"),
                    topic=item.get("topic"),
                    quote=item.get("quote"),
                )
            )

    def _get_interaction_by_external_id(self, external_id: str) -> Interaction | None:
        """Load an interaction created from the selected OnlinePBX call."""
        return (
            self.db.query(Interaction)
            .filter(
                Interaction.department_id == self.department_id,
                Interaction.external_id == external_id,
            )
            .first()
        )

    def _get_interaction(
        self,
        *,
        interaction_id: str | None = None,
        external_id: str | None = None,
    ) -> Interaction | None:
        """Load an interaction by id or external id within the current department."""
        query = self.db.query(Interaction).filter(Interaction.department_id == self.department_id)
        if interaction_id:
            return query.filter(Interaction.id == interaction_id).first()
        if external_id:
            return query.filter(Interaction.external_id == external_id).first()
        raise DatabaseError("Provide interaction_id or external_id for delivery replay.")

    def _get_analysis_for_interaction(self, interaction_id: UUID) -> Analysis | None:
        """Load the latest persisted analysis for an interaction."""
        return (
            self.db.query(Analysis)
            .filter(
                Analysis.department_id == self.department_id,
                Analysis.interaction_id == interaction_id,
            )
            .order_by(Analysis.created_at.desc())
            .first()
        )

    def _mark_delivery_success(
        self,
        *,
        interaction: Interaction,
        delivery_result: dict[str, Any],
        mode: str,
    ) -> None:
        """Persist a successful delivery status and audit snapshot."""
        interaction.status = "DELIVERED"
        interaction.error_message = None
        interaction.metadata_ = self._build_delivery_audit(
            interaction=interaction,
            mode=mode,
            status="DELIVERED",
            targets=delivery_result.get("targets") or [],
            error_message=None,
        )

    def _mark_delivery_failure(
        self,
        *,
        interaction: Interaction,
        error_message: str,
        mode: str,
    ) -> None:
        """Persist a failed delivery status and audit snapshot."""
        interaction.status = "DELIVERY_FAILED"
        interaction.error_message = error_message
        interaction.metadata_ = self._build_delivery_audit(
            interaction=interaction,
            mode=mode,
            status="DELIVERY_FAILED",
            targets=[],
            error_message=error_message,
        )

    def _build_delivery_audit(
        self,
        *,
        interaction: Interaction,
        mode: str,
        status: str,
        targets: list[dict[str, Any]],
        error_message: str | None,
    ) -> dict[str, Any]:
        """Attach the last manual pilot delivery attempt to interaction metadata."""
        metadata = dict(interaction.metadata_ or {})
        metadata["manual_pilot_delivery"] = {
            "attempted_at": datetime.now(UTC).isoformat(),
            "mode": mode,
            "status": status,
            "targets": targets,
            "error_message": error_message,
        }
        return metadata
