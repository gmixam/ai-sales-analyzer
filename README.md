# AI Sales Analyzer

`ai-sales-analyzer` — internal MVP-1 project for manual analysis and reporting over sales calls.

Current stage:
- `4.5 Manual Reporting Pilot`

Current focus:
- stable manual operator run for `manager_daily` and `rop_weekly`
- bounded reporting logic and reuse-first execution
- safe repo baseline for continued developer work

Current known gap:
- `closed_with_known_verification_gap` is still open
- the residual blocker is operational, not code-level:
  - billable quota is not yet restored for `OPENAI_API_KEY_STT_MAIN`
  - billable quota is not yet restored for `OPENAI_API_KEY_LLM1_MAIN`
- do not try to "close it on the side" while doing unrelated work

## Start Here

For project context and working boundaries:
1. [docs/CONTEXT_INDEX.md](docs/CONTEXT_INDEX.md)
2. [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
4. [docs/PROGRESS.md](docs/PROGRESS.md)
5. [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)

For developer onboarding:
- [docs/DEV_ONBOARDING.md](docs/DEV_ONBOARDING.md)

## Scope Boundaries

In scope right now:
- Manual Reporting Pilot work
- bounded reporting/analyzer/runtime hardening
- repo hygiene, documentation, and controlled infra steps

Out of scope unless a task explicitly says otherwise:
- scheduler / retries / beat rollout
- automation expansion
- broad prompt redesign
- analyzer contract redesign
- hidden "cleanup" changes outside the assigned bounded step

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
