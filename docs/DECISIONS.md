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
- **Decision:** The first standard active template versions were `manager_daily_template_v1` and `rop_weekly_template_v1`, with semantic and visual/layout assets stored in `core/app/agents/calls/report_template_assets/...`.
- **Decision:** For these first standard versions, visual/layout precedence comes from:
  - `manager_daily` must follow the approved HTML reference asset `docs/report_templates/reference/manager_daily_reference_html`; `docs/report_templates/reference/manager_daily_reference.md` remains the repo-readable semantic/visual summary of that reference
  - `docs/report_templates/reference/rop_weekly_reference.md`
  while semantic/content rules still come from the existing reporting docs and normalized runtime contracts.
- **Decision:** `manager_daily_template_v1` is now the first approved runtime adaptation of that HTML reference; final reader-facing PDF output must preserve its visual composition and must not expose service/debug text like raw `not available`, `Note:`, template ids, or generation metadata.
- **Decision:** Within that same `manager_daily_template_v1`, reader-facing fallback states must preserve the approved card/banner/table composition and use editorial manager-facing wording, not technical empty-state formulas that make the PDF look like a raw text export.
- **Decision:** For Business-ready Report Pack runtime testing, the improved canonical `manager_daily` runtime output is now versioned as `manager_daily_template_v2`, while `manager_daily_template_v1` remains the separated legacy runtime template id.
- **Decision:** The ordinary `/pipeline/calls/report-run` -> `manager_daily` -> Telegram delivery path must use `manager_daily_template_v2` as the active runtime default, including `report_from_ready_data_only` preview-shell outcomes.
- **Decision:** The standing runtime standard for `manager_daily_template_v2` is now the approved 13-block `v5` structure already fixed in repo reference implementation `scripts/generate_docx_report.js`; the Python runtime renderer must follow that block order and must not silently fall back to the earlier v2 composition.
- **Decision:** Safe fallback is allowed only inside those same v5 blocks. Missing data may change wording/content density, but not the approved section order or the presence of the 13 blocks themselves.
- **Decision:** Structured report results, artifact metadata, observability, and diagnostics must expose report provenance explicitly via `template_version`, `template_id`, `render_variant`, and `generator_path`, so `v1` and `v2` outputs cannot be confused operationally.
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

## ADR-044: Pilot Ready closes all non-billing tasks first; final closure waits for one bounded rerun after top-up
- **Decision:** The current `Pilot Ready` task closes all technical and documentation work that does not depend on billable access for `OPENAI_API_KEY_STT_MAIN` and `OPENAI_API_KEY_LLM1_MAIN`.
- **Decision:** The remaining blocker is explicitly external: billable quota / balance access for those two keys.
- **Decision:** Until the user confirms the balance top-up, full closure verification is not complete and must not be misrepresented as closed.
- **Decision:** After user confirmation about top-up, only one bounded rerun is allowed for final closure verification: `manager_daily/build_missing_and_report` on the already fixed live case `department=472cda28-ce71-494c-9068-25d3ffbf7399`, `manager=09cae83f-7ac1-4ee0-b1d5-3a76c8053c3f`, `extension=322`, `period=2026-04-06`, with always-on Telegram test delivery and business email off.
- **Superseded note:** Step 8P / ADR-049 replaces the always-on Telegram wording with explicit `telegram_test_only` delivery.
- **Reason:** Repo docs must separate the last external billing dependency from code/runtime scope, so the team can close `Pilot Ready` immediately after one successful rerun instead of reopening architecture or broad reporting work.
- **Scope:** No billing workaround in code, no `Business-ready Report Pack`, no full report mechanism upgrade, no scheduler/retries/beat/automation, and no broad analyzer redesign.
- **Date:** 2026-04-15

## ADR-045: Before pilot, scheduled reporting may run automatically but business delivery stays review-gated
- **Decision:** Before pilot the project allows a bounded operating mode `scheduled_reviewable_reporting`.
- **Decision:** In this mode the system may create report runs automatically by schedule and build the report artifact automatically, but it must stop in `review_required` before business delivery.
- **Decision:** Business delivery remains manual: the operator must review the draft in the existing operator UI, may edit only allowed business-facing report blocks, and must explicitly approve delivery.
- **Decision:** Raw analysis/scoring stays immutable. Manual editing is not allowed for transcript, raw extracted facts, raw checklist answers, stage scores, criteria results, raw analyzer JSON, source call-list data, or computed metrics.
- **Reason:** The project needs to remove the daily manual trigger before pilot, while preserving operator control and avoiding a full automation loop or any mixing of report-shaping with raw-analysis edits.
- **Scope:** Allowed in this block:
  - bounded schedule creation in existing backend/operator UI
  - fixed schedule fields and bounded report-period rules
  - lifecycle `planned -> queued -> running -> review_required -> approved_for_delivery -> delivered|failed|paused`
  - audit of original generated block, edited block, editor, and `edited_at`
- **Scope:** Not allowed in this block:
  - retries / beat platform redesign / failure recovery engine
  - generic workflow builder or arbitrary cron editor
  - auto-approval or auto-send to business without review
  - broad analyzer redesign or full rich-report mechanism upgrade
- **Date:** 2026-04-15

## ADR-046: Scheduled reviewable reporting uses server-enforced lifecycle, review gate, and edit whitelist
- **Decision:** `scheduled_reviewable_reporting` must enforce its invariants on the backend, not only in the operator UI.
- **Decision:** Due-scan must be idempotent for the same due occurrence: repeated scan must not create duplicate batches, disabled schedules must not emit new batches, and future schedules must not start early.
- **Decision:** Batch lifecycle transitions are explicit and limited to:
  - `planned -> queued|failed|paused`
  - `queued -> running|failed|paused`
  - `running -> review_required|failed|paused`
  - `review_required -> approved_for_delivery|failed|paused`
  - `approved_for_delivery -> delivered|failed`
