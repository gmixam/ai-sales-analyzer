FROM python:3.11-slim

WORKDIR /app

# System dependencies: ffmpeg for audio processing, curl for health checks.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .
