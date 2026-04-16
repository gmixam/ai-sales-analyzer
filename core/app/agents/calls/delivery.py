"""Delivery helpers for manual pilot notifications."""

from __future__ import annotations

import json
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core_shared.config.settings import settings
from app.core_shared.db.models import Interaction
from app.core_shared.exceptions import DeliveryError


@dataclass(slots=True)
class DeliveryTarget:
    """Resolved test delivery destination."""

    channel: str
    address: str


CALL_TYPE_LABELS = {
    "sales_primary": "Продажи — первичный",
    "sales_repeat": "Продажи — повторный",
    "mixed": "Смешанный",
    "support": "Поддержка",
    "internal": "Внутренний",
    "other": "Другое",
}

SCENARIO_TYPE_LABELS = {
    "cold_outbound": "Холодный / исходящий",
    "hot_incoming_contact": "Горячий / входящий контакт",
    "warm_webinar_or_lead": "Тёплый / вебинар / заявка",
    "repeat_contact": "Повторный контакт",
    "after_signed_document": "После подписания документа",
    "post_sale_follow_up": "Постпродажное сопровождение",
    "mixed_scenario": "Смешанный сценарий",
    "other": "Другое",
}

LEVEL_LABELS = {
    "problematic": "Проблемный",
    "basic": "Базовый",
    "strong": "Сильный",
    "excellent": "Отличный",
}

PRIORITY_LABELS = {
    "high": "высокий",
    "medium": "средний",
    "low": "низкий",
}

BUSINESS_TEXT_TRANSLATIONS = {
    "The call involved a detailed walkthrough of the client's subscription features and document access process.": (
        "Менеджер подробно провёл клиента по возможностям подписки и доступу к документам."
    ),
    "The client was guided through accessing documents and features.": (
        "Клиенту помогли с доступом к документам и базовыми возможностями сервиса."
    ),
    "The client will be contacted by the service department for further assistance.": (
        "С клиентом свяжется отдел сервиса и поможет по дальнейшим вопросам."
    ),
    "No inquiry into current processes.": (
        "Не уточнил, как у клиента сейчас устроен процесс."
    ),
    "Explanation was clear but could be crisper.": (
        "Объяснение было понятным, но не хватило краткости."
    ),
    "Clear reason provided.": "Чётко обозначил цель звонка.",
    "Value linked to client context.": "Связал ценность решения с контекстом клиента.",
    "Ask about the client's current processes to better tailor the presentation.": (
        "Отдельно уточнять, как у клиента сейчас устроен процесс, чтобы точнее подстраивать презентацию."
    ),
    "Use more concise examples to enhance clarity.": (
        "Давать более краткие и понятные примеры, чтобы объяснение было яснее."
    ),
}


