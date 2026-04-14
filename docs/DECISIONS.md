# Architectural Decisions

## ADR-001: Python instead of n8n/Make
- **Decision:** Use a pure Python pipeline.
- **Reason:** AI coding tools can generate and maintain Python directly, abstraction overhead stays low, and the team keeps full control over execution flow and debugging.
- **Date:** 2026-03-17

## ADR-002: `department_id` on all tables
- **Decision:** `department_id` is mandatory on every database table.
- **Reason:** This guarantees department-level data isolation and preserves a path to multi-tenant architecture without future schema redesign.
- **Date:** 2026-03-17

## ADR-003: Agent = Python module, not AI agent
- **Decision:** An agent is a folder with a deterministic pipeline.
- **Reason:** This keeps execution predictable, debugging simple, and avoids unnecessary LLM calls or implicit behavior.
- **Date:** 2026-03-17

## ADR-004: LLM JSON contract is immutable
- **Decision:** The JSON structure of LLM outputs, including fields and types, must not change when prompt versions evolve.
- **Reason:** This preserves BI compatibility and allows stable Pydantic validation without breaking downstream consumers.
- **Date:** 2026-03-17

## ADR-005: `instruction_version` on each analysis
- **Decision:** Store `instruction_version` in the `analyses` table.
- **Reason:** This enables cohort tracking, prompt A/B tests, and reliable BI filtering by prompt instruction lineage.
- **Date:** 2026-03-17

## ADR-008: `script.py.mako` is required in `migrations/`
- **Decision:** Always create `script.py.mako` in the `migrations` folder.
- **Reason:** Alembic uses it as the template for generating migration files.
- **Date:** 2026-03-17

## ADR-009: Analyzer business logic waits for approved checklist and contract
- **Decision:** Build the calls analyzer as a technical scaffold until the approved checklist, call cards, and final analysis contract are provided.
- **Reason:** This preserves architecture and prompt plumbing without inventing business rules that could later break ADR-004 or force schema rework.
- **Date:** 2026-03-17

## ADR-010: Temporary manual pilot mode before Bitrix read-only and scheduler
- **Decision:** For MVP-1 / Phase 1, introduce a temporary manual execution mode for one live end-to-end call run: OnlinePBX -> filtering -> extractor -> STT -> analyzer -> persistence -> delivery, triggered manually via CLI and/or manual API endpoint.
- **Reason:** The immediate goal of the current phase is to validate the live pipeline on a real call as quickly as possible. Bitrix24 read-only selection, scheduler, retries, and recovery are postponed to the next step so they do not block the first live demonstration.
- **Constraints:** This mode must use explicit pilot target configuration / whitelist, must send notifications only to test recipients, must not require Bitrix24, and must not introduce scheduler-driven automation.
- **Date:** 2026-03-18

## ADR-011: OnlinePBX endpoint normalization and explicit override for live validation
- **Decision:** Normalize `ONLINEPBX_DOMAIN` so it can accept either a short subdomain, a full host, or a URL-like value, and keep explicit overrides `ONLINEPBX_API_BASE_URL` and `ONLINEPBX_CDR_URL` for live validation when the provider endpoint differs from the default pattern. For the current live account, the confirmed working override is `ONLINEPBX_CDR_URL=https://api.onlinepbx.ru/{domain}/mongo_history/search.json`, with `auth.json` derived from the same HTTP API base and `x-pbx-authentication` requested dynamically from the project API key.
- **Reason:** Real project env values may already contain a full host such as `d24kz.onpbx.ru`. The previous logic blindly appended `.onlinepbx.ru`, which produced malformed URLs and blocked CDR intake before the first live run. After normalization, the legacy endpoint still returned `307` redirect to `https://onlinepbx.ru/`, so manual live validation needed an explicit HTTP API override rather than more guessing.
- **Constraints:** Diagnostics must show the assembled URL, redirect target, config snapshot, and response preview without exposing secrets. The override stays in env/config, not in hardcoded secrets or one-off Python constants.
- **Date:** 2026-03-18

## ADR-012: Temporary Whisper STT for Manual Live Validation
- **Decision:** For manual live validation, allow STT provider selection through env and switch the manual live path to Whisper via OpenAI, while keeping provider selection configurable for later return to AssemblyAI or another provider.
- **Reason:** The current goal is to unblock the first live end-to-end run quickly. AssemblyAI must not be a hard dependency for this test step.
- **Constraints:** This is a temporary execution-mode choice for live validation, not a schema or analyzer contract change.
- **Date:** 2026-03-18

## ADR-013: Fresh-container runtime path for live OnlinePBX checks
- **Decision:** Live validation checks for OnlinePBX must run through a fresh `docker compose run --rm api ...` container with explicit env overrides when needed, instead of relying on `docker compose exec` into long-running containers that may still hold placeholder env values.
- **Reason:** During bounded discovery, `exec` against the already running API container showed stale placeholder config (`ONLINEPBX_DOMAIN=yourcompany`) even though the project `.env` had the real account values. A fresh container reproduces the current `.env` and makes endpoint discovery and live probes deterministic.
- **Constraints:** This is an operational path for Manual Live Validation only. It does not introduce scheduler automation or any permanent runtime redesign.
- **Date:** 2026-03-18

