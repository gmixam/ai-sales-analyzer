# AI Sales Analyzer Context

## Project Overview
- **Project:** AI Sales Analyzer
- **Goal:** Automated analysis of sales calls with a pipeline from call ingestion to transcription, AI analysis, and delivery of insights to managers and sales leads.
- **Current stage:** MVP-1 foundation. At this stage we are setting up the project skeleton, shared conventions, and architectural constraints that all future implementation must follow.

## Tech Stack
- Python 3.11+
- FastAPI
- Celery
- Redis
- PostgreSQL
- AssemblyAI for speech-to-text
- OpenAI GPT-4o / GPT-4o-mini
- Docker and Docker Compose
- Self-hosted VPS deployment

## Architecture Principles
- **Agent = isolated Python module, not an autonomous AI agent.**
  Each domain-specific pipeline lives in its own module with the standard structure:
  `intake / extractor / analyzer / delivery / prompts / config`.
- **Interaction is the universal processing unit.**
  The system should be designed around a generic `interaction` entity that can represent:
  `call | email | chat | doc | meeting`.
- **`department_id` must exist on every database table.**
  This is a hard invariant. Never remove it. It enables strict departmental isolation and preserves the path to multi-tenant support without redesigning the schema later.
- **`instruction_version` must exist on every analysis record.**
  This is a hard invariant. Never remove it. It allows prompt version tracking, BI slicing, controlled rollouts, and A/B analysis.
- **LLM JSON response structure is a contract.**
  Field names and field types must remain stable across prompt versions. Prompts may improve, but the response schema cannot break downstream consumers.
- **Celery is required for all heavy operations.**
  STT, LLM calls, batch processing, and other expensive or long-running jobs must run asynchronously via Celery workers.

## Project Structure
- `docs/` — architecture notes, decisions, progress tracking, and prompt design guidance.
- `core/` — application source tree and service packaging.
- `core/app/agents/` — isolated domain agents with deterministic processing pipelines.
- `core/app/agents/calls/` — the first MVP agent for call processing.
- `core/app/core_shared/` — shared infrastructure: DB access, API shell, workers, scheduler, and settings.
- `infra/` — deployment and operational assets such as nginx, database init, and helper scripts.
- `tests/` — test package and shared fixtures for future automated validation.

## Coding Conventions
- **Language:** Python 3.11+
- **Formatting and linting:** `ruff`
- **Typing:** use type hints everywhere
- **Schemas:** use Pydantic for all external and internal data contracts
- **Error handling:** define custom exceptions in `core_shared/exceptions.py`
- **Logging:** use `structlog` with contextual fields on every relevant event
- **Required log context:** `interaction_id`, `manager_id`, `department_id`
- **Constants:** keep constants only in `config/settings.py` or in the corresponding agent `config.py`

## What NOT to do
- Do not change LLM JSON response structures.
- Do not remove `department_id` or `instruction_version`.
- Do not place business logic inside `api/routes`.
- Do not call the database directly from agents; use `core_shared/db` only.

## Current Sprint
- TODO: define current sprint goals, scope, acceptance criteria, and blockers.
