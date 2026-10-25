# syntax=docker/dockerfile:1.7
# One image for the API and the ingestion worker (different commands).
FROM python:3.12-slim AS base
ARG WITH_LIBREOFFICE=false
ARG WITH_RERANKER=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng fonts-dejavu-core libgl1 libglib2.0-0 curl \
    && if [ "$WITH_LIBREOFFICE" = "true" ]; then apt-get install -y --no-install-recommends libreoffice-writer; fi \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && if [ "$WITH_RERANKER" = "true" ]; then pip install ".[rerank]"; fi
COPY data ./data
RUN useradd -m -u 10001 lw && mkdir -p /app/storage && chown -R lw /app/storage
USER lw
ENV STORAGE_DIR=/app/storage
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD curl -fsS http://localhost:8000/api/v1/healthz/live || exit 1
CMD ["lw-api"]