## ADR-014: Temporary manual bootstrap for department and manager in Live Validation
- **Decision:** Until Bitrix24 read-only mapping is connected, Manual Live Validation may create or reuse a temporary pilot `department` and `manager` directly in PostgreSQL through a minimal bootstrap path. The bootstrap is intentionally narrow: one department, one manager, one extension mapping, enough to persist a real call and its analysis.
- **Reason:** The live source pipeline is already working, but persistence still requires mandatory `department_id` and manager mapping by extension. Without a small bootstrap path, the first real manual run remains blocked even though Bitrix is explicitly out of scope for this step.
- **Constraints:** This does not replace future Bitrix24 read-only mapping, does not introduce a new master-data subsystem, and stays limited to Manual Live Validation via CLI/manual runner.
- **Date:** 2026-03-18

## ADR-015: Runtime-safe analyzer source fallback for fresh containers
- **Decision:** `CallsAnalyzer` may fall back to its already embedded approved checklist definition, contract template, and prompt assets when fresh runtime containers cannot access host-level `docs/mvp1_sources` paths.
- **Reason:** The approved analyzer materials were available in the repository context but not mounted into the fresh `api` container used for manual live validation. Without a runtime-safe fallback, the first live run failed before persistence despite successful intake, audio fetch, and Whisper STT.
- **Constraints:** The fallback does not change the approved JSON contract, does not move LLM calls outside `CallsAnalyzer`, and exists only to keep Manual Live Validation reproducible in the current runtime layout.
- **Date:** 2026-03-18

## ADR-016: Delivery-only replay for persisted manual live cases
- **Decision:** Manual Live Validation may replay only the test delivery stage for an already persisted `interaction` / `analysis` pair, without repeating OnlinePBX intake, audio fetch, Whisper STT, or LLM analysis.
- **Reason:** After the first real live case had already reached persistence, the remaining blocker moved to test-only delivery credentials. Replaying just the delivery stage is the safest way to verify delivery wiring and retry the same case without creating duplicate `interactions` or `analyses`.
- **Constraints:** Replay remains test-only, uses the persisted `Analysis.scores_detail` payload, updates the existing `interaction` status instead of creating new rows, and does not replace future delivery automation or retry logic.
- **Date:** 2026-03-18

## ADR-017: Telegram is the closing channel for Manual Live Validation
- **Decision:** The formal closing path for `Веха 3.5 Manual Live Validation` is a successful test-only Telegram delivery replay on an already persisted live case, using `TELEGRAM_BOT_TOKEN` plus explicit `TEST_DELIVERY_TELEGRAM_CHAT_ID`.
- **Reason:** The live pipeline was already proven up to persistence, and Telegram became the fastest safe channel to finish validation without rerunning OnlinePBX intake, STT, or analyzer. The persisted case `interaction_id=2ea673d2-8a5c-4ab3-9e96-339392003b00` / `analysis_id=5a8f8414-f59a-4671-8879-bac3bf5e2f4d` was successfully replay-delivered to the test-only chat `74665909` with no duplicate rows.
- **Constraints:** This decision closes only Manual Live Validation. It does not expand delivery scope to production recipients, does not replace later Delivery Ready work, and does not introduce scheduler/retry logic.
- **Date:** 2026-03-18

## ADR-018: Bitrix24 read-only becomes the primary manager mapping path after Manual Live Validation
- **Decision:** After closing `Веха 3.5`, manager selection/mapping should first try a minimal Bitrix24 read-only path and only then fall back to the existing manual pilot bootstrap/mapping. The read-only path uses the existing incoming webhook, mirrors only the minimal manager/department fields into PostgreSQL, and never performs Bitrix24 write-back.
- **Reason:** The live pipeline is already proven end-to-end, so the next bottleneck is no longer delivery but deterministic manager/department mapping beyond a single manual pilot case. A light read-only mirror keeps the pipeline practical without introducing a new master-data platform.
- **Matching order:** `extension` exact match in Bitrix24 active users -> `phone` exact match in Bitrix24 active users -> manual fallback. Local department mapping uses Bitrix `UF_DEPARTMENT` with optional `BITRIX24_TARGET_DEPARTMENT_IDS`; local manager mirror stores `bitrix_id`, `extension`, `email`, and active status in the existing tables.
- **Constraints:** Manual pilot mode and manual bootstrap stay intact as fallback. Ambiguous or missing Bitrix matches must be surfaced in diagnostics/metadata, not hidden. Write-back to Bitrix24 is explicitly out of scope for this step.
- **Date:** 2026-03-18

## ADR-019: Live Bitrix24 mapping confirmed on real fields
- **Decision:** The current live Bitrix24 account confirms that deterministic manager/department mapping can rely on `UF_PHONE_INNER` for the internal extension and `UF_DEPARTMENT` for department linkage; phone-based matching remains secondary via `PERSONAL_MOBILE` / `PERSONAL_PHONE` / `WORK_PHONE`.
- **Reason:** A live probe against the provided webhook showed `user.get` and `department.get` working in read-only mode, and the real manager with extension `311` was resolved as Bitrix user `2158` into a local mirrored manager/department pair without ambiguity.
- **Observed live behavior:** `user.userfield.list` is not available for this webhook (`insufficient_scope`), but that is not blocking because the required fields are already present in `user.get`. The Bitrix `ACTIVE` field comes back as a boolean on this account, so normalization must accept both boolean and legacy string forms.
- **Constraints:** Manual fallback still remains mandatory for missing/ambiguous cases or unavailable webhook data.
- **Date:** 2026-03-18

