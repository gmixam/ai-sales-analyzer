# Architecture

## System Overview
The MVP pipeline for a sales call is organized as eight sequential stages:

1. **Ingestion** — receive or discover a new call interaction from the source system.
2. **Filtering** — validate whether the call matches business rules for analysis.
3. **Download** — fetch the raw call artifact from the telephony provider.
4. **STT** — send audio to AssemblyAI and retrieve a transcript.
5. **LLM-1** — run the first model pass for classification and structured extraction.
6. **LLM-2** — run the second model pass for deeper analysis, scoring, agreements, and insights.
7. **Persistence** — write normalized outputs to PostgreSQL with full metadata.
8. **Delivery** — send reports or notifications to the manager and the head of sales.

Heavy stages such as download preparation, STT, and LLM processing must run asynchronously through Celery.

## AI Execution Layers
- `STT` runs in `CallsExtractor`.
- `LLM-1` and `LLM-2` belong to `CallsAnalyzer`.
- Provider/account selection for these layers is centralized in a shared routing layer instead of being hardcoded per call site.

Current MVP-1 runtime status:
- `STT`: routed and executed through the provider router.
- `LLM-1`: routed and executed through a separate first-pass request for classification / summary / follow-up context.
- `LLM-2`: routed and executed through the provider router for the approved deep-analysis request.
- Current adapter scope is intentionally bounded:
  - `STT` has concrete runtime adapters for `assemblyai` and `openai/whisper`.
  - `LLM-1` currently runs through the OpenAI client using routed `model` + `api_base`, so other vendors require OpenAI-compatible API semantics or a future explicit adapter.
  - `LLM-2` currently runs through the OpenAI client using routed `model` + `api_base`, so other vendors require OpenAI-compatible API semantics or a future explicit adapter.
- Current execution boundary is also intentionally explicit:
  - router selection and execution compatibility are not the same thing;
  - current runtime now enforces explicit executor-preflight compatibility guardrails so routing-valid config is not mistaken for execution-ready adapter support.

## Agent Architecture
An agent is a deterministic Python module that owns one interaction workflow. It is not an autonomous AI runtime. Each agent follows a standard internal shape:

- `intake` — receives source events or polling results
- `extractor` — normalizes payloads and prepares structured inputs
- `analyzer` — runs prompt-driven LLM logic with strict output schemas
- `delivery` — sends results to external systems or users
- `prompts` — versioned prompt texts
- `config` — agent-specific constants and settings

For the current MVP-1 progression, manager/department mapping may use a light Bitrix24 read-only path before fallback to manual pilot bootstrap. This path must stay read-only, deterministic, and compatible with the same `interactions` / `analyses` schema.

## Manual Reporting Pilot
The next agreed MVP-1 operating mode is `Manual Reporting Pilot`.

This mode:
- stays manual and parameter-driven;
- reuses already-built artifacts whenever their effective versions have not changed;
- allows bounded `scheduled_reviewable_reporting` before pilot, but does not imply scheduler/retry/beat/full automation loop;
- does not change the approved analyzer contract;
- does not redesign the core calls pipeline.

First launch parameters are expected to include:
- one or more managers;
- period;
- `min_duration`;
- `max_duration`;
- `report_preset`;
- model/version selection;
- email delivery.

First launch presets:
- `manager_daily`
- `rop_weekly`

Manual execution modes:
- `build_missing_and_report`
- `report_from_ready_data_only`

Delivery rules for this mode:
- email only;
- each report goes to the resolved primary recipient and the monitoring email `sales@dogovor24.kz`;
- recipient resolution comes from Bitrix manager / org-structure data as a configurable rule, not a hardcoded address.

Allowed bounded extension:
- an optional report-composer LLM step may synthesize daily recommendations, focus summaries, weekly narratives, and interpretation blocks from already prepared artifacts.
- this is not a new core AI layer and not an analyzer redesign.

Implementation boundary for the first bounded slice:
- reuse the existing manual/operator-driven entrypoint pattern instead of introducing scheduler-driven orchestration;
- keep report execution organized as:
  1. manual trigger
  2. preset resolution
  3. filter resolution
  4. artifact lookup / reuse
  5. build-missing path
  6. report input builder
  7. optional report-composer step
  8. normalized report payload builder
  9. rendering
  10. email delivery