class CallsDelivery:
    """Build and send manual pilot notifications to test channels only."""

    def __init__(self, department_id: str, db: Session):
        self.department_id = UUID(department_id)
        self.db = db
        self.logger = structlog.get_logger().bind(
            module="calls.delivery",
            department_id=department_id,
        )

    def resolve_test_targets(self) -> list[DeliveryTarget]:
        """Return configured test-only delivery targets."""
        targets: list[DeliveryTarget] = []
        if settings.has_test_telegram_delivery:
            targets.append(
                DeliveryTarget(
                    channel="telegram",
                    address=settings.test_delivery_telegram_chat_id,
                )
            )
        if settings.has_test_email_delivery:
            targets.append(
                DeliveryTarget(
                    channel="email",
                    address=settings.test_delivery_email_to,
                )
            )
        if not targets:
            raise DeliveryError(
                "No test delivery target configured. Set TEST_DELIVERY_TELEGRAM_CHAT_ID and/or "
                "TEST_DELIVERY_EMAIL_TO."
            )
        return targets

    def build_notification_text(
        self,
        interaction: Interaction,
        analysis_result: dict[str, Any],
    ) -> str:
        """Render a compact, evidence-based single-call card for pilot validation."""
        call = analysis_result["call"]
        classification = analysis_result["classification"]
        summary = self._build_summary_view(interaction=interaction, analysis_result=analysis_result)
        score = analysis_result["score"]
        checklist_score = score["checklist_score"]
        strengths = analysis_result.get("strengths") or []
        gaps = analysis_result.get("gaps") or []
        recommendations = analysis_result.get("recommendations") or []
        follow_up = analysis_result["follow_up"]
        criterion_names = self._build_criterion_name_map(analysis_result=analysis_result)

        stage_lines = []
        for stage in analysis_result.get("score_by_stage") or []:
            stage_lines.append(
                f"- {stage['stage_name']}: {stage['stage_score']}/{stage['max_stage_score']}"
            )
        if not stage_lines:
            stage_lines = ["- Этапы не зафиксированы"]

        strength_lines = self._render_finding_lines(
            items=strengths,
            criterion_names=criterion_names,
            category="strength",
        )
        gap_lines = self._render_finding_lines(
            items=gaps,
            criterion_names=criterion_names,
            category="gap",
        )
        recommendation_lines = self._render_recommendation_lines(
            items=recommendations,
            criterion_names=criterion_names,
        )
        score_line = self._build_score_line(score=score, checklist_score=checklist_score)
        follow_up_line = self._build_follow_up_line(
            interaction=interaction,
            analysis_result=analysis_result,
        )
        manager_display = self._build_manager_display(
            interaction=interaction,
            analysis_result=analysis_result,
        )
        call_type_label = CALL_TYPE_LABELS.get(
            classification.get("call_type"),
            classification.get("call_type") or "—",
        )
        scenario_label = SCENARIO_TYPE_LABELS.get(
            classification.get("scenario_type"),
            classification.get("scenario_type") or "—",
        )
        critical_failure = "да" if score.get("critical_failure") else "нет"
        eligibility = classification.get("analysis_eligibility") or "—"
        eligibility_reason = classification.get("eligibility_reason") or "—"

        return "\n".join(
            [
                "Карточка звонка — ручная проверка",
                f"Interaction ID: {interaction.id}",
                f"Внешний код: {call.get('external_call_code')}",
                f"Менеджер: {manager_display}",
                f"Контакт: {call.get('contact_name') or call.get('contact_phone') or '—'}",
                f"Дата/время: {call.get('call_started_at')}",
                f"Длительность: {call.get('duration_sec')} сек",
                f"Тип звонка: {call_type_label}",
                f"Сценарий: {scenario_label}",
                f"Статус анализа: {eligibility} / {eligibility_reason}",
                "",
                f"Краткое резюме: {summary.get('short_summary')}",
                f"Итог: {summary.get('outcome_text')}",
                f"Следующий шаг: {summary.get('next_step_text') or 'не зафиксирован'}",
                "",
                score_line,
                f"Критический сбой: {critical_failure}",
                "",
                "Этапы:",
                *stage_lines,
                "",
                "Сильные стороны:",
                *strength_lines,
                "",
                "Зоны роста:",
                *gap_lines,
                "",
                "Рекомендации:",
                *recommendation_lines,
                "",
                follow_up_line,
            ]
        )

    @staticmethod
    def _contains_cyrillic(value: str | None) -> bool:
        """Return True when the text contains Cyrillic characters."""
        if not value:
            return False
        return bool(re.search(r"[А-Яа-яЁё]", value))

    def _localize_business_text(
        self,
        value: Any,
        *,
        default: str,
        fallback: str | None = None,
    ) -> str:
        """Return Russian business text while preserving allowed system values elsewhere."""
        text = str(value).strip() if value is not None else ""
        if not text:
            return default
        if self._contains_cyrillic(text):
            return text
        translated = BUSINESS_TEXT_TRANSLATIONS.get(text)
        if translated:
            return translated
        return fallback or default

    @staticmethod
    def _build_criterion_name_map(analysis_result: dict[str, Any]) -> dict[str, str]:
        """Resolve criterion names from the persisted score_by_stage payload."""
        mapping: dict[str, str] = {}
        for stage in analysis_result.get("score_by_stage") or []:
            for criterion in stage.get("criteria_results") or []:
                criterion_code = criterion.get("criterion_code")
                criterion_name = criterion.get("criterion_name")
                if criterion_code and criterion_name:
                    mapping[str(criterion_code)] = str(criterion_name)
        return mapping

    def _build_summary_view(
        self,
        *,
        interaction: Interaction,
        analysis_result: dict[str, Any],
    ) -> dict[str, str]:
        """Return Russian summary fields for manager-facing delivery."""
        summary = analysis_result.get("summary") or {}
        transcript = (interaction.text or "").lower()
        short_summary = self._localize_business_text(
            summary.get("short_summary"),
            default=self._fallback_short_summary(transcript),
        )
        outcome_text = self._localize_business_text(
            summary.get("outcome_text"),
            default=self._fallback_outcome_text(transcript),
        )
        next_step_default = self._fallback_next_step_text(transcript, analysis_result.get("follow_up") or {})
        next_step_text = self._localize_business_text(
            summary.get("next_step_text"),
            default=next_step_default,
            fallback=next_step_default,
        )
        return {
            "short_summary": short_summary,
            "outcome_text": outcome_text,
            "next_step_text": next_step_text,
        }

    def _build_manager_display(
        self,
        *,
        interaction: Interaction,
        analysis_result: dict[str, Any],
    ) -> str:
        """Render a readable manager identity, including explicit fallback state."""
        call = analysis_result.get("call") or {}
        manager_name = str(call.get("manager_name") or "").strip()
        metadata = getattr(interaction, "metadata_", {}) or {}
        mapping_source = str(metadata.get("mapping_source") or "").strip()
        extension = str(metadata.get("extension") or manager_name or "").strip()

        if getattr(interaction, "manager_id", None):
            return manager_name or extension or "—"

        if manager_name and re.search(r"[A-Za-zА-Яа-яЁё]", manager_name):
            return manager_name

        if mapping_source == "manual_fallback" and extension:
            return f"не сопоставлен (внутренний номер {extension})"

        return manager_name or extension or "—"

    @staticmethod
    def _fallback_short_summary(transcript: str) -> str:
        """Build a Russian fallback summary from transcript keywords."""
        themes: list[str] = []
        if any(token in transcript for token in ("доступ", "логин", "парол")):
            themes.append("доступ в систему")
        if "документ" in transcript:
            themes.append("документы")
        if "подпис" in transcript:
            themes.append("возможности подписки")
        if "сайт" in transcript:
            themes.append("работу с сайтом")
        ordered_themes = list(dict.fromkeys(themes))
        if ordered_themes:
            return "Менеджер подробно провёл клиента по темам: " + ", ".join(ordered_themes) + "."
        return "Менеджер провёл содержательный разговор по текущему использованию сервиса."

    @staticmethod
    def _fallback_outcome_text(transcript: str) -> str:
        """Build a Russian fallback outcome from transcript keywords."""
        has_access_topic = any(token in transcript for token in ("доступ", "логин", "парол"))
        if "отдел сервиса" in transcript and has_access_topic:
            return "Клиенту помогли с доступом и передали дальнейшее сопровождение в отдел сервиса."
        if has_access_topic:
            return "Клиенту помогли с доступом и объяснили основные возможности сервиса."
        return "Менеджер помог клиенту разобраться в текущем вопросе и обозначил дальнейшие действия."

    def _fallback_next_step_text(self, transcript: str, follow_up: dict[str, Any]) -> str:
        """Build a Russian fallback next-step line."""
        if "отдел сервиса" in transcript:
            return "С клиентом свяжется отдел сервиса и поможет по дальнейшим вопросам."
        if follow_up.get("next_step_fixed"):
            return "Следующий шаг зафиксирован и требует дальнейшего сопровождения клиента."
        return "Следующий шаг не зафиксирован."

    def _render_finding_lines(
        self,
        *,
        items: list[dict[str, Any]],
        criterion_names: dict[str, str],
        category: str,
    ) -> list[str]:
        """Render strengths or gaps in a Russian manager-facing form."""
        if not items:
            return (
                ["- Нет зафиксированных сильных сторон"]
                if category == "strength"
                else ["- Нет зафиксированных зон роста"]
            )

        lines: list[str] = []
        for item in items[:3]:
            criterion_name = criterion_names.get(str(item.get("criterion_code") or ""), "")
            title_default = (
                criterion_name
                or "Сильная сторона разговора"
                if category == "strength"
                else criterion_name
                or "Зона роста"
            )
            detail_default = (
                "сильная сторона подтверждена в разговоре"
                if category == "strength"
                else "нужна доработка в следующих звонках"
            )
            title = self._localize_business_text(
                item.get("title"),
                default=title_default,
                fallback=criterion_name or title_default,
            )
            detail = self._localize_business_text(
                item.get("impact") or item.get("comment"),
                default=detail_default,
            )
            lines.append(f"- {title}: {detail}")
        return lines

    def _render_recommendation_lines(
        self,
        *,
        items: list[dict[str, Any]],
        criterion_names: dict[str, str],
    ) -> list[str]:
        """Render recommendations in Russian and tolerate both old and approved shapes."""
        if not items:
            return ["- Нет рекомендаций"]

        lines: list[str] = []
        for item in items[:3]:
            priority_code = str(item.get("priority") or "medium").lower()
            priority_label = PRIORITY_LABELS.get(priority_code, "средний")
            criterion_name = criterion_names.get(str(item.get("criterion_code") or ""), "")
            russian_text = self._localize_business_text(
                item.get("better_phrase") or item.get("recommendation") or item.get("problem"),
                default=(
                    f"Усилить критерий «{criterion_name}»."
                    if criterion_name
                    else "Уточнить формулировку рекомендации."
                ),
            )
            lines.append(f"- [{priority_label}] {russian_text}")
        return lines

    def _build_score_line(
        self,
        *,
        score: dict[str, Any],
        checklist_score: dict[str, Any],
    ) -> str:
        """Render score block without exposing empty legacy values."""
        checklist_level = LEVEL_LABELS.get(
            checklist_score.get("level"),
            checklist_score.get("level") or "—",
        )
        parts = [
            (
                "Скоринг по чек-листу: "
                f"{checklist_score.get('total_points')}/{checklist_score.get('max_points')} "
                f"({checklist_score.get('score_percent')}%, {checklist_level})"
            )
        ]
        legacy_score = score.get("legacy_card_score")
        legacy_level = score.get("legacy_card_level")
        if legacy_score is not None and legacy_level:
            parts.append(
                "Legacy card: "
                f"{legacy_score} ({LEVEL_LABELS.get(legacy_level, legacy_level)})"
            )
        return " | ".join(parts)

    def _build_follow_up_line(
        self,
        *,
        interaction: Interaction,
        analysis_result: dict[str, Any],
    ) -> str:
        """Render follow-up block in Russian for manager-facing delivery."""
        follow_up = analysis_result.get("follow_up") or {}
        transcript = (interaction.text or "").lower()
        next_step_text = self._localize_business_text(
            follow_up.get("next_step_text"),
            default=self._fallback_next_step_text(transcript, follow_up),
            fallback=self._fallback_next_step_text(transcript, follow_up),
        )
        reason_not_fixed = self._localize_business_text(
            follow_up.get("reason_not_fixed"),
            default="—",
            fallback="—",
        )
        next_step_fixed = "да" if follow_up.get("next_step_fixed") else "нет"
        return (
            "Дальнейшие действия: "
            f"шаг зафиксирован — {next_step_fixed}; "
            f"следующий шаг — {next_step_text}; "
            f"причина, если не зафиксирован — {reason_not_fixed}"
        )

    def send_telegram(self, chat_id: str, text: str) -> dict[str, Any]:
        """Send a test notification to Telegram."""
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=30) as client:
                chunks = self._chunk_telegram_text(text)
                for chunk in chunks:
                    response = client.post(url, json={"chat_id": chat_id, "text": chunk})
                    response.raise_for_status()
            return {
                "channel": "telegram",
                "target": chat_id,
                "status": "sent",
                "messages_sent": len(chunks),
            }
        except httpx.HTTPError as exc:
            raise DeliveryError(f"Telegram delivery failed: {exc}") from exc

    def send_telegram_document(
        self,
        *,
        chat_id: str,
        filename: str,
        content: bytes,
        caption: str,
    ) -> dict[str, Any]:
        """Send a PDF report document to Telegram."""
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendDocument"
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    url,
                    data={
                        "chat_id": chat_id,
                        "caption": caption[:1000],
                    },
                    files={
                        "document": (filename, content, "application/pdf"),
                    },
                )
                response.raise_for_status()
            return {
                "channel": "telegram",
                "target": chat_id,
                "status": "sent",
                "artifact": filename,
            }
        except httpx.HTTPError as exc:
            raise DeliveryError(f"Telegram delivery failed: {exc}") from exc

    @staticmethod
    def _chunk_telegram_text(text: str, *, max_len: int = 3500) -> list[str]:
        """Split long Telegram messages into safe chunks."""
        normalized = text.strip()
        if len(normalized) <= max_len:
            return [normalized]

        chunks: list[str] = []
        remaining = normalized
        while len(remaining) > max_len:
            split_at = remaining.rfind("\n", 0, max_len)
            if split_at <= 0:
                split_at = max_len
            chunk = remaining[:split_at].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[split_at:].strip()
        if remaining:
            chunks.append(remaining)
        return chunks or [normalized]

    def send_email_message(
        self,
        *,
        email_to: str,
        subject: str,
        text: str,
        html: str | None = None,
        cc_emails: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send one email with optional HTML and CC recipients."""
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from or settings.smtp_user
        message["To"] = email_to
        message.set_content(text)
        if cc_emails:
            message["Cc"] = ", ".join(cc_emails)
        if html:
            message.add_alternative(html, subtype="html")
        for attachment in attachments or []:
            message.add_attachment(
                attachment["content"],
                maintype=attachment.get("maintype", "application"),
                subtype=attachment.get("subtype", "octet-stream"),
                filename=attachment["filename"],
            )

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            return {
                "channel": "email",
                "target": email_to,
                "cc": cc_emails or [],
                "status": "sent",
            }
        except smtplib.SMTPAuthenticationError as exc:
            raise DeliveryError(
                f"Email delivery failed: SMTP auth error {exc.smtp_code}"
            ) from exc
        except smtplib.SMTPException as exc:
            raise DeliveryError(f"Email delivery failed: {exc}") from exc
        except OSError as exc:
            raise DeliveryError(f"Email delivery failed: {exc}") from exc

    def send_email(self, email_to: str, subject: str, text: str) -> dict[str, Any]:
        """Send a test notification to Email."""
        return self.send_email_message(
            email_to=email_to,
            subject=subject,
            text=text,
        )

    def preview_report_delivery(
        self,
        *,
        primary_email: str | None,
        cc_emails: list[str],
        send_business_email: bool,
        email_resolution_error: str | None = None,
    ) -> dict[str, Any]:
        """Return the effective operator-facing delivery preview for one report."""
        return {
            "mode": "split_operator_delivery",
            "telegram_test_delivery": {
                "enabled": True,
                "target": settings.test_delivery_telegram_chat_id or None,
                "status": "planned" if settings.has_test_telegram_delivery else "failed",
                "error": (
                    None
                    if settings.has_test_telegram_delivery
                    else "Telegram test delivery is required for manual runs, but TEST_DELIVERY_TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN is not configured."
                ),
            },
            "email_delivery": {
                "enabled": send_business_email,
                "primary_email": primary_email,
                "cc_emails": cc_emails,
                "status": (
                    "planned"
                    if send_business_email and primary_email and not email_resolution_error
                    else "blocked"
                    if send_business_email and email_resolution_error
                    else "skipped"
                ),
                "error": email_resolution_error,
            },
            "resolved_email": {
                "primary_email": primary_email,
                "cc_emails": cc_emails,
            },
        }

    def deliver_operator_report(
        self,
        *,
        primary_email: str | None,
        cc_emails: list[str],
        subject: str,
        text: str,
        html: str | None = None,
        pdf_bytes: bytes,
        pdf_filename: str,
        template_meta: dict[str, Any] | None,
        send_business_email: bool,
        email_resolution_error: str | None = None,
        morning_card_text: str | None = None,
    ) -> dict[str, Any]:
        """Deliver one operator report via mandatory Telegram test channel plus optional business email."""
        preview = self.preview_report_delivery(
            primary_email=primary_email,
            cc_emails=cc_emails,
            send_business_email=send_business_email,
            email_resolution_error=email_resolution_error,
        )
        targets: list[dict[str, Any]] = []
        telegram_state = dict(preview["telegram_test_delivery"])
        email_state = dict(preview["email_delivery"])

        if morning_card_text:
            telegram_caption = morning_card_text
        else:
            telegram_caption = "\n".join(
                [
                    subject,
                    f"Template: {(template_meta or {}).get('template_id') or 'unknown'}",
                    f"Resolved email: {primary_email or 'not available'}",
                ]
            )
        try:
            if not settings.has_test_telegram_delivery:
                raise DeliveryError(
                    "Telegram test delivery is required for manual runs, but TEST_DELIVERY_TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN is not configured."
                )
            telegram_delivery = self.send_telegram_document(
                chat_id=settings.test_delivery_telegram_chat_id,
                filename=pdf_filename,
                content=pdf_bytes,
                caption=telegram_caption,
            )
            telegram_state.update(
                {
                    "status": "delivered",
                    "artifact": pdf_filename,
                }
            )
            targets.append(telegram_delivery)
            self.logger.info(
                "delivery.report_telegram_sent",
                telegram_chat_id=settings.test_delivery_telegram_chat_id,
                resolved_primary_email=primary_email,
                resolved_cc_emails=cc_emails,
            )
        except DeliveryError as exc:
            telegram_state.update({"status": "failed", "error": str(exc)})

        if send_business_email:
            if email_resolution_error:
                email_state.update({"status": "blocked", "error": email_resolution_error})
            elif primary_email:
                try:
                    email_delivery = self.deliver_report_email(
                        primary_email=primary_email,
                        cc_emails=cc_emails,
                        subject=subject,
                        text=text,
                        html=html,
                        pdf_bytes=pdf_bytes,
                        pdf_filename=pdf_filename,
                    )
                    targets.extend(email_delivery.get("targets", []))
                    email_state.update({"status": "delivered", "artifact": pdf_filename})
                except DeliveryError as exc:
                    email_state.update({"status": "failed", "error": str(exc)})
            else:
                email_state.update(
                    {
                        "status": "blocked",
                        "error": "Business email delivery is enabled, but primary recipient is not resolved.",
                    }
                )
        else:
            email_state.update({"status": "skipped"})

        return {
            "targets": targets,
            "subject": subject,
            "preview": text,
            "artifact": {
                "filename": pdf_filename,
                "media_type": "application/pdf",
                "template": template_meta,
            },
            "transport": {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": telegram_state,
                "email_delivery": email_state,
                "resolved_email": {
                    "primary_email": primary_email,
                    "cc_emails": cc_emails,
                },
            },
        }

    def deliver_report_email(
        self,
        *,
        primary_email: str,
        cc_emails: list[str],
        subject: str,
        text: str,
        html: str | None = None,
        pdf_bytes: bytes,
        pdf_filename: str,
    ) -> dict[str, Any]:
        """Deliver a bounded reporting-pilot email."""
        delivery = self.send_email_message(
            email_to=primary_email,
            subject=subject,
            text=text,
            html=html,
            cc_emails=cc_emails,
            attachments=[
                {
                    "filename": pdf_filename,
                    "content": pdf_bytes,
                    "maintype": "application",
                    "subtype": "pdf",
                }
            ],
        )
        self.logger.info(
            "delivery.report_email_sent",
            primary_email=primary_email,
            cc_emails=cc_emails,
        )
        return {
            "targets": [delivery],
            "subject": subject,
            "preview": text,
        }

    def deliver_test_result(
        self,
        interaction: Interaction,
        analysis_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Send the single-call analysis to configured test channels."""
        text = self.build_notification_text(
            interaction=interaction,
            analysis_result=analysis_result,
        )
        targets = self.resolve_test_targets()
        deliveries: list[dict[str, Any]] = []

        for target in targets:
            if target.channel == "telegram":
                deliveries.append(self.send_telegram(chat_id=target.address, text=text))
                continue
            if target.channel == "email":
                subject = (
                    "AI Sales Analyzer manual pilot — "
                    f"{analysis_result['call'].get('external_call_code')}"
                )
                deliveries.append(
                    self.send_email(email_to=target.address, subject=subject, text=text)
                )
                continue
            raise DeliveryError(f"Unsupported delivery channel: {target.channel}")

        self.logger.info(
            "delivery.sent",
            interaction_id=str(interaction.id),
            channels=[item["channel"] for item in deliveries],
        )
        return {
            "targets": deliveries,
            "preview": text,
            "analysis_result_excerpt": json.dumps(
                {
                    "interaction_id": str(interaction.id),
                    "call": analysis_result["call"],
                    "classification": analysis_result["classification"],
                    "summary": analysis_result["summary"],
                    "score": analysis_result["score"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        }