## ADR-020: Automation readiness is postponed until Manual Output Validation is complete
- **Decision:** After closing `Веха 3.5 Manual Live Validation`, the immediate next step is `Manual Output Validation`, not scheduler/retries/beat/full automation loop. Automation readiness stays postponed until the generated materials are manually reviewed and accepted.
- **Reason:** The pipeline is already proven operationally in manual mode, including Telegram delivery and Bitrix24 read-only mapping. The next highest-risk unknown is output quality and business usefulness of the generated artifacts, not automation mechanics.
- **Scope impact:** This step is documentation and validation-driven. It focuses on transcript quality, analysis contract quality, checklist/scoring quality, agreements/follow-up usefulness, compact manager-facing card quality, Telegram content quality, and cross-artifact consistency.
- **Constraints:** No scheduler, retries, beat, or full automation loop are introduced in this step. Manual pilot mode, manual bootstrap, and delivery replay remain available as fallback/operational controls during validation.
- **Date:** 2026-03-18

## ADR-021: Transcript language stays source-native while business outputs must be Russian
- **Decision:** Transcript artifacts keep the original spoken language of the call, while all business-facing outputs must be Russian unless a fragment is intentionally quoted as source evidence or is a technical/system value.
- **Reason:** During `Manual Output Validation`, the first persisted live case showed a mixed-language manager-facing delivery card: raw transcript content was correctly source-native, but summary/findings/recommendations leaked English into a Russian business wrapper. This degrades readability and business usefulness even when transport and persistence are technically correct.
- **Applies to:** `interaction.text`, transcript segments, raw source fragments, and evidence quotes remain source-native; `summary`, `strengths`, `gaps`, `recommendations`, `follow_up`, compact Telegram delivery, manager-facing card text, and similar business outputs must be Russian.
- **Constraints:** This does not authorize automatic transcript translation and does not change system values such as codes, enums, ids, JSON keys, or technical identifiers.
- **Date:** 2026-03-18

## ADR-022: Layer-specific AI provider routing with deterministic pools
- **Decision:** Introduce one shared routing layer for `STT`, `LLM-1`, and `LLM-2`, with independent provider pools, account aliases, models, and routing policies per layer.
- **Reason:** MVP-1 needs controlled cost distribution, account/vendor isolation, deterministic failover behavior, and the ability to run bounded A/B tests without rewriting the pipeline around each provider change.
- **Supported policies:** `fixed`, `failover`, `weighted_ab`, `manual_force`.
- **Persistence/logging rule:** The selected provider/account/model, policy, fallback usage, force-override state, and provider failures must be visible in runtime logs and persisted audit metadata.
- **Backward compatibility:** If no explicit pool JSON is configured, the router must derive a legacy single-provider pool from existing settings so the current manual flow keeps working.
- **Current execution scope:** `STT` and `LLM-2` are wired to actual routed execution now; `LLM-1` routing is prepared/configured and persisted as metadata, but a separate first-pass `LLM-1` call is intentionally not activated yet in the current `CallsAnalyzer` runtime.
- **Confirmed bounded adapter scope:** `STT` currently has concrete runtime adapters for `assemblyai` and `openai/whisper`; `LLM-2` currently executes through the OpenAI client with routed `model` and `api_base`, so other `LLM` vendors require OpenAI-compatible semantics or a later explicit adapter step.
- **Schema/runtime note:** `endpoint` is already part of the routing config and audit schema, but current executors do not yet consume it directly at request-build time.
- **Constraints:** This routing layer is not pipeline automation readiness, does not introduce scheduler/retries/beat semantics, does not move LLM calls outside `CallsAnalyzer`, and does not change the approved analyzer contract/output shape.
- **Date:** 2026-03-19

## ADR-023: Execution compatibility guardrails must be explicit for routed AI providers
- **Decision:** Treat routing validity and execution readiness as separate concerns. A configured provider/account entry may participate in selection metadata, but it must not be treated as execution-supported unless the target layer has a matching adapter capability.
- **Reason:** After introducing multi-provider routing, the current code can select candidates that are structurally valid in config yet only fail later inside executor-specific code paths. This is acceptable for bounded MVP-1 only if the boundary is explicit and guarded.
- **Execution modes:** Minimum distinction is `openai_compatible` versus `vendor_specific`.
- **Implemented guardrail:** Settings/config validation remains structural, router selection now annotates candidates with execution capability metadata, and executor-preflight enforces the hard compatibility stop before provider client/request build.
- **Implemented bounded capability map:** `STT / assemblyai -> vendor_specific`, `STT / openai -> openai_compatible`, `LLM-2 / openai -> openai_compatible`.
- **Current scope:** This bounded guardrail is implemented only for `STT` and `LLM-2`. `LLM-1` remains configuration/audit-only for now and must not gain a separate runtime pass in this step.
- **Non-goals:** No plugin framework, no remote provider probing at settings-load time, no scheduler/retry expansion, no analyzer contract change, and no broad extractor/analyzer refactor.
- **Date:** 2026-03-19