- **Decision:** Scheduled runs must stop at `review_required`; business delivery before explicit approve is impossible server-side.
- **Decision:** Draft editing is whitelist-only on the backend. Every accepted edit stores `original_generated_block`, `edited_block`, `editor`, and `edited_at`; forbidden edit attempts must return a structured error.
- **Reason:** Pilot Ready now includes a bounded scheduled reviewable flow, so operator control and raw-analysis immutability must survive repeated scans, direct API calls, and incorrect status sequencing without relying on UI discipline.
- **Scope:** This hardening does not add retries, recovery engine, generic scheduler platform, analyzer-contract change, Business-ready Report Pack, or full report mechanism upgrade.
- **Date:** 2026-04-15

## ADR-048: `manager_daily` selection model — три слоя данных и разграничение оперативного и коучингового слоёв

- **Decision:** Canonical selection model для `manager_daily` фиксирует три явных слоя данных:
  - `raw_calls` — все CDR-записи дня из телефонии, полный источник;
  - `meaningful_calls` — содержательные разговоры дня (после фильтрации beep / IVR / пустого трафика), используются для СПИСОК ЗВОНКОВ ДНЯ и итоговой outcome-таблицы;
  - `coaching_core` — звонки с готовым анализом и coaching-eligibility, используются только в coaching-блоках (СИТУАЦИЯ ДНЯ, БАЛЛЫ ПО ЭТАПАМ, РАЗБОР ЗВОНКА и др.) и для readiness decision.
- **Decision:** Ежедневный отчёт не должен показывать менеджеру только `coaching_core` как будто это весь рабочий день. СПИСОК ЗВОНКОВ ДНЯ строится из `meaningful_calls`, а не из `coaching_core`.
- **Decision:** Операционный слой дня (`raw_calls`, `meaningful_calls`, СПИСОК ЗВОНКОВ ДНЯ) всегда только за выбранный день. Rolling window `1 → 2 → 3` рабочих дней применяется только к коучинговому слою (`coaching_core`) для набора аналитической базы readiness decision.
- **Decision:** Если rolling window применён, это явно отражается в service note отчёта и в structured result (`window_days_used`, `window_start`, `window_end`).
- **Decision:** Минимальный набор счётчиков, которые должны стать частью payload/report contract: `raw_calls_total`, `meaningful_calls_total`, `service_calls_total`, `coaching_candidate_calls_total`, `analyzed_calls_total`, `included_in_report_total`. Причины исключения: `too_short_or_no_speech`, `ivr_or_autoanswer`, `support_internal`, `not_enough_analysis`, `not_selected_for_core_review`.
- **Decision:** Canonical source of truth по этому rule set — `docs/MANAGER_DAILY_SELECTION_MODEL.md`.
- **Reason:** Действующий daily report слишком рано сжимает день до узкого аналитического ядра. Менеджер видит в отчёте только малую часть дня, хотя в фактической выгрузке звонков содержательный слой шире. Это нарушает доверие менеджера к отчёту и скрывает реальную картину рабочего дня.
- **Scope:** Это doc-only фиксация canonical selection model и report contract. Изменения кода, analyzer contract, readiness thresholds и scheduler в этот шаг не входят.
- **Date:** 2026-04-30

## ADR-047: `manager_daily` delivery is docx-first; PDF is a converted artifact, not a separate format source
- **Decision:** For ordinary `manager_daily` runtime delivery, the canonical report format source of truth is the approved docx generator `scripts/generate_docx_report.js` and the corresponding approved v5 docx structure it emits.
- **Decision:** `manager_daily_template_v2` delivery must build canonical `.docx` first and then convert that document to `.pdf` server-side before Telegram or business-channel delivery.
- **Decision:** The standard conversion path is headless LibreOffice: `soffice --headless --convert-to pdf`.
- **Decision:** Observability and artifact metadata must explicitly expose `generator_path`, `source_of_truth_generator_path`, `conversion_path`, `artifact_type`, and `conversion_status`, so operators can distinguish successful docx-first delivery from fallback behavior.
- **Decision:** If canonical docx generation or docx-to-pdf conversion fails, the pipeline may use the existing runtime PDF renderer only as a bounded fallback. That fallback must stay explicit via `conversion_status=fallback_runtime_pdf` plus error metadata; it must not silently redefine the format source of truth.
- **Reason:** The approved docx report is already the reliable business-facing standard for structure and style, while maintaining exact parity with a separate runtime PDF renderer has repeatedly created integration drag. Docx-first delivery preserves one canonical format source and still keeps PDF as the delivered artifact.
- **Scope:** This is a bounded `manager_daily` delivery/runtime standard only. It does not redesign the report format, does not change analyzer contracts, does not switch delivery to raw docx, and does not introduce a broader document platform or scheduler redesign.
- **Date:** 2026-04-23

## ADR-049: Manual report delivery channels are explicit and opt-in
- **Decision:** Manual report delivery must resolve to one explicit mode: `preview_only`, `telegram_test_only`, `business_email_only`, or `telegram_and_email`.
- **Decision:** `--no-delivery` / `preview_only` means no Telegram and no business email while artifact/render generation remains allowed.
- **Decision:** Telegram test delivery is allowed only when explicitly enabled by delivery mode or operator flag. `send_email=false` must not enable Telegram by side effect.
- **Decision:** Business email delivery is allowed only when explicitly enabled. For incomplete / `review_required` `manager_daily`, business email remains forced off regardless of requested mode; Telegram operator preview remains possible only when explicitly enabled.
- **Reason:** Step 8O proved manager-ready artifacts through a safe render-only path, but the older always-on Telegram test behavior made `--no-delivery` ambiguous and risky. Explicit channel selection keeps preview/report generation usable without accidental external delivery.
- **Scope:** This changes delivery semantics only. It does not change analyzer prompts, STT/LLM/build logic, scoring, eligibility, selection model, rolling window, report content, `rop_weekly`, or scheduler behavior.
- **Date:** 2026-05-05