- keep three concerns separated:
  - selection / reuse / build logic
  - normalized report payload contract
  - rendering / delivery formatting
- do not couple semantic/visual report templates or PDF rendering to data aggregation logic;
- allow placeholder sections in the payload for CRM-dependent or future-filled blocks without breaking the v1 report contract.

Canonical reporting payload direction for the first slice:
- `manager_daily` and `rop_weekly` should each have a normalized payload contract before rendering;
- payload sections should explicitly distinguish:
  - raw / calculated fields
  - model-dependent fields
  - CRM-dependent fields
  - delivery-only presentation metadata
- this allows:
  - reuse-first execution
  - selective rerun of only model-dependent reporting steps
  - multiple renderers later without changing upstream aggregation logic.

Reuse-first rule in implementation terms:
- existing artifacts such as transcript, analysis payload, checklist-derived fields, manager identity, and report inputs should be reused when their effective dependency versions are still valid;
- changing a reporting model or report-composer prompt must not imply a full pipeline rerun by default;
- selective rerun is allowed only for the model-dependent reporting step when upstream source artifacts remain valid.
- current stricter reporting reuse check means transcript reuse still depends on non-empty `interaction.text`, while analysis reuse now also depends on reporting-compatible persisted shape (`instruction_version`, `classification`, `score.checklist_score.score_percent`, `score_by_stage`, `strengths`, `gaps`, `recommendations`, `follow_up`);
- analyzer success now has two bounded gates:
  - shape-valid approved-contract normalization
  - semantic-valid analysis payload
- the first semantic-invalid rule is `semantically_empty_analysis`: if `score_by_stage`, `strengths`, `gaps`, and `recommendations` are all empty together, the output is not treated as a successful analysis even if the JSON shape is otherwise valid;
- `analyses.raw_llm_response` now stores the raw `LLM-2` response text, while normalized approved-contract data stays separate in `scores_detail`;
- when a persisted analysis fails that stricter reporting reuse check, the reporting path treats it as missing: `build_missing_and_report` may rebuild only the analysis step, while `report_from_ready_data_only` leaves it outside the ready subset;
- failed analyses carrying `fail_reason=semantically_empty_analysis` and older persisted semantic-empty contracts are both non-reusable for reporting;
- reporting-specific steps themselves are not reused between manual runs in this slice: payload assembly, readiness gating, and final render always rebuild against the current `report_logic_version`, `reuse_policy_version`, and active template version.

Current bounded implementation status:
- manual report execution now has a dedicated bounded orchestration path and manual CLI/API entrypoints;
- the first operator-facing internal web page now sits on top of the same bounded reporting API path, inside the existing FastAPI app rather than a separate frontend project;
- the operator UI can manually refresh the local Bitrix-synced manager directory for one selected department before running reports, so the manager picker is not limited to stale mirrored rows from older call-driven syncs;
- the operator UI now supports zero, one, or many selected managers/extensions without changing the `/pipeline/calls/report-run` request contract, because that contract already accepts `manager_ids[]` and `manager_extensions[]`;
- `manager_daily` now uses a source-aware manual full-run model: it starts with OnlinePBX discovery for the selected day + filters, checks what is already persisted locally, ingests only missing interactions, and then continues with reuse-first report preparation;
- repeated manual runs stay idempotent on persistence because missing-source ingest reuses existing `external_id` rows instead of creating duplicate interactions;
- for `manager_daily`, `report_from_ready_data_only` still performs source discovery + persistence-check + ingest-missing, but it stops short of audio fetch / `STT` / `LLM-1` / `LLM-2` for interactions that are not already ready;
- for `manager_daily`, `build_missing_and_report` continues from the same source-aware selection and then runs the full upstream build chain for fresh/missing cases in this exact order: audio fetch -> `STT` -> `LLM-1` -> `LLM-2` -> persistence -> report build / delivery;
- for `manager_daily`, render/delivery is now gated by a bounded readiness decision after source/reuse/build and before final artifact generation: the path may emit `full_report`, `signal_report`, or `skip_accumulate` instead of forcing a full daily report on a weak base;
- the first readiness thresholds are intentionally fixed and local to the reporting slice: `full_report` requires `relevant_calls >= 6`, `ready_analyses >= 5`, `analysis_coverage >= 75%`, and key content blocks without empty fallback; `signal_report` requires `ready_analyses >= 2` plus one explicit signal and one clear action;
- readiness window expansion for `manager_daily` is bounded to `1 -> 2 -> 3` working days only;
- `rop_weekly` now uses an explicitly different execution model: persisted-only aggregation over already stored interactions/analyses, with no source discovery, no ingest of missing calls, and no new audio / `STT` / `LLM-1` / `LLM-2` execution even if the requested mode is `build_missing_and_report`;
- normalized payloads are built before rendering for both `manager_daily` and `rop_weekly`;
- final report rendering now uses repo-local versioned template assets as standing source of truth:
  - semantic blocks in `core/app/agents/calls/report_template_assets/<preset>/<version>/semantic.json`
  - visual/layout assets in `core/app/agents/calls/report_template_assets/<preset>/<version>/visual.json` and `layout.css`
  - active versions in `core/app/agents/calls/report_template_assets/active_versions.json`
- visual/layout source of truth for the first standard templates comes from:
  - `manager_daily` visual baseline is adapted from the approved HTML reference asset `docs/report_templates/reference/manager_daily_reference_html`, while `docs/report_templates/reference/manager_daily_reference.md` stays the repo-readable summary of the same layout contract;
  - `docs/report_templates/reference/rop_weekly_reference.md`
- current active template versions are `manager_daily_template_v1` and `rop_weekly_template_v1`;
- the main operator artifact is now a rendered PDF report built from the active template version, while HTML/text remain preview/supporting render outputs;
- `manager_daily_template_v1` now renders a reference-aligned composition with hero banner, summary tiles, narrative box, signal/focus banners, two-column review, recommendation cards, outcomes table, dynamics block, and memo page, rather than a generic section dump;
- the operator page uses lightweight supporting endpoints for form context, local-manager sync, and recipient preview, while report execution still goes through the existing `/pipeline/calls/report-run` contract;
- email delivery now has a reporting-specific skeleton with `To + Cc + text/html` support;
- Telegram test delivery for operator runs now sends the final PDF document artifact, not a text-only dump;
- optional business email delivery reuses the same final PDF artifact as attachment while preserving HTML/text body preview;
- operator manual runs now use split delivery semantics: Telegram test delivery to `TEST_DELIVERY_TELEGRAM_CHAT_ID` is always attempted for every run, while business email delivery is optional and controlled separately by the operator UI toggle;
- business email recipients are still resolved and exposed as reference metadata, but email is not sent unless the operator explicitly enables it;
- `manager_daily` recipient resolution uses the manager email stored in the local Bitrix-synced manager card;
- `rop_weekly` recipient resolution uses `department.settings.reporting.rop_weekly_email` when configured, and otherwise falls back to live Bitrix `department.UF_HEAD -> active user EMAIL`;
- reporting delivery failures are normalized back into structured report statuses instead of escaping as CLI/API-level tracebacks;
- source/build failures in the manual full-run path are also normalized back into structured `blocked` / `partial` report results with observability stage errors, instead of escaping from `/pipeline/calls/report-run` as raw HTTP traceback-only failures;
- operator observability/diagnostics now expose the preset-specific execution model explicitly, so `rop_weekly` transparently shows `persisted_only` together with skipped source/build stages rather than looking like an unexplained no-op;
- operator observability now also separates `telegram_test_delivery` and `email_delivery`, so the page can show `Telegram delivered / email skipped|delivered|failed` instead of one mixed channel state;
- operator result / observability now also expose effective `template_version`, so the UI can show which standard template produced the current PDF artifact;
- operator result / diagnostics for `manager_daily` now also expose readiness metadata (`readiness_outcome`, reason codes, chosen window, readiness metrics, content-block presence) as part of the bounded reporting result rather than a separate subsystem;
- payload richness for both presets now comes from deterministic assembly over already approved persisted analysis fields such as `score_by_stage`, `follow_up`, `product_signals`, and `evidence_fragments`, without changing the normalized report contract;
- monitoring copy defaults to `sales@dogovor24.kz`, with optional override through `department.settings.reporting.monitoring_email`.