## ADR-024: Manual Reporting Pilot comes before automation settings
- **Decision:** After closing `Manual Output Validation`, the next agreed intermediate mode is `Manual Reporting Pilot`, not scheduler/retries/beat/full automation loop.
- **Reason:** The project now needs a controlled manual reporting layer for daily and weekly management use, with parameterized runs, artifact reuse, model testing, and email delivery, before any automation settings are discussed.
- **Operating shape:** Launches are manual and parameter-driven, built around `report_preset + period + filters`, with first presets `manager_daily` and `rop_weekly`, and first manual modes `build_missing_and_report` plus `report_from_ready_data_only`.
- **Reuse rule:** Existing artifacts must be reused whenever the effective versions of the inputs that influence a step have not changed. Model change alone must not force a full pipeline rerun, though it may justify rerunning only the model-dependent step.
- **Delivery rule:** Reports in this mode are email-first; each report goes to the resolved primary recipient plus monitoring email `sales@dogovor24.kz`. Recipient resolution comes from Bitrix employee/org-structure data as a configurable rule.
- **Allowed bounded extension:** An optional report-composer LLM step may synthesize daily recommendations, focus summaries, and weekly narrative interpretation blocks from already built artifacts. This does not redesign `CallsAnalyzer` and does not create a new core AI layer.
- **Constraints:** No automation readiness by default, no scheduler/retries/beat/full automation loop, no analyzer contract change, no rewrite of closed Track A / Track B, and no monthly report in the first version.
- **Date:** 2026-03-26

## ADR-025: Reporting pilot must keep recipient fallback and delivery failures structured
- **Decision:** In the bounded Manual Reporting Pilot slice, `rop_weekly` resolves its primary recipient first from `departments.settings.reporting.rop_weekly_email`, and if that value is absent it falls back to live Bitrix org-structure data `department.UF_HEAD -> active user EMAIL`.
- **Decision:** Delivery-stage email failures in the manual reporting path must be folded back into structured report results as `blocked`, with `payload` and `preview` preserved, instead of escaping as CLI/API-level tracebacks.
- **Reason:** Real validation on 2026-03-27 showed that the local department mirror already had enough Bitrix data to derive the weekly sales-head recipient without a broader org-chart redesign, while SMTP failures were still terminating the manual run path and hiding the reporting result behind a stack trace.
- **Scope:** This is a bounded reporting-pilot rule only. It does not introduce scheduler/retries/automation semantics, does not redesign Bitrix integration beyond department-head fallback, and does not change the approved analyzer contract.
- **Date:** 2026-03-27

## ADR-026: First operator UI stays inside the existing FastAPI app
- **Decision:** The first operator-facing interface for Manual Reporting Pilot is an internal web page served by the existing FastAPI application, using the current reporting API path instead of a separate frontend project.
- **Decision:** This UI may add only lightweight supporting endpoints for form context and recipient preview; actual execution continues to use the existing `/pipeline/calls/report-run` contract.
- **Reason:** Delivered happy path is already confirmed for the bounded reporting slice, so the next safe step is to remove CLI-only friction for operators without creating a second application surface or drifting into automation scope.
- **Scope:** No scheduler/retries/beat, no reporting history/dashboard subsystem, no contract change for report execution, and no monthly report.
- **Date:** 2026-03-27

## ADR-027: Operator UI may refresh the local manager mirror and use Telegram-first test delivery
- **Decision:** The internal Manual Reporting operator UI may expose an explicit per-department manager sync action that refreshes the local mirrored `managers` directory from Bitrix24 before report execution.
- **Decision:** This UI keeps using the existing bounded `/pipeline/calls/report-run` contract, including existing `manager_ids[]` / `manager_extensions[]` filters, but the controls may be multi-select to support zero, one, or many managers.
- **Decision:** During the current test period, if `TEST_DELIVERY_TELEGRAM_CHAT_ID` is configured, report delivery may be redirected to that operator Telegram chat while still resolving and surfacing the underlying email recipients for preview/reference; when the Telegram test chat is absent, the regular email delivery path remains in effect.
- **Reason:** Real operator usage showed that call-driven mirror updates leave the manager picker stale for full-department runs, while the safest test-period delivery target is the operator Telegram chat rather than sending every experimental run to business recipients.
- **Scope:** This does not add scheduler/history automation, does not remove or redesign the email delivery path, and does not change the approved analyzer/reporting execution contract.
- **Date:** 2026-03-27

## ADR-028: Operator observability stays inside the existing report-run response
- **Decision:** The first bounded observability step for Manual Reporting Pilot must stay inside the existing operator UI and the existing `/pipeline/calls/report-run` response, rather than adding a new run-history subsystem or a separate observability backend.
- **Decision:** The response may expose a structured `observability` block with:
  - UI-facing `run_state`
  - stage snapshots for `source-discovery`, `persistence-check`, `ingest-missing`, `audio-fetch`, `STT`, `analysis`, `report-build / render`, and `delivery`
  - compact run summary
  - AI cost entries with exact values only when metadata is actually available, otherwise explicit safe fallback such as `not_available`
- **Reason:** The operator currently needs immediate confidence that a run started and where it is blocked, but the project is still inside a bounded manual pilot and must avoid drifting into scheduler/history/dashboard scope.
- **Scope:** No streaming backend, no long-lived run store, no retries/beat/scheduler, no analyzer contract expansion just for observability, and no invented cost estimates.
- **Date:** 2026-03-27