## ADR-050: `manager_daily` final call outcomes use deterministic report-day business resolution
- **Decision:** Final manager-facing outcomes in `manager_daily` `ИТОГ ДНЯ` and `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` must be resolved by a deterministic reporting-layer `BusinessOutcomeResolver` over already persisted report-day data: transcript / `interaction.text`, latest reusable or persisted failed analysis, `scores_detail.classification`, `scores_detail.follow_up`, fail reason, and metadata.
- **Decision:** Outcome resolution applies only to report-day `meaningful_calls` / `payload.call_list[]`. Rolling-window calls, coaching_core calls outside the report-day call list, historical calls, weekly data, and `rop_weekly` are not inputs to manager_daily outcome acceptance.
- **Decision:** The priority order is:
  1. technical blockers: `Без транскрипта`, `Без анализа`, technical `Ошибка анализа`, `Ошибка провайдера`;
  2. `Тех/сервис` for contentful service/help calls;
  3. explicit `Отказ`;
  4. commercial `Договорённость`;
  5. `Перенос`;
  6. `Открыт`;
  7. `Не подходит для разбора` only when no business signal exists.
- **Decision:** `not_coachable_or_reportable` is no longer a direct manager-facing outcome mapping. It means the call may be unavailable for coaching, not that it lacks a business outcome. Reporting must first attempt business outcome resolution and only fall back to `Не подходит для разбора` when the call is truly semantic-empty / not business-meaningful.
- **Decision:** Explicit refusal language such as `не рассматриваем`, `не интересно`, `нет необходимости`, `нет потребности`, `уже нашли`, `передумали`, or equivalent persisted follow-up evidence must beat `Открыт` and weak “contact later” agreement.
- **Decision:** Service/help signals such as ЭЦП, QR, NCALayer, signing, document access/signing help, support handoff, or instructions for an already created contract/document must become `Тех/сервис`, even when the analyzer marked the call non-coachable.
- **Reason:** Step 8Q audit of `2026-05-04` report-day call lists showed inflated `Не подходит для разбора`, almost no refusals, and business-significant outcomes hidden behind coaching eligibility / failed semantic analysis states.
- **Scope:** Reporting-layer mapping only. No analyzer prompt, STT/LLM, build_missing, scoring, eligibility, selection model, rolling window, Step 8I gate, Step 8L source-audio refresh, Step 8N validation persistence, Step 8P delivery semantics, PDF layout, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-06

## ADR-051: `manager_daily` post-summary blocks use final report-day business outcomes
- **Decision:** `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` must be built from final report-day `payload.call_list[]` / `BusinessOutcomeResolver` status, not from raw `follow_up` status over `coaching_core`.
- **Decision:** Tomorrow actions include only final `Договорённость`, `Перенос`, and `Открыт`. Final `Отказ`, `Тех/сервис`, `Не подходит для разбора`, `Без транскрипта`, `Без анализа`, `Ошибка анализа`, and `Ошибка провайдера` must not be shown as sales follow-up actions.
- **Decision:** In Step 8U tomorrow priority labels were initially derived from final outcome: `Договорённость -> Горячий`, `Перенос -> Перенос`, `Открыт -> Открытый`. Step 8AH-3 supersedes this label mapping with deterministic hotness while keeping the same inclusion/exclusion source.
- **Decision:** Normal report-day coaching examples (`РАЗБОР ЗВОНКА`, `СИТУАЦИЯ ДНЯ`, `ЧЕЛЛЕНДЖ`) must not silently select final `Отказ` or `Тех/сервис` as ordinary sales coaching examples when at least one final sales-like candidate exists.
- **Reason:** Step 8T showed that post-summary blocks could contradict the resolver-aligned `ИТОГ ДНЯ` and `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`, e.g. final `Открыт` rendered as hot agreement, final `Отказ` shown as follow-up, and final `Тех/сервис` selected as normal call breakdown.
- **Scope:** Reporting payload/post-summary block alignment only. No analyzer prompt, STT/LLM, build_missing, scoring, eligibility, selection model, rolling-window rule, Step 8R resolver priority, delivery semantics, money rule, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-06

## ADR-052: `manager_daily` Situation Day must be evidence-based or explicitly insufficient
- **Decision:** `СИТУАЦИЯ ДНЯ` must not render a strong manager-facing conclusion without either a call reference plus persisted evidence/fragment or an explicit insufficient-evidence state.
- **Decision:** The primary source remains stage-linked persisted `evidence_fragments.client_text` selected by `criterion_code` / focus stage. When that quote is absent, reporting may use the selected sales-like `РАЗБОР ЗВОНКА` call as a bounded fallback evidence source.
- **Decision:** The fallback source order is selected call `evidence_fragments.client_text` with optional manager text, then selected call `interaction.metadata_.segments`, then selected call `interaction.text`. If none exists, renderer must say `Недостаточно подтверждённых фрагментов звонков для доказательного разбора ситуации дня.`
- **Decision:** Speaker roles must not be inferred from unreliable transcript segment labels. Unknown/generic segment speakers remain `speaker=unknown` and render as `Реплика`, not as client/manager dialogue.
- **Decision:** `call_breakdown` carries `call_id`, date/time, client label and phone so post-summary evidence fallback can reference the same selected sales-like call deterministically.
- **Reason:** Step 8V PDFs showed `СИТУАЦИЯ ДНЯ` either empty while `РАЗБОР ЗВОНКА` existed, or showing a conclusion with `Фрагмент звонка в текущем payload не передан`, even though selected calls had persisted transcripts/segments.
- **Scope:** Reporting payload assembly and docx-first render behavior for `СИТУАЦИЯ ДНЯ` only. No analyzer prompt, STT/LLM, build_missing, scoring, eligibility, selection model, rolling window, BusinessOutcomeResolver priority, delivery semantics, PDF layout redesign, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-06

