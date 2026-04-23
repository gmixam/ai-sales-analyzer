FROM python:3.11-slim

WORKDIR /app

# System dependencies: ffmpeg for audio processing, curl for health checks,
# Node.js + docx for canonical manager_daily .docx generation,
# LibreOffice Writer for deterministic headless docx -> pdf conversion.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    libpq-dev \
    gcc \
    nodejs \
    npm \
    libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g docx@9.6.1

ENV NODE_PATH=/usr/local/lib/node_modules:/usr/lib/node_modules

# Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .
