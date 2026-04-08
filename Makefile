COMPOSE = docker compose

.PHONY: up down logs shell migrate seed test lint status migrate-create migrate-down db-shell

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

shell:
	$(COMPOSE) exec api bash

seed:
	$(COMPOSE) exec api python infra/scripts/seed_prompts.py

test:
	pytest

lint:
	ruff check .

status:
	$(COMPOSE) ps

migrate:
	docker compose exec api alembic -c app/core_shared/db/migrations/alembic.ini upgrade head

migrate-create:
	docker compose exec api alembic -c app/core_shared/db/migrations/alembic.ini revision --autogenerate -m "$(name)"

migrate-down:
	docker compose exec api alembic -c app/core_shared/db/migrations/alembic.ini downgrade -1

db-shell:
	docker compose exec postgres psql -U $${POSTGRES_USER} -d $${POSTGRES_DB}
