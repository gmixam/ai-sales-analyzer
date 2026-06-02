# AI Sales Analyzer

`ai-sales-analyzer` — internal MVP-1 project for manual analysis and reporting over sales calls.

Current stage:
- `6.5 Business-ready Report Pack`

Current focus:
- LLM2 v15 `block-ready` per-call analysis for `manager_daily`
- LLM3 narrative composers for grounded manager-facing report blocks
- semantic quality of `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`
- ready-only/no-delivery report previews before business delivery

Current known gap:
- current report-quality work is not a full automation rollout
- generated previews may be `partial` when ready-data coverage is incomplete, even when the report-level artifact is `ready`
- remaining active tasks are documented in `docs/PROGRESS.md` and `docs/BUSINESS_READY_REPORT_PACK_TASKS.md`
- money / warm pipeline / challenge broad consistency work is intentionally not part of the current bounded next step unless explicitly reopened

## Start Here

For project context and working boundaries:
1. [docs/CONTEXT_INDEX.md](docs/CONTEXT_INDEX.md)
2. [docs/RUNTIME_PROFILES.md](docs/RUNTIME_PROFILES.md)
3. [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
4. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
5. [docs/PROGRESS.md](docs/PROGRESS.md)
6. [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)

For developer onboarding:
- [docs/DEV_ONBOARDING.md](docs/DEV_ONBOARDING.md)

## Scope Boundaries

In scope right now:
- Manual Reporting Pilot work
- bounded reporting/analyzer/runtime hardening
- repo hygiene, documentation, and controlled infra steps
- Business-ready `manager_daily` report-quality work on existing persisted calls/analyses
- prompt/contract/render updates that improve grounded manager-facing report blocks

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
docker compose run --rm api python -m unittest tests.test_ai_provider_routing tests.test_manual_reporting
```

## Git

The local repo already has a baseline Git history.

Current expectations:
- work from `main` or from short-lived feature branches
- do not commit secrets, `.env`, TLS keys, or local runtime artifacts
- do not rewrite history or force-push without explicit agreement

If you are joining the project, read [docs/DEV_ONBOARDING.md](docs/DEV_ONBOARDING.md) before making changes.
