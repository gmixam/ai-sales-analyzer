"""Audio extraction and speech-to-text pipeline for call interactions."""

from __future__ import annotations

from dataclasses import replace
import tarfile
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import structlog
from sqlalchemy.orm import Session

from app.agents.calls.schemas import SpeakerSegment, TranscriptResult
from app.core_shared.ai_routing import AIProviderRouteCandidate, AIProviderRouter
from app.core_shared.config.settings import settings
from app.core_shared.db.models import Interaction
from app.core_shared.exceptions import ExtractionError


class CallsExtractor:
    """Download call archives, extract audio, and transcribe calls."""

    OPENAI_STT_ENDPOINT_PATH = "/audio/transcriptions"

    def __init__(self, department_id: str, db: Session):
        self.department_id = UUID(department_id)
        self.db = db
        self.audio_dir = Path("/tmp/audio")
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.logger = structlog.get_logger().bind(
            module="calls.extractor",
            department_id=department_id,
        )
        self.ai_router = AIProviderRouter()

    def download_and_extract(self, interaction: Interaction) -> Path:
        """Download a call artifact and return an extracted audio file path."""
        log = self.logger.bind(interaction_id=str(interaction.id))
        if not interaction.raw_ref:
            raise ExtractionError("Missing raw_ref for interaction audio download")

        archive_path = self.audio_dir / f"{interaction.external_id or interaction.id}.tar"
        url = interaction.raw_ref
        headers = {"Authorization": f"Bearer {settings.onlinepbx_api_key}"}
        safe_url = self._safe_url(url)

        log.info("extractor.download.start", url=safe_url)
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExtractionError(
                f"Failed to download audio artifact: status={exc.response.status_code} "
                f"url={safe_url} content_type={exc.response.headers.get('content-type')}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ExtractionError(f"Failed to download audio artifact: url={safe_url} error={exc}") from exc

        content_type = response.headers.get("content-type", "").split(";")[0].lower()
        detected_suffix = Path(urlparse(url).path).suffix.lower()
        if detected_suffix in {".mp3", ".wav"} or content_type in {
            "audio/mpeg",
            "audio/mp3",
            "audio/wav",
            "audio/x-wav",
        }:
            audio_suffix = detected_suffix or self._suffix_from_content_type(content_type)
            extracted_path = self.audio_dir / f"{interaction.external_id or interaction.id}{audio_suffix}"
            extracted_path.write_bytes(response.content)
            log.info(
                "extractor.download.direct_audio",
                url=safe_url,
                content_type=content_type,
                path=str(extracted_path),
            )
            return extracted_path

        archive_path.write_bytes(response.content)
        log.info(
            "extractor.download.done",
            path=str(archive_path),
            url=safe_url,
            content_type=content_type,
        )

        selected_name: str | None = None
        selected_size = -1
        selected_suffix = ".mp3"

        try:
            with tarfile.open(archive_path) as tar:
                members = [m for m in tar.getmembers() if m.isfile()]
                audio_members = [
                    member
                    for member in members
                    if Path(member.name).suffix.lower() in {".mp3", ".wav"}
                ]
                if not audio_members:
                    raise ExtractionError("No audio file in archive")

                for member in audio_members:
                    if member.size > selected_size:
                        selected_name = member.name
                        selected_size = member.size
                        selected_suffix = Path(member.name).suffix.lower() or ".mp3"

                if selected_name is None:
                    raise ExtractionError("No audio file in archive")

                safe_name = Path(selected_name).name
                extracted_path = self.audio_dir / f"{interaction.external_id or interaction.id}{selected_suffix}"
                log.info("extractor.archive.selected", member=safe_name, size=selected_size)

                extracted_file = tar.extractfile(selected_name)
                if extracted_file is None:
                    raise ExtractionError("No audio file in archive")

                with extracted_file, extracted_path.open("wb") as destination:
                    destination.write(extracted_file.read())
        except tarfile.TarError as exc:
            raise ExtractionError(f"Failed to extract audio archive: {exc}") from exc
        finally:
            archive_path.unlink(missing_ok=True)

        log.info("extractor.archive.extracted", path=str(extracted_path))
        return extracted_path

    def transcribe(
        self,
        audio_path: Path,
        interaction_id: str,
        stt_provider: str | None = None,
    ) -> tuple[TranscriptResult, dict[str, Any]]:
        """Transcribe audio with the configured STT provider."""
        route_plan = self.ai_router.build_route_plan(
            layer="stt",
            subject_key=interaction_id,
            provider_override=stt_provider,
        )
        selected = route_plan.current_candidate()
        self.logger.info(
            "extractor.stt_route_selected",
            interaction_id=interaction_id,
            layer="stt",
            policy=route_plan.policy,
            provider=selected.provider,
            account_alias=selected.account_alias,
            model=selected.model,
            forced_override=route_plan.forced_override,
        )

        while True:
            candidate = route_plan.current_candidate()
            try:
                result, execution_details = self._transcribe_with_candidate(
                    audio_path=audio_path,
                    interaction_id=interaction_id,
                    candidate=candidate,
                )
                route_plan.mark_attempt_success()
                return result, route_plan.to_metadata(
                    request_kind="speech_to_text",
                    notes="STT runtime request completed.",
                    executed_endpoint_path=execution_details.get("executed_endpoint_path"),
                    provider_request_id=execution_details.get("provider_request_id"),
                )
            except ExtractionError as exc:
                can_fallback = route_plan.mark_attempt_failure(str(exc))
                if can_fallback:
                    self.logger.warning(
                        "extractor.stt_fallback",
                        interaction_id=interaction_id,
                        layer="stt",
                        failed_provider=candidate.provider,
                        failed_account_alias=candidate.account_alias,
                        failed_model=candidate.model,
                        policy=route_plan.policy,
                        error=str(exc),
                    )
                    continue
                raise ExtractionError(f"STT routing failed: {exc}") from exc

    def _transcribe_with_candidate(
        self,
        *,
        audio_path: Path,
        interaction_id: str,
        candidate: AIProviderRouteCandidate,
    ) -> tuple[TranscriptResult, dict[str, Any]]:
        """Run STT against one routed provider candidate."""
        provider = candidate.provider.strip().lower()
        if provider == "assemblyai":
            try:
                self.ai_router.ensure_execution_compatibility(
                    candidate,
                    executor_label="STT vendor-specific executor",
                    required_execution_mode="vendor_specific",
                )
            except Exception as exc:
                raise ExtractionError(f"Unsupported STT adapter path: {exc}") from exc
            return self._transcribe_assemblyai(
                audio_path=audio_path,
                interaction_id=interaction_id,
                candidate=candidate,
            )
        if provider == "openai":
            try:
                compatibility_candidate = candidate
                if (candidate.endpoint or "").rstrip("/") == "/audio/transcriptions":
                    # OpenAI SDK already targets the transcription route internally, so this
                    # known-safe endpoint hint should not block the routed Whisper executor.
                    compatibility_candidate = replace(candidate, endpoint=None)
                self.ai_router.ensure_execution_compatibility(
                    compatibility_candidate,
                    executor_label="STT OpenAI-compatible executor",
                    required_execution_mode="openai_compatible",
                )
            except Exception as exc:
                raise ExtractionError(f"Unsupported STT adapter path: {exc}") from exc
            return self._transcribe_whisper(
                audio_path=audio_path,
                interaction_id=interaction_id,
                candidate=candidate,
            )
        try:
            self.ai_router.ensure_execution_compatibility(
                candidate,
                executor_label="STT executor",
            )
        except Exception as exc:
            raise ExtractionError(f"Unsupported STT adapter path: {exc}") from exc
        raise ExtractionError(f"Unsupported STT adapter path: provider '{provider}' has no executor.")

    def _transcribe_assemblyai(
        self,
        *,
        audio_path: Path,
        interaction_id: str,
        candidate: AIProviderRouteCandidate,
    ) -> tuple[TranscriptResult, dict[str, Any]]:
        """Transcribe audio with AssemblyAI and return a normalized result."""
        try:
            import assemblyai as aai
        except ImportError as exc:
            raise ExtractionError("AssemblyAI SDK is not installed") from exc

        aai.settings.api_key = candidate.resolved_api_key()

        config = aai.TranscriptionConfig(
            language_code=settings.stt_language or settings.assemblyai_language,
            speaker_labels=True,
            speakers_expected=2,
        )

        transcriber = aai.Transcriber()
        last_error: Exception | None = None
        attempts_total = max(1, candidate.max_retries_for_this_provider + 1)
        transcript = None
        for _ in range(attempts_total):
            try:
                transcript = transcriber.transcribe(str(audio_path), config=config)
                break
            except Exception as exc:
                last_error = exc
        if transcript is None:
            raise ExtractionError(f"AssemblyAI transcription failed: {last_error}")

        if transcript.status == aai.TranscriptStatus.error:
            raise ExtractionError(f"AssemblyAI error: {transcript.error}")

        utterances = transcript.utterances or []
        segments = [
            SpeakerSegment(
                speaker=str(utterance.speaker),
                text=utterance.text,
                start_ms=utterance.start,
                end_ms=utterance.end,
            )
            for utterance in utterances
        ]

        confidences = [
            word.confidence
            for word in (transcript.words or [])
            if getattr(word, "confidence", None) is not None
        ]
        avg_confidence = mean(confidences) if confidences else None

        return (
            TranscriptResult(
                interaction_id=interaction_id,
                full_text=transcript.text or "",
                segments=segments,
                speaker_a_is_manager=True,
                confidence=avg_confidence,
                duration_sec=getattr(transcript, "audio_duration", None),
            ),
            {
                "executed_endpoint_path": None,
                "provider_request_id": self._read_openai_attr(transcript, "_request_id"),
            },
        )

    def _transcribe_whisper(
        self,
        *,
        audio_path: Path,
        interaction_id: str,
        candidate: AIProviderRouteCandidate,
    ) -> tuple[TranscriptResult, dict[str, Any]]:
        """Transcribe audio with OpenAI Whisper for live validation."""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ExtractionError("OpenAI SDK is not installed for Whisper STT") from exc

        api_key = candidate.resolved_api_key()
        client = OpenAI(api_key=api_key, base_url=candidate.api_base)

        last_error: Exception | None = None
        attempts_total = max(1, candidate.max_retries_for_this_provider + 1)
        for _ in range(attempts_total):
            try:
                with audio_path.open("rb") as audio_file:
                    transcript = client.audio.transcriptions.create(
                        model=candidate.model,
                        file=audio_file,
                        language=settings.stt_language,
                        response_format="verbose_json",
                        timeout=candidate.timeout_sec or settings.openai_timeout_sec,
                    )
                break
            except Exception as exc:
                last_error = exc
        else:
            raise ExtractionError(f"Whisper STT failed: {last_error}")

        transcript_text = self._read_openai_attr(transcript, "text") or ""
        raw_segments = self._read_openai_attr(transcript, "segments") or []
        duration_sec = self._read_openai_attr(transcript, "duration")
        segments = self._normalize_whisper_segments(raw_segments, transcript_text)

        return (
            TranscriptResult(
                interaction_id=interaction_id,
                full_text=transcript_text,
                segments=segments,
                speaker_a_is_manager=True,
                confidence=None,
                duration_sec=int(duration_sec) if duration_sec is not None else None,
            ),
            {
                "executed_endpoint_path": self.OPENAI_STT_ENDPOINT_PATH,
                "provider_request_id": self._read_openai_attr(transcript, "_request_id"),
            },
        )

    async def process(
        self,
        interaction: Interaction,
        stt_provider: str | None = None,
    ) -> TranscriptResult:
        """Run the full extraction and transcription pipeline for one call."""
        log = self.logger.bind(interaction_id=str(interaction.id))
        log.info("extractor.start")

        interaction.status = "TRANSCRIBING"
        self.db.commit()

        try:
            audio_path = self.download_and_extract(interaction)
            log.info("extractor.audio_ready", path=str(audio_path))

            result, stt_routing = self.transcribe(
                audio_path,
                str(interaction.id),
                stt_provider=stt_provider,
            )
            log.info(
                "extractor.transcribed",
                chars=len(result.full_text),
                segments=len(result.segments),
            )

            metadata = dict(interaction.metadata_ or {})
            metadata["segments"] = [segment.model_dump() for segment in result.segments]
            metadata["confidence"] = result.confidence
            metadata["ai_routing"] = self._merge_ai_routing_metadata(
                metadata.get("ai_routing"),
                stt_routing,
            )

            interaction.text = result.full_text
            interaction.status = "TRANSCRIBED"
            interaction.metadata_ = metadata
            self.db.commit()

            audio_path.unlink(missing_ok=True)
            log.info("extractor.done")
            return result

        except ExtractionError as exc:
            interaction.status = "FAILED"
            interaction.error_message = str(exc)
            self.db.commit()
            log.error("extractor.failed", error=str(exc))
            raise

    async def run_pending(self, limit: int = 10) -> dict:
        """Process pending eligible interactions for the department."""
        interactions = (
            self.db.query(Interaction)
            .filter(
                Interaction.department_id == self.department_id,
                Interaction.status == "ELIGIBLE",
            )
            .limit(limit)
            .all()
        )

        processed, failed = 0, 0
        for interaction in interactions:
            try:
                await self.process(interaction)
                processed += 1
            except ExtractionError:
                failed += 1
                continue

        return {"processed": processed, "failed": failed, "total": len(interactions)}

    @staticmethod
    def _read_openai_attr(value: Any, field: str) -> Any:
        """Read SDK response values regardless of object/dict shape."""
        if isinstance(value, dict):
            return value.get(field)
        return getattr(value, field, None)

    def _normalize_whisper_segments(
        self,
        raw_segments: list[Any],
        transcript_text: str,
    ) -> list[SpeakerSegment]:
        """Normalize Whisper segments into the shared speaker segment schema."""
        segments: list[SpeakerSegment] = []
        for item in raw_segments:
            text = self._read_openai_attr(item, "text") or ""
            start = self._read_openai_attr(item, "start") or 0
            end = self._read_openai_attr(item, "end") or start
            segments.append(
                SpeakerSegment(
                    speaker="A",
                    text=text,
                    start_ms=int(float(start) * 1000),
                    end_ms=int(float(end) * 1000),
                )
            )

        if segments:
            return segments

        return [
            SpeakerSegment(
                speaker="A",
                text=transcript_text,
                start_ms=0,
                end_ms=0,
            )
        ]

    @staticmethod
    def _suffix_from_content_type(content_type: str) -> str:
        """Map a response content type to a local audio file suffix."""
        if content_type in {"audio/wav", "audio/x-wav"}:
            return ".wav"
        return ".mp3"

    @staticmethod
    def _safe_url(url: str) -> str:
        """Mask signed URL query params before surfacing them in logs."""
        parsed = urlparse(url)
        safe_path = parsed.path
        marker = "/calls-records/download/"
        if marker in safe_path:
            prefix, suffix = safe_path.split(marker, 1)
            path_parts = suffix.split("/")
            if len(path_parts) >= 2:
                path_parts[0] = "***"
                safe_path = f"{prefix}{marker}{'/'.join(path_parts)}"
        safe_query = "***" if parsed.query else ""
        return parsed._replace(path=safe_path, query=safe_query).geturl()

    @staticmethod
    def _merge_ai_routing_metadata(
        current: Any,
        layer_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach one layer-specific routing snapshot to interaction metadata."""
        merged = dict(current or {})
        layer = str(layer_metadata.get("layer") or "").strip()
        if layer:
            merged[layer] = layer_metadata
        return merged