## ADR-029: Selection transparency for operator UI stays inside report-run diagnostics
- **Decision:** The existing internal operator page may expose a compact diagnostics block on the same screen, backed by a structured additive `diagnostics` field in `/pipeline/calls/report-run`.
- **Decision:** This diagnostics payload should explain empty or limited runs through stable bounded reason codes and effective filter metadata, rather than client-side guessing.
- **Decision:** The first bounded set of diagnostics codes is:
  - `no_persisted_interactions_for_filters`
  - `filters_intersection_empty`
  - `no_ready_artifacts_for_ready_only_mode`
  - `manager_not_in_local_directory`
  - `date_range_has_no_persisted_calls`
  - `source_discovery_failed`
  - `transcript_build_failed`
  - `analysis_build_failed`
- **Reason:** The operator needs immediate clarity on whether the issue is filters, ready-only constraints, missing persisted calls, or stale local mirror state, but the project still must avoid a separate diagnostics/history subsystem.
- **Scope:** Additive payload only, no contract break, no realtime streaming, no new page/router, and no expansion of analyzer architecture beyond bounded operator diagnostics.
- **Date:** 2026-03-27

## ADR-030: Manual operator reporting run becomes source-aware full manual run
- **Decision:** The existing manual operator/reporting path is no longer persisted-reporting-only. A bounded manual run must first discover target calls in the source system for the selected `report_preset + period + filters`, compare them against persisted interactions, ingest only missing source calls, and then continue with reuse-first transcript / analysis / report / delivery execution.
- **Decision:** `report_from_ready_data_only` still performs source discovery and idempotent ingest of missing interactions, but it must not build new audio / STT / analysis artifacts. `build_missing_and_report` performs the same source-aware prelude and then builds only missing transcript / analysis artifacts for the selected persisted interactions.
- **Decision:** Runtime source/build failures in this path must fold back into structured report results (`blocked` / `partial` plus stage errors), not escape from `/pipeline/calls/report-run` as raw HTTP tracebacks.
- **Reason:** Real operator usage showed that a persisted-only reporting slice is insufficient for date-based manual runs: the operator needs a manual launch that can find calls still present in OnlinePBX but absent from the local DB, pull them into the pipeline without duplicates, and then complete a bounded analysis/report flow from the same UI.
- **Scope:** This remains a manual operator-triggered path only. No scheduler, retries, beat, history/dashboard subsystem, analyzer contract change, or broad automation loop is introduced by this decision.
- **Date:** 2026-03-27

## ADR-031: `manager_daily` and `rop_weekly` use different execution models
- **Decision:** `manager_daily` is the only preset that may use the source-aware manual full-run path: source discovery, persistence-check, ingest missing calls, audio fetch, STT, and analysis are allowed there under the existing bounded modes.
- **Decision:** `rop_weekly` is persisted-only aggregation. Weekly runs must not perform source discovery, must not ingest missing calls, and must not trigger new audio / STT / analysis execution even when the operator chooses `build_missing_and_report`.
- **Decision:** Operator observability/diagnostics must expose this distinction explicitly via execution-model metadata and `skipped` source/build stages for `rop_weekly`.
- **Reason:** The daily preset needs a true manual launch for one day/manager, while the weekly preset is intended to summarize already prepared material for management and should not unexpectedly open a new source/build loop.
- **Scope:** This is a standing rule for the current Manual Reporting Pilot / Reporting Loop Ready bounded scope. No `/pipeline/calls/report-run` contract change, no scheduler/history/dashboard subsystem, and no automation expansion follow from it.
- **Date:** 2026-03-27

## ADR-032: Operator report-run failure path must stay JSON-first and UI-safe
- **Decision:** `/pipeline/calls/report-run` should keep its success payload unchanged, but on failure it should return a structured JSON error envelope whenever the server can still control the response, including unexpected exceptions inside the manual reporting flow.
- **Decision:** The internal operator UI must not assume that every failed HTTP response is JSON. It should safely inspect status/content-type/body first and show a readable request-failure block when the server returns non-JSON content.
- **Decision:** Request/transport failure must be presented separately from business-stage failure that is already represented inside the normal structured reporting result (`blocked`, `partial`, stage errors, diagnostics).
- **Reason:** After the preset-specific refactor, the highest-friction operator failure mode became not the server defect itself but the frontend parse error on `Internal Server Error` text/HTML. The operator needs the real failure reason directly in the page without opening browser devtools.
- **Scope:** No success-contract change, no new frontend app, no history/dashboard subsystem, and no automation-scope expansion.
- **Date:** 2026-03-27

## ADR-033: Manual operator run always sends Telegram test delivery; toggle controls only business email
- **Decision:** Every manual operator run must always attempt Telegram test delivery to `TEST_DELIVERY_TELEGRAM_CHAT_ID` using `TELEGRAM_BOT_TOKEN`.
- **Decision:** The existing UI delivery toggle is reinterpreted as `business email delivery only`; it must not disable Telegram test delivery and should default to `off`.
- **Decision:** Reporting observability/summary must expose Telegram test delivery and business email delivery as separate channel states.
- **Reason:** The operator needs a guaranteed per-run inspection channel for process validation, content validation, and cost awareness, while business recipients should not receive experimental/manual runs unless email is explicitly enabled.
- **Scope:** This is a bounded operator-run rule only. It does not introduce a new notification subsystem or a broader multi-channel redesign beyond split Telegram-test vs optional business-email semantics.
- **Date:** 2026-03-27

