# AI Sales Analyzer

`ai-sales-analyzer` — internal MVP-1 project for manual analysis and reporting over sales calls.

Current stage:
- MVP-1 pilot operations after `6.5 Business-ready Report Pack` audit/fix pass

Current focus:
- daily pilot runs for selected managers
- KPI / GO-NO-GO measurement through `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md`
- cost tracking through `observability.ai_costs`
- operator review before business email delivery
- compact LLM2 input as the default runtime profile

Current known gap:
- generated previews may be `partial` when ready-data coverage is incomplete, even when the report-level artifact is `ready`
- Kimi K2.6 is connected but not accepted as full-day LLM2 runtime for the current layered contract
- broad code refactors are deferred until the pilot loop is stable

## Start Here

For project context and working boundaries:
1. [docs/CONTEXT_INDEX.md](docs/CONTEXT_INDEX.md)
2. [docs/PILOT_OPERATIONS.md](docs/PILOT_OPERATIONS.md)
3. [docs/RUNTIME_PROFILES.md](docs/RUNTIME_PROFILES.md)
4. [docs/MVP1_PILOT_METRICS_MEASUREMENTS.md](docs/MVP1_PILOT_METRICS_MEASUREMENTS.md)
5. [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
6. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
7. [docs/PROGRESS.md](docs/PROGRESS.md)
8. [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)

For developer onboarding:
- [docs/DEV_ONBOARDING.md](docs/DEV_ONBOARDING.md)

## Scope Boundaries

In scope right now:
- Manual Reporting Pilot work
- daily pilot execution and measurement
- bounded reporting/analyzer/runtime hardening required by pilot findings
- repo hygiene, documentation, and controlled infra steps
- business delivery only after operator review or explicit user request

Out of scope unless a task explicitly says otherwise:
- scheduler / retries / beat rollout
- automation expansion
- broad analyzer redesign
- analyzer contract redesign
- hidden "cleanup" changes outside the assigned bounded step
- external CRM/money/revenue integrations
- auto-send to business without operator review

## Quick Start

1. Copy env template:

```bash
cp .env.example .env
```

2. Fill `.env` with real local credentials and runtime values.

3. Start the stack:

```bash
make up
```

4. Check status:

```bash
make status
curl -s http://localhost:8081/health
```

5. Open the operator UI:

```text
http://localhost:8000/pipeline/calls/report-ui
```

## Useful Commands

```bash
make up
make down
make logs
make status
make shell
make db-shell
make migrate
```

Fresh test run in container:

```bash
docker compose exec -T api python -m pytest -q /app/tests/test_ai_costs.py /app/tests/test_calls_delivery_text.py
```

## Git

The local repo already has a baseline Git history.

Current expectations:
- work from `main` or from short-lived feature branches
- do not commit secrets, `.env`, TLS keys, or local runtime artifacts
- do not rewrite history or force-push without explicit agreement

If you are joining the project, read [docs/DEV_ONBOARDING.md](docs/DEV_ONBOARDING.md) before making changes.