## ADR-053: LLM2 provides additive report-ready evidence; reporting remains deterministic
- **Decision:** The target architecture for `manager_daily` evidence-rich report blocks is `STT -> transcript/segments -> LLM1 routing -> LLM2 deep analysis + report_evidence -> deterministic reporting layer`.
- **Decision:** LLM2 should add an additive `report_evidence_version=v1` / `report_evidence` package to each call analysis. This does not replace the approved MVP-1 analysis contract.
- **Decision:** `report_evidence` contains report-ready candidates for business outcome evidence, Situation Day, manager coaching moments, Voice of Customer, Additional Situations, follow-up candidates, and quote bank. The full contract lives in `docs/REPORT_EVIDENCE_CONTRACT.md`.
- **Decision:** Reporting layer is not an AI analysis layer. It selects report scope, report-day calls, `meaningful_calls`, `coaching_core`, validates/ranks candidates, applies final `BusinessOutcomeResolver` status, aggregates, renders, and falls back to Step 8W legacy evidence logic when `report_evidence` is missing or invalid.
- **Decision:** `BusinessOutcomeResolver` remains the final deterministic source for manager-facing outcome. Future resolver versions may use `report_evidence.business_outcome` as the primary semantic signal, but deterministic priority rules and technical blockers still win.
- **Decision:** Validation must enforce known enums, checklist `stage_code`, speaker values `manager|client|unknown`, transcript-grounded quotes/dialogue, no invented roles, and non-rendering of insufficient evidence as strong proof.
- **Reason:** Step 8W proved the reporting layer can recover evidence from persisted transcripts, but that should remain a compatibility fallback. Report-ready semantic candidates should be prepared during LLM2 analysis so reporting can stay bounded, deterministic, and auditable.
- **Scope:** Design/architecture contract only in Step 8Y. No code implementation, prompt implementation, STT/LLM rerun, build_missing, delivery, report rendering change, mass rebuild, scheduler, or `rop_weekly` behavior change.
- **Date:** 2026-05-06

## ADR-054: `manager_daily` uses one unified client/call display reference
- **Decision:** All `manager_daily` blocks that show a client or call reference must use one display format: `client_name_or_label · phone · date, time`.
- **Decision:** If no persisted name/label is available, the reference is `phone · date, time`; if no phone is available, the reference is `name/label · date, time`. The reporting layer must not invent names and must not duplicate the phone when the label is already the same phone.
- **Decision:** The source priority is persisted analysis call metadata, then persisted interaction metadata, then already assembled reporting call-reference fields. Transcript fragments themselves must not be artificially prefixed with this label.
- **Decision:** The display contract applies to `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and the client column in `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`.
- **Reason:** Step 8AG human review showed the same call rendered inconsistently across blocks: sometimes phone only, sometimes name only, sometimes time without date. A single reference makes final PDFs readable for managers and ROP without changing analysis, selection, outcomes, or delivery behavior.
- **Scope:** Reporting payload / render display layer only. No analyzer prompt, STT/LLM, `report_evidence` contract, `BusinessOutcomeResolver`, source discovery, `build_missing`, readiness, delivery semantics, or radical call-list column redesign.
- **Date:** 2026-05-08

## ADR-055: `manager_daily` tables use human-readable layout labels and status-order call-list sorting
- **Decision:** `manager_daily` table layouts must use manager-facing column labels rather than technical/reporting labels.
- **Decision:** `РАЗБОР ЗВОНКА` renders `Момент / время | Что было | Фрагмент | Рекомендация`. If no timestamp exists, the reporting layer uses `Момент N`; it must not invent precise timestamps.
- **Decision:** `ГОЛОС КЛИЕНТА` renders `Клиент / звонок | Что сказал клиент | Что это значит / Что делать`, not `Паттерн` / `Подтверждающие цитаты`.
- **Decision:** `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` renders `Приоритет | Клиент | Контекст | Рекомендация`; opening script belongs inside the recommendation as `Можно начать: ...`, not as a separate `Первая фраза` column.
- **Decision:** `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` renders `# | Клиент | Тип / суть | Контекст | Статус`. `Клиент` contains the unified client/call reference, including date/time, so a separate `Время` column is not rendered.
- **Decision:** The call list is sorted by manager-facing status order: `Договорённость`, `Перенос`, `Отказ`, `Открыт`, `Тех/сервис`, `Не подходит для разбора`, then technical/unclassified buckets; calls inside the same status group are sorted by time.
- **Reason:** Step 8AG/8AH human review showed that table labels and mixed columns were harder for managers and ROP to read than the underlying content warranted. This presentation cleanup improves readability without changing analysis, outcomes, selection, inclusion/exclusion, or delivery.
- **Scope:** Reporting payload/render model/docx/html/PDF table layout only. No analyzer prompt, STT/LLM, `report_evidence` contract, `BusinessOutcomeResolver`, source discovery, `build_missing`, readiness, delivery semantics, hotness rules, or new short-topic/context generation.
- **Date:** 2026-05-08

## ADR-056: `manager_daily` tomorrow priority is deterministic follow-up hotness
- **Decision:** `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` priority is a deterministic follow-up hotness label, separate from the final manager-facing outcome.
- **Decision:** The only priority labels are `Горячий`, `Перенос`, `Тёплый`, and `Низкий`, backed by internal codes `hot`, `rescheduled`, `warm`, and `low`. `Открытый` remains a final status label but must not be used as a tomorrow priority label.
- **Decision:** Inclusion stays unchanged: include only final `Договорённость`, `Перенос`, and `Открыт`; exclude final `Отказ`, `Тех/сервис`, `Не подходит для разбора`, and technical/unclassified buckets.
- **Decision:** `Горячий` applies to final `Договорённость`; commercial persisted signals such as invoice/payment/meeting/Zoom/demo/date/deadline/purchase/connection/commercial proposal are used as supporting evidence when present. `Перенос` applies to final `Перенос`. Final `Открыт` becomes `Тёплый` only when persisted text/follow-up fields contain explicit interest/materials/KP/WhatsApp/info/consultation signals; otherwise it is `Низкий`.
- **Decision:** Tomorrow contacts sort by `Горячий -> Перенос -> Тёплый -> Низкий`, then nearest deadline, then call time.
- **Reason:** Human review after Step 8AH-2 showed that `Открытый` describes final outcome rather than follow-up urgency. Managers need the priority column to answer how urgently to work the contact tomorrow, while outcome totals and final statuses remain deterministic.
- **Scope:** Reporting payload/render deterministic priority calculation only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract, `BusinessOutcomeResolver`, selection/inclusion rules, delivery semantics, or short-topic/context generation changes.
- **Date:** 2026-05-08