### Scheduled Reviewable Reporting

Before pilot the system also allows one bounded operational mode: `scheduled_reviewable_reporting`.

This mode is intentionally narrow:
- schedule creation lives inside the existing backend/operator UI surface;
- schedule timing fields (`start_date`, `start_time`, `timezone`, `recurrence_type`) define only when a run starts;
- `report_period_rule` defines only what data window the run reads;
- automatic execution may create the report artifact, but it must stop at `review_required`;
- business delivery remains a separate explicit operator approve action;
- this is not a full automation loop.

Persisted runtime objects for this mode:
- `report_schedules` — future-dated schedule definitions
- `scheduled_report_batches` — one scheduled occurrence / lifecycle instance
- `scheduled_report_drafts` — reviewable draft artifacts for one batch

Lifecycle for scheduled batches:
- `planned`
- `queued`
- `running`
- `review_required`
- `approved_for_delivery`
- `delivered`
- `failed`
- `paused`

Separation of concerns in this mode:
- raw analysis artifacts remain in the existing `interactions` / `analyses` pipeline and stay immutable;
- only bounded business-facing draft blocks are editable before approve;
- final approved delivery reuses the prepared draft/report path and does not redesign the run.

## AI Provider Routing
The system supports layer-specific provider pools for:

- `STT`
- `LLM-1`
- `LLM-2`

Each pool may contain multiple provider/account entries with model, timeout, retry, weight, and account alias metadata.

Supported routing policies:

- `fixed`
- `failover`
- `weighted_ab`
- `manual_force`

Routing requirements:

- deterministic selection for the same subject key;
- audit-friendly metadata in logs and persistence;
- backward-compatible legacy single-provider behavior when only one entry is configured;
- no pipeline-level scheduler/retry semantics introduced by this layer.
- explicit distinction between `openai_compatible` execution and vendor-specific/custom adapters for runtime safety.
- fail-fast executor-preflight on execution-incompatible candidates, with diagnostic audit metadata preserved.

Detailed config schema and metadata format: [docs/AI_PROVIDER_ROUTING.md](docs/AI_PROVIDER_ROUTING.md)
Detailed reporting-pilot operating model: [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)

To add a new agent:

1. Create a new folder under `core/app/agents/` with the standard module layout.
2. Register the agent in the shared registry so the application can discover it.
3. Reuse shared DB, worker, config, and schema conventions without bypassing platform rules.

## Data Model
Core tables planned for the MVP:

- `interactions` — source-level records for calls and later other interaction types.
- `analyses` — main AI analysis output for each interaction, including `instruction_version`.
- `agreements` — extracted promises, next steps, and commitments from the conversation.
- `insights` — reusable analytical conclusions, risks, and coaching points.
- `prompts` — stored prompt definitions, metadata, and versions used by the system.
- `manager_progress` — longitudinal view of manager performance and coaching dynamics.
- `prompt_suggestions` — candidate prompt improvements proposed by operators or analytics.
- `departments` — business unit boundaries used for data isolation.
- `managers` — manager profiles, mappings, and report recipients.

## Key Invariants
- Every database table must contain `department_id`.
- Every analysis record must contain `instruction_version`.
- LLM output JSON shape is a contract: field names and field types are stable across prompt revisions.

These rules are architectural constraints, not optional implementation details.

## Infrastructure
The project is designed for Docker Compose-based deployment with the following services:

- `postgres` — primary relational database for all operational and analytical records
- `redis` — Celery broker and lightweight queue/cache layer
- `api` — FastAPI application for health, orchestration endpoints, and control-plane access
- `worker` — Celery worker for STT, LLM, and heavy background jobs
- `beat` — scheduler for periodic polling and maintenance jobs
- `flower` — task monitoring UI for Celery
- `nginx` — reverse proxy and entrypoint for external traffic