## ADR-034: Final manual reports use repo-local versioned templates and PDF as the primary operator artifact
- **Decision:** `manager_daily` and `rop_weekly` final report layouts must be defined by repo-local versioned template assets, not by ad-hoc inline rendering logic alone.
- **Decision:** The first standard active template versions are `manager_daily_template_v1` and `rop_weekly_template_v1`, with semantic and visual/layout assets stored in `core/app/agents/calls/report_template_assets/...`.
- **Decision:** For these first standard versions, visual/layout precedence comes from:
  - `manager_daily` must follow the approved HTML reference asset `docs/report_templates/reference/manager_daily_reference_html`; `docs/report_templates/reference/manager_daily_reference.md` remains the repo-readable semantic/visual summary of that reference
  - `docs/report_templates/reference/rop_weekly_reference.md`
  while semantic/content rules still come from the existing reporting docs and normalized runtime contracts.
- **Decision:** `manager_daily_template_v1` is now the first approved runtime adaptation of that HTML reference; final reader-facing PDF output must preserve its visual composition and must not expose service/debug text like raw `not available`, `Note:`, template ids, or generation metadata.
- **Decision:** Within that same `manager_daily_template_v1`, reader-facing fallback states must preserve the approved card/banner/table composition and use editorial manager-facing wording, not technical empty-state formulas that make the PDF look like a raw text export.
- **Decision:** The primary operator artifact of a manual report run is a rendered PDF built from the active template version. HTML/text outputs remain supporting previews.
- **Decision:** Telegram test delivery for operator runs must send that final PDF document artifact; optional business email delivery should reuse the same PDF as attachment.
- **Reason:** Manual reporting now needs a stable, reviewable deliverable that can be read, forwarded, and compared across iterations without rebuilding layout intent in code for every run.
- **Scope:** This is a bounded template/rendering rule for the current manual reporting pilot. It does not introduce a broader document platform or dashboard subsystem.
- **Date:** 2026-03-30

## ADR-035: `manager_daily` readiness-based outcome logic gates render and delivery
- **Decision:** `manager_daily` is no longer required to emit a full daily report on every manual run. After source discovery / ingest / reuse / optional build and before final render/delivery, the reporting path must choose exactly one bounded outcome:
  - `full_report`
  - `signal_report`
  - `skip_accumulate`
- **Decision:** The first bounded `full_report` thresholds are:
  - `relevant_calls >= 6`
  - `ready_analyses >= 5`
  - `analysis_coverage >= 75%`
  and content readiness without empty fallback for the key blocks:
  - `ИТОГ ДНЯ`
  - `РАЗБОР`
  - `КЛЮЧЕВАЯ ПРОБЛЕМА ДНЯ`
  - `РЕКОМЕНДАЦИИ`
  plus at least:
  - `1` strong zone
  - `1` growth zone
  - `1` main problem
  - `1` normal recommendation

- **Decision:** `signal_report` is allowed only when `full_report` is not ready, but:
  - `ready_analyses >= 2`
  - there is an explicit positive, critical, or coaching signal
  - there is at least one clear manager action
- **Decision:** If neither `full_report` nor `signal_report` is ready, the bounded outcome is `skip_accumulate`.
- **Decision:** The rolling window for this decision is limited to `1 -> 2 -> 3` working days and must not expand further in the current slice.
- **Decision:** Thresholds and readiness reason codes must live in bounded reporting config/constants and structured reporting output, not as scattered magic numbers.
- **Decision:** `rop_weekly` remains unchanged and does not use this readiness gate.
- **Reason:** Manual operator reporting needs to avoid producing weak daily PDFs filled with fallback blocks when the source/analysis base is too thin, while still allowing a bounded signal-only delivery when there is already one business-useful coaching or critical case.
- **Scope:** This is bounded reporting logic inside the current Manual Reporting Pilot / Reporting Loop Ready delta. It is not scheduler/retry/beat automation, does not expand the analyzer contract, and does not change the standing persisted-only behavior of `rop_weekly`.
- **Date:** 2026-04-07

## ADR-036: Reporting reuse/version checks are stricter; payload richness grows inside the existing normalized contract
- **Decision:** Reuse in the reporting path is no longer based on `analysis.scores_detail is a non-empty dict` alone.
- **Decision:** For the current bounded slice, an analysis is considered enough for reporting reuse only when it is not failed and contains the reporting-required persisted contract pieces:
  - non-empty `instruction_version`
  - `classification`
  - `score.checklist_score.score_percent`
  - `score_by_stage`
  - `strengths`
  - `gaps`
  - `recommendations`
  - `follow_up`
- **Decision:** If a persisted analysis is present but not reusable for reporting, it must be treated as missing for reporting purposes:
  - in `build_missing_and_report`, rebuild only the missing/stale `analysis` step for that interaction when transcript is already reusable;
  - in `report_from_ready_data_only`, do not rebuild it and surface the interaction as not ready for reporting reuse.