## ADR-057: `report_evidence v1` includes optional call report summary
- **Decision:** `report_evidence v1` supports an optional `call_report_summary` object with `short_topic`, `short_context`, `client_display_name`, `client_name_confidence`, `hotness`, `hotness_reason`, `manager_next_action`, and `suggested_manager_phrase`.
- **Decision:** `call_report_summary` is additive and backward-compatible. Legacy analyses without it remain valid and reusable.
- **Decision:** `call_report_summary.hotness` is only a semantic signal (`hot|warm|low`). It does not override deterministic final outcome, tomorrow inclusion/exclusion, or Step 8AH-3 manager-facing hotness priority. `rescheduled` stays a deterministic final status/category, not LLM summary hotness.
- **Decision:** The reporting layer remains responsible for phone/date/time display through the unified client/call reference. `client_display_name` may provide only an explicit name/FIO/name fragment and must not be invented.
- **Decision:** `suggested_manager_phrase` must be a manager phrase, not copied client text. The validator rejects exact copies of known client quotes and warns on non-null phrases for refusal/tech/not_suitable outcomes without explicit follow-up.
- **Reason:** Human review after Step 8AH-1..8AH-3 showed that table layout and deterministic priority are now cleaner, but future report quality needs LLM2-prepared short topic, context, recommendation, and manager phrase fields without changing rendering or prompts in this bounded step.
- **Scope:** `report_evidence` schema/validator/docs/tests only. No analyzer prompt change, STT/LLM run, source discovery, `build_missing`, report rendering, `BusinessOutcomeResolver`, delivery semantics, or persisted data migration.
- **Date:** 2026-05-08

## ADR-058: `manager_daily` hard refusal matching uses grounded outcome text
- **Decision:** `BusinessOutcomeResolver` must not classify a call as final `Отказ` from synthetic coaching narrative alone.
- **Decision:** Hard refusal keyword matching is grounded in transcript text, classification fields, and persisted follow-up fields. LLM-written coaching text such as `recommendations`, `gaps`, `strengths`, situation meanings, and other risk explanations may not by itself trigger final `Отказ`.
- **Decision:** Broader legacy analysis text may remain available to other established resolver paths in this bounded step; this ADR only narrows hard refusal matching to prevent synthetic-analysis false positives.
- **Reason:** Step 8AH-8A audited Тимур `12:09 / +77470957591`: latest v8 analysis and transcript both supported `Открыт`, but final reporting rendered `Отказ` because the resolver matched `неактуально` inside a coaching recommendation about possible risk, not inside client refusal evidence.
- **Scope:** Reporting-layer `BusinessOutcomeResolver` false-refusal guard only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, PDF layout, money rules, selection/inclusion rules, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-08

## ADR-059: `manager_daily` rejects unsafe client display names
- **Decision:** Unified `manager_daily` client/call references must render a client name/label only after a safe display-name guard accepts it.
- **Decision:** Unsafe exact labels such as `ужас`, `алло`, `да`, `нет`, `не знаю`, `клиент`, `абонент`, `заявка`, `договор`, `эдо`, `поддержка`, `продажи`, `техподдержка`, `менеджер`, and `неизвестно` are not manager-facing names. Phone-like, duplicate-phone, digit-bearing, URL/email-like, too-long, or symbol-noisy values are also rejected.
- **Decision:** When a candidate name is rejected, reporting falls back to `phone · date, time` or date/time only. It must not invent a replacement name.
- **Decision:** Valid persisted names/FIO/name fragments remain allowed. If future display paths consume `report_evidence.call_report_summary.client_display_name`, `client_name_confidence=low` must not become the primary label when a phone is available.
- **Reason:** Step 8AH-8B human-review blocker showed `Ужас · +77774745093 · 4 мая 2026, 06:37` in a final PDF. A wrong or embarrassing client name is worse than showing only phone/date/time.
- **Scope:** Reporting display-name/reference generation only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, `BusinessOutcomeResolver`, selection/inclusion, PDF layout, money rules, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-08

## ADR-060: `manager_daily` uses stable analysis selection by default
- **Decision:** Normal `manager_daily` selection must not blindly use the latest persisted `Analysis` row when that row belongs to a controlled sample or verification run.
- **Decision:** Analysis purpose is stored without DB migration in existing JSON fields: `scores_detail.analysis_purpose` and `scores_detail.meta.analysis_purpose`.
- **Decision:** Allowed purpose values are `production`, `controlled_sample`, and `verification`. Legacy rows without a purpose marker are treated as `production`.
- **Decision:** Default reporting behavior excludes `controlled_sample` and `verification` rows, then selects the newest reusable stable analysis. If the latest stable row is invalid/non-reusable, reporting falls back to an older reusable stable row. If none is reusable, the newest allowed non-reusable row remains available for rejection diagnostics.
- **Decision:** Controlled rows may participate only through explicit opt-in (`include_controlled_samples=true` / `--include-controlled-samples`) for bounded verification.
- **Decision:** Future controlled sample / verification persistence must mark purpose explicitly and must not overwrite an existing production analysis row with the same `instruction_version`.
- **Reason:** Step 8 audit found that controlled exact-call samples can create newer persisted analysis rows and silently change future `manager_daily` reports through latest-by-created-at selection; this already surfaced as the Timur outcome-stability blocker.
- **Scope:** Analysis selection / persistence marker convention only. No DB migration, analyzer prompt change, STT/LLM run, source discovery, `build_missing`, `BusinessOutcomeResolver` semantics, PDF layout, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-08

## ADR-061: `manager_daily` Situation Day client-reaction conclusions require client-grounded evidence when available
- **Decision:** When `СИТУАЦИЯ ДНЯ` makes a conclusion about client reaction or state, a manager-only fragment must not be rendered as strong proof if valid persisted client-grounded evidence exists for the same focus call/package.
- **Decision:** Client-reaction/state includes trust or distrust, convenience to talk, doubt, objection, refusal/reschedule, need, current process, and client barrier cases.
- **Decision:** Evidence ranking for these cases prefers usable `report_evidence.situation_candidates` with client dialogue, then relevant client quotes from valid persisted `report_evidence.voice_of_customer` / `quote_bank`, then transcript/dialogue excerpt, then manager-only fallback, then explicit weak/insufficient evidence.
- **Decision:** If a client quote replaces manager-only proof, the reporting payload marks `source=report_evidence.client_grounded_situation` and `client_grounded=true`, and the Situation Day coaching text must align to that selected client signal without inventing facts.
- **Reason:** Human review found Situation Day conclusions about client reaction where the rendered fragment showed only a manager question, hiding the client response that justified the conclusion.
- **Scope:** Reporting payload evidence selection and deterministic fallback text only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, `BusinessOutcomeResolver`, PDF layout, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-08

