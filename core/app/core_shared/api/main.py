"""FastAPI application assembly."""

from fastapi import FastAPI

from app.core_shared.api.routes import health, pipeline, status

app = FastAPI(
    title="AI Sales Analyzer",
    version="0.1.0",
    description="Автоматический анализ звонков отдела продаж",
)

app.include_router(health.router)
app.include_router(pipeline.router)
app.include_router(status.router)