- **Decision:** Reporting-specific steps are not reused across manual runs in this slice. Payload assembly, readiness decision, and final render are always rebuilt against the current:
  - `report_logic_version`
  - `reuse_policy_version`
  - active `template_version`
- **Decision:** Payload richness may be improved only inside the existing normalized contracts for `manager_daily` and `rop_weekly`. The slice may use already approved persisted fields such as `score_by_stage`, `follow_up`, `product_signals`, and `evidence_fragments` to enrich existing sections, but must not change the approved analyzer contract or the preset execution split.
- **Decision:** `manager_daily` remains source-aware manual; `rop_weekly` remains persisted-only aggregation.
- **Reason:** The previous reuse rule was too weak for richer reporting sections: a partially shaped persisted analysis could look “ready” even when key reporting blocks depended on fields that were missing. At the same time, richer operator artifacts should come from better deterministic assembly over already approved persisted data, not from broad analyzer/reporting redesign.
- **Scope:** This is bounded reporting logic only. It does not introduce scheduler/retries/beat/automation loop behavior and does not add a new persisted reporting artifact cache.
- **Date:** 2026-04-07

## ADR-037: `manager_daily/build_missing_and_report` activates the real `LLM-1 -> LLM-2` analyzer chain
- **Decision:** The bounded analyzer/runtime path for fresh or missing `manager_daily/build_missing_and_report` cases now includes a real separate `LLM-1` runtime pass before the existing final analysis pass.
- **Decision:** The required execution order for fresh/missing `manager_daily/build_missing_and_report` cases is:
  - source discovery
  - ingest missing interactions
  - audio fetch
  - `STT`
  - `LLM-1`
  - `LLM-2`
  - persistence
  - report build / delivery
- **Decision:** `manager_daily/report_from_ready_data_only` may still perform source discovery and ingest missing interactions, but it must not start new audio / `STT` / `LLM-1` / `LLM-2` execution.
- **Decision:** `rop_weekly` remains persisted-only aggregation and must not open the source/build chain.
- **Decision:** The approved analyzer contract remains unchanged: `LLM-1` returns bounded intermediate context for the second pass, while the final persisted analysis contract still comes from `LLM-2`.
- **Decision:** Per-layer AI audit metadata must now be explicit enough for provider/billing reconciliation. At minimum, `interaction.metadata.ai_routing` and reporting observability must expose:
  - selected provider / account / model
  - attempted / executed status
  - skip reason when not activated by mode
  - bounded usage metadata when the provider returns it
- **Reason:** The operator UI is now used as the real manual run interface for selected periods, so `manager_daily/build_missing_and_report` must be able to complete the full planned AI chain for fresh/missing daily cases instead of stopping at a partially activated analyzer path.
- **Scope:** This is a bounded analyzer/reporting activation step only. It does not change the approved analyzer contract, does not alter the standing `rop_weekly` execution split, and does not introduce scheduler/retries/beat/automation loop behavior.
- **Date:** 2026-04-07

## ADR-038: Semantically empty `LLM-2` outputs are rejected before successful persistence and reporting reuse
- **Decision:** Shape-valid but semantically empty `LLM-2` outputs must not be treated as successful analyses. A bounded semantic-validation step now runs after analyzer shape-validation and before successful persistence/reuse.
- **Decision:** For the current bounded slice, the canonical semantic-invalid reason code is `semantically_empty_analysis`. It applies when all of the following are empty at the same time:
  - `score_by_stage`
  - `strengths`
  - `gaps`
  - `recommendations`
- **Decision:** When this happens, the attempt may still be persisted for forensic traceability, but only as a failed analysis row:
  - `is_failed = true`
  - `fail_reason = semantically_empty_analysis`
  - `raw_llm_response` stores the raw `LLM-2` response text
  - normalized approved-contract snapshot is kept separate from that raw payload and must not be treated as a successful reusable analysis
- **Decision:** Reporting reuse must reject both:
  - failed analyses carrying `semantically_empty_analysis`
  - older persisted rows that still look shape-valid but are semantically empty by the same bounded rule
- **Decision:** In `manager_daily/build_missing_and_report`, when transcript is already ready but analysis is semantic-invalid/non-reusable, only the analysis step is rebuilt. In `report_from_ready_data_only`, no rebuild is allowed and the interaction stays outside the ready subset with structured reuse-rejection.
- **Reason:** Real operator runs showed that permissive template-merge normalization could let `LLM-2` outputs degrade into empty scored contracts (`0.0`, empty stages/findings/recommendations), which then looked like persisted analyses but were not materially usable for reporting. The fix belongs in the analyzer/reuse boundary, not as a reporting-only workaround.
- **Scope:** No approved analyzer contract change, no broad prompt redesign, no automation expansion, and no change to `rop_weekly` execution model.
- **Date:** 2026-04-07

## ADR-039: Default task close-out includes Git commit/push/sync when safely available
- **Decision:** For normal bounded implementation/documentation tasks, the default close-out expectation is no longer "files changed only". When the machine has a working Git repository and remote/auth path, the coder should finish the task with:
  - `commit`
  - `push`
  - and sync with remote when needed before push