## ADR-062: `manager_daily` Voice of Customer recommendations are signal-specific
- **Decision:** `ГОЛОС КЛИЕНТА` must preserve the actual client quote and build the manager action from the quote's client signal rather than using a generic answer fallback when the signal is clear.
- **Decision:** A valid `call_report_summary.manager_next_action` may be used only when it is specific, safe, and aligned with the detected customer signal. Passive instructions such as only waiting for the client do not override stronger deterministic guidance.
- **Decision:** Deterministic Voice of Customer action mapping covers internal discussion / thinking, current-solution-enough, trust or unknown-call barrier, materials/KP/WhatsApp/price request, refusal, and service/signing/QR/NCALayer issues.
- **Decision:** Generic fallback remains allowed only when no specific customer signal is detected.
- **Reason:** Human review found useful client quotes paired with broad recommendations such as passively waiting or generally clarifying the task. Managers need the recommendation to answer what to do next for that exact client signal.
- **Scope:** Reporting payload/render fallback recommendation text only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, `BusinessOutcomeResolver`, PDF layout, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-08

## ADR-063: `manager_daily` tomorrow follow-up recommendations are signal-specific
- **Decision:** `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` must build `Контекст`, `Рекомендация`, and `Можно начать` from one follow-up action profile instead of rendering the same generic recommendation for different sales situations.
- **Decision:** Supported deterministic profiles include invoice/payment, meeting/demo/Zoom, materials/KP/WhatsApp/info, internal discussion / thinking, rescheduled callback, trust or safe-channel barrier, weak open, and generic agreement.
- **Decision:** A valid `call_report_summary.manager_next_action` may override deterministic text only when it is specific and aligned with the detected profile. Generic actions, passive waiting, materials actions without return-to-discussion intent, and trust actions that do not address safe channel/company/purpose must fall back to deterministic profile text.
- **Decision:** This rule does not change Step 8AH-3 hotness priority, final outcome, sorting, or inclusion/exclusion. Tomorrow still includes only final `Договорённость`, `Перенос`, and `Открыт`, and excludes final `Отказ`, `Тех/сервис`, `Не подходит`, and technical/unclassified buckets.
- **Reason:** Human review found that tomorrow follow-up rows could say “Понять текущий интерес клиента...” even when persisted evidence clearly showed a specific invoice, meeting, materials request, internal discussion, reschedule, or trust-channel situation.
- **Scope:** Reporting payload/render recommendation/context generation only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, `BusinessOutcomeResolver`, PDF layout, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-08

## ADR-064: `manager_daily` Call Breakdown must not render missing fragments as strong proof
- **Decision:** `РАЗБОР ЗВОНКА` must prefer coaching moments with concrete persisted evidence fragments over fragmentless moments.
- **Decision:** Candidate ranking first considers call-breakdown evidence strength (`strong`, `medium`, `weak`, `missing`) before the existing stage/priority/quality/score/time ordering.
- **Decision:** Legacy fallback may use persisted `evidence_fragments`, transcript segments, or transcript text to find the strongest meaningful fragment; greeting-only, IVR-like, or empty fragments remain weak/missing.
- **Decision:** If no meaningful fragment exists, the renderer must show `Нет подтверждающего фрагмента в сохранённых данных.` instead of a bare `—`. Weak/missing evidence must use softer wording and must not be described as strong call-specific proof.
- **Reason:** Human review found `РАЗБОР ЗВОНКА` rows where the block selected a coaching moment but rendered `Фрагмент: —`, making generic advice look like evidence-backed call analysis.
- **Scope:** Reporting payload/render evidence ranking and weak-fragment display only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, `BusinessOutcomeResolver`, PDF layout, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-08

## ADR-065: Reports are verification artifacts; fixes must be system-level first
- **Decision:** Generated report artifacts such as PDF, DOCX, HTML, text extracts, Telegram previews, and review packages are verification artifacts, not source of truth for product behavior.
- **Decision:** A report defect must be corrected upstream first: prompt / contract / validator / renderer / template / normalizer / selection logic / deterministic reporting logic / regression tests. Manual editing of a generated report is not an acceptable product fix.
- **Decision:** Reports may be rebuilt only after the mechanism is fixed, after an explicit no-code decision, or as a clearly bounded verification run. A one-off report, manager, call, phone, interaction id, or PDF must not be patched as the implementation.
- **Reason:** Step 8 human-review work showed that PDF-visible issues can tempt point fixes, but reliable `manager_daily` quality requires reusable mechanisms and regression checks before final artifacts are regenerated.
- **Scope:** Project operating rule for report correction and review handoff. This does not change analyzer prompts, report contracts, validators, renderers, selection logic, outcome resolution, delivery semantics, or existing generated artifacts by itself.
- **Date:** 2026-05-10

## ADR-066: `manager_daily` coaching blocks render explicit data scope
- **Decision:** Coaching blocks in `manager_daily` must carry deterministic `data_scope` metadata with one of `report_day`, `expanded_coaching_base`, or `rolling_window`.
- **Decision:** If a selected Situation Day / Call Breakdown example is not from the report-day call list, the renderer must not present it as a plain `СИТУАЦИЯ ДНЯ` / today example. It must label the block or note that the call was selected from the expanded coaching base.
- **Decision:** If a Challenge or coaching metric is aggregated from expanded/rolling data, the renderer must not say `Сегодня` for that metric. It must use expanded-base or `За последние N рабочих дней` wording.
- **Decision:** `ИТОГ ДНЯ`, `ДЕНЬГИ НА СТОЛЕ`, and `СПИСОК ЗВОНКОВ ДНЯ` remain report-day only. Expanded/rolling calls must not enter the call list.
- **Reason:** PM review after Step 8AH-10B found that a non-report-day coaching example and expanded-base counts could be read as if they happened today. The report needs to stay useful for coaching without misleading the manager about the data scope.
- **Scope:** Reporting payload/render semantics and regression tests only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, outcome resolver, scoring, report-day totals, selection inclusion/exclusion, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-10

## ADR-067: `manager_daily` main coaching blocks share one daily coaching focus
- **Decision:** `manager_daily` must build a deterministic `daily_coaching_focus` object and use it as the single stage/problem source for the main coaching layer.
- **Decision:** `daily_coaching_focus` carries focus stage (`stage_id`, `stage_code`, `stage_name`), problem signal/statement, data scope, selected evidence/breakdown call ids, challenge metric source, confidence, and validation status.
- **Decision:** `СИТУАЦИЯ` and `РАЗБОР ЗВОНКА` must not silently select evidence from a different stage than `daily_coaching_focus.stage_code`. Valid `report_evidence` candidates and legacy fallback are filtered to the focus stage.
- **Decision:** If no suitable evidence exists for the focus stage, the block must render an explicit insufficient-evidence fallback instead of replacing the main focus with a secondary signal.
- **Decision:** `ЧЕЛЛЕНДЖ` and focus recommendations use the same focus stage. Stage mismatch is exposed through `daily_coaching_focus_validation` as a warning.
- **Reason:** Step 8AH-10B PM review found a self-contradictory report: stage scores/challenge focused on `Э3`, while Situation and Call Breakdown described `Э1`. Managers need one coherent coaching focus unless a secondary signal is explicitly labeled as secondary.
- **Scope:** Reporting payload/render focus alignment and regression tests only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, outcome resolver, report-day totals, call-list semantics, Step 8AH-11A data-scope rules, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-10

## ADR-068: `manager_daily` problem wording is normalized before manager-facing render
- **Decision:** Positive or neutral statements must not be rendered as `Основная проблема`, `daily_coaching_focus.problem_statement`, Additional Situation gap title/body, or coaching problem wording.
- **Decision:** The reporting layer owns a downstream problem-statement normalizer. It rewrites positive/neutral LLM2 or legacy fallback wording into actionable missing-behavior wording before PDF/DOCX rendering.
- **Decision:** Known positive/neutral patterns such as `Менеджер не ушел в презентацию слишком рано`, `Не ушёл в презентацию слишком рано`, `Сохранил нейтральный, вежливый и понятный тон`, `Представился и обозначил компанию`, and `Понятно обозначил причину звонка` must become manager-facing gap statements rather than being shown as completed actions.
- **Decision:** Additional Situation gap title and body must not contradict each other. If the title is positive/neutral but the section is a growth zone, the title/body are normalized to gap wording; if no safe rewrite exists, the fallback is `Проблема требует уточнения по evidence`.
- **Decision:** Normalization diagnostics are exposed through `problem_wording_diagnostics`; focus-level wording warnings also flow into `daily_coaching_focus.validation.issues`.
- **Reason:** Step 8AH-10B PM review found positive wording such as `Менеджер не ушел в презентацию слишком рано` rendered as a problem, while the actual issue was unfinished qualification before an offer.
- **Scope:** Reporting payload/render/DOCX normalizer and regression tests only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, outcome resolver, scoring semantics, report-day totals, call-list semantics, Step 8AH-11A data-scope rules, Step 8AH-11B daily-coaching-focus stage selection, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-10

## ADR-069: `manager_daily` Additional Situations require evidence/context and non-generic actions
- **Decision:** `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` must pass a reporting-layer quality gate before manager-facing render.
- **Decision:** A rendered additional situation must have a title, stage/signal metadata, data scope, evidence or concrete call context, `what_happened`, `why_it_matters`, `next_action`, `why_this_works`, and medium/high confidence.
- **Decision:** Candidates without evidence/context, unresolved title/body mismatch, duplicate problem signal, low confidence, or unrecoverably generic wording are excluded. If no candidates pass, the section is hidden rather than filled with placeholders or generic filler.
- **Decision:** Generic `why_it_matters` / `next_action` text may be deterministically adapted to stage-specific guidance for primary contact, qualification, needs discovery, presentation, objections, or completion. The same generic recommendation must not be repeated across unrelated signals.
- **Decision:** Payload diagnostics are exposed through `additional_situations_quality` with input/rendered/filtered counts, filter reasons, and rendered-situation metadata.
- **Reason:** Step 8AH-10B PM review found that Additional Situations could look populated while still repeating generic advice without concrete evidence or call context.
- **Scope:** Reporting payload/render/DOCX quality gate, deterministic wording adaptation, diagnostics, and regression tests only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, outcome resolver, scoring semantics, report-day totals, call-list semantics, Step 8AH-11A data-scope rules, Step 8AH-11B daily-coaching-focus semantics, Step 8AH-11C problem normalizer semantics, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-10