- **Decision:** This is a default workflow rule for future coders in this repository, not a one-off local preference.
- **Decision:** The coder must not perform risky Git actions such as `force-push`, history rewrite, or ambiguous conflict resolution without explicit approval.
- **Decision:** If remote sync/push is blocked by auth, branch protection, divergence, or another external Git blocker, the coder must report that blocker explicitly instead of pretending Git close-out is complete.
- **Reason:** The project now has a baseline Git history and is onboarding additional developers. Consistent Git close-out reduces drift between "implemented locally" and "shared in remote history", while still preserving visibility of external blockers and open verification gaps.
- **Scope:** This is a process/default workflow rule only. It does not authorize masking runtime issues, skipping verification, or changing product/runtime scope as part of a Git close-out.
- **Date:** 2026-04-09

## ADR-040: Non-deliverable `manager_daily` emits an operator-facing preview shell
- **Decision:** When `manager_daily` ends in a bounded non-deliverable state:
  - `skip_accumulate`
  - `no_data`
  - `missing_artifacts`
  the reporting layer should render an operator-facing preview shell instead of returning an empty no-artifact result.
- **Decision:** The preview shell must preserve the daily report layout and explicitly show:
  - manager
  - date / effective period
  - preset / mode
  - final status / readiness outcome
  - readiness reason codes
  - found calls / ready analyses / coverage
  - placeholder versions of the main daily sections
- **Decision:** The shell must be explicitly marked as:
  - `preview`
  - `insufficient data`
  - `not a deliverable manager report`
- **Decision:** This shell is operator-only. It must not be sent as an ordinary manager daily report and must keep business email delivery disabled; only the existing test-delivery path may be used for preview verification.
- **Reason:** Ready-only `manager_daily` on the current persisted dataset honestly resolves to `skip_accumulate`, but operators still need to see the report form, template layout, and diagnostics without masking weak data as a `signal_report` / `full_report`.
- **Scope:** This is a bounded reporting-layer policy for Manual Reporting Pilot. It does not activate new AI build steps, does not change analyzer/runtime contracts outside reporting, and does not alter `rop_weekly`.
- **Date:** 2026-04-09

## ADR-041: Repo-first project governance and agent-independent task closure

- **Decision:** Canonical project context lives in the GitHub repository, primarily in `docs/` and related repo assets. The current chat is a management delta over repo. Files in Sources and older chat context are reference-only unless explicitly promoted into repo docs.
- **Decision:** Critical execution rules must not depend only on agent-specific memory or hidden prompt state. They must live in:
  - the task prompt itself;
  - repo documentation / infrastructure;
  - human review before acceptance.
- **Decision:** If an incoming task is not already structured in the project task format, the coder must first normalize it into that format before implementation.
- **Decision:** A task is not complete without an explicit close-out that states:
  - whether `PROGRESS.md` was updated;
  - whether `DECISIONS.md` was updated;
  - what other docs changed;
  - whether commit/push were completed.
- **Reason:** The project is now operated across multiple agents and sessions. Hidden agent memory or vendor-specific bootstrap alone is not reliable enough to preserve process discipline, documentation updates, and task closure.
- **Scope:** This is a project operating-model decision. It does not change product runtime behavior, analyzer contracts, or reporting execution logic.
- **Date:** 2026-04-09

## ADR-042: Thin agent entry files plus versioned Git hook barrier

- **Decision:** The repository keeps thin agent-specific entry files at repo root:
  - `CLAUDE.md`
  - `AGENTS.md`
  - `GEMINI.md`
  These files are not the canonical rules layer. They act as entry adapters that direct the agent to `docs/CODER_WORKING_RULES.md`, require repo-first behavior, require task normalization first, and require mandatory close-out.
- **Decision:** `docs/TASK_PROMPT_TEMPLATE.md` must include an обязательный close-out checklist inside the task prompt itself.
- **Decision:** Git hook enforcement must be versioned in the repository, not stored only in local `.git/hooks`.
- **Decision:** The first bounded pre-push barrier blocks push when non-doc changes are present but `docs/PROGRESS.md` was not updated, unless the operator explicitly bypasses the check with `git push --no-verify`.
- **Reason:** Different agents auto-load different root-level files, while some agents may ignore them completely. Thin entry adapters improve adoption for supported agents, but the cross-agent enforcement must still live in the task prompt and repo infrastructure.
- **Constraints:** Local `.git/hooks` may only delegate to repo-versioned scripts. This decision does not replace human review and does not authorize masking blockers or incomplete verification.
- **Date:** 2026-04-09

## ADR-043: Business-ready report pack comes before Pilot Live; full report mechanism upgrade comes after pilot
- **Decision:** Before `Pilot Live` we do a bounded business-facing report improvement block.
- **Decision:** This block is limited to presentation/readability/renderer/report-structure improvements.
- **Decision:** Full report mechanism upgrade is postponed until after pilot.
- **Reason:** Business perception is highly report-visual and report-format dependent, but mixing pilot launch with full mechanism redesign would blend two different risks into one step.
- **Scope:** Allowed before pilot:
  - report structure/layout
  - wording/readability
  - visual hierarchy
  - PDF/renderer polish
  - complete call-list presentation
- **Scope:** Not allowed before pilot:
  - full extraction/aggregation/coaching redesign
  - broad analyzer redesign
  - full rich-report mechanism rollout
- **Date:** 2026-04-14