## ADR-070: `manager_daily` call-list context is quality-gated before render
- **Decision:** `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ / Контекст` must be selected through a reporting-layer quality gate rather than rendering weak `call_report_summary` or follow-up text directly.
- **Decision:** Source priority is: valid high-quality `call_report_summary.short_context`; specific `call_report_summary.short_topic`; deterministic final-outcome + next-step/deadline fallback; call type + customer-signal fallback; safe fallback text.
- **Decision:** The gate rejects empty, bare-dash, low-information, truncated-with-ellipsis, technical-code-like, and bad-deadline wording such as `до После...`, `до На этой неделе`, or `→ до Конец года 2026`.
- **Decision:** Sales/open/follow-up rows should not render bare `—` when deterministic reporting can explain the context. Technical/service rows receive a service fallback when no sales context exists; not-suitable rows should say that they are not suitable for review.
- **Decision:** Payload diagnostics are exposed through `call_list_context_quality` with source counts, fallback counts, rejected candidate contexts, retained bare contexts, and final failures.
- **Reason:** PM review after Step 8AH-10B found that call-list context could remain empty, truncated, or technical even after deadline wording polish. Managers need a readable context for each business-relevant call without inventing facts or changing final outcomes.
- **Scope:** Reporting payload/render fallback formatting, diagnostics, and regression tests only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` / `call_report_summary` contract, outcome resolver, scoring semantics, report-day totals, call-list inclusion/sorting semantics, Step 8AH-11A data-scope rules, Step 8AH-11B daily-coaching-focus semantics, Step 8AH-11C problem normalizer semantics, Step 8AH-11D Additional Situations quality gate, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-10

## ADR-071: `manager_daily` Call Breakdown rows require confirming evidence and aligned corrective recommendations
- **Decision:** `РАЗБОР ЗВОНКА` must pass a reporting-layer `call_breakdown_quality` gate before manager-facing render.
- **Decision:** A rendered Call Breakdown row must have a confirming evidence fragment / quote / concrete call context. Fragmentless rows and the weak-evidence text `Нет подтверждающего фрагмента в сохранённых данных` must not be rendered as proof.
- **Decision:** If a row describes a growth/problem moment, its recommendation must be corrective and actionable. Positive-only recommendations such as “продолжать использовать...” are filtered unless the row is explicitly a best-practice row.
- **Decision:** The gate filters or cleans duplicate problem wording, low-information fragments, stage mismatches, and punctuation artifacts such as `говорить.: Менеджер...`.
- **Decision:** If no valid row remains for the `daily_coaching_focus` stage, the block renders the explicit fallback `Недостаточно подтверждённых фрагментов для детального разбора по фокусному этапу.` and must not silently switch to another stage.
- **Reason:** PM review after Step 8AH-11G found that Call Breakdown could still show missing-fragment text as a table fragment, pair a problem with a positive-only recommendation, or render punctuation/duplication artifacts. This made the block look evidence-backed when it was not.
- **Scope:** Reporting payload/render quality gate, diagnostics, wording cleanup, and regression tests only. No analyzer prompt, STT/LLM, source discovery, `build_missing`, `report_evidence` contract/validator, outcome resolver, scoring semantics, report-day totals, call-list semantics, Step 8AH-11A data scope, Step 8AH-11B daily coaching focus, Step 8AH-11C problem normalizer, Step 8AH-11D Additional Situations quality gate, Step 8AH-11E call-list context gate, delivery semantics, scheduler, or `rop_weekly` changes.
- **Date:** 2026-05-10

## ADR-072: `manager_daily` semantic blocks may use bounded narrative composition
- **Decision:** For selected report blocks, rigid micro-field/table output may be replaced by bounded narrative composition when the inputs are already selected, evidence-grounded, and validated.
- **Decision:** LLM2 remains the per-call analyzer and report-evidence producer. LLM3 may compose manager-facing narrative for `Ситуация дня`, `Разбор звонка`, `Голос клиента`, follow-up wording, and eligible secondary situations, but it must not change report scope, selected calls/contacts, final statuses, deadlines, or facts.
- **Decision:** Report Layer remains final authority for block eligibility, evidence gates, counter-evidence, speaker/quote safety, Russian manager-facing output, and renderer shape.
- **Decision:** Dialogue rendered in report blocks must be speaker-labelled; uncertain speakers use neutral side labels such as `Сторона 1` / `Сторона 2`; each replica is rendered on a separate line and styled as quote/evidence.
- **Reason:** Human review of 2026-05-19 manager reports showed that the report finally began to carry meaning when LLM3 was allowed to write semantically, while rigid cells were still flattening the actual situation.
- **Scope:** `manager_daily` report-block composition and rendering only. No STT/source discovery, broad analyzer redesign, CRM/revenue integration, scheduler/retries/beat rollout, or auto-business-delivery change.
- **Date:** 2026-05-21

## ADR-073: `Разбор звонка` and `Голос клиента` have separate visible roles
- **Decision:** `Разбор звонка` must show the selected call story and concrete call turns. It must not render a second `Ситуация дня` through extra visible conclusion blocks such as repeated `Что не сработало` / `Как провести лучше`.
- **Decision:** `Голос клиента` must explain what the customer really means and how the manager should work with that signal. It must not turn customer signal interpretation into another manager-gap diagnosis unless the selected evidence explicitly supports that role.
- **Decision:** `Ситуация дня` visible output should be one readable narrative block; structured action/example material can live below it without repeating the same meaning in multiple subheaders.
- **Reason:** The 2026-05-19/20 report review found good semantic content but also duplication between Situation Day, Call Breakdown, and Voice of Customer. Clear block roles make the final report easier to read and reduce repeated advice.
- **Scope:** Visible `manager_daily` block roles, prompts, renderer shape, and docs. No final status/outcome changes, no report-day selection changes, no money/warm-pipeline/challenge expansion in the current bounded step.
- **Date:** 2026-05-21

## ADR-074: Non-doc changes require documentation-impact handling
- **Decision:** Every non-doc change must include a documentation-impact check before close-out. At minimum, non-doc changes require `docs/PROGRESS.md` in the same changeset unless explicitly bypassed with a named reason.
- **Decision:** `docs/PROGRESS.md` is only the minimum audit log. If the change affects behavior, contract, prompt policy, architecture, operating model, roadmap, agent rules, or user-facing report output, the corresponding source-of-truth docs must also be updated.
- **Decision:** Repo hooks enforce the minimum rule twice: `pre-commit` blocks staged non-doc changes without staged `docs/PROGRESS.md`, and `pre-push` blocks pushed non-doc commit ranges without `docs/PROGRESS.md`.
- **Decision:** Hook bypasses (`--no-verify`) are allowed only as explicit intentional overrides and must be named in close-out.
- **Reason:** The previous process relied mostly on agent discipline and a late `pre-push` check. It could still allow code/runtime/process changes to be made without immediately syncing docs, and it did not remind agents at commit time.
- **Scope:** Process governance and Git hook barrier only. This does not change runtime behavior, report generation semantics, analyzer prompts, or delivery.
- **Date:** 2026-05-21
