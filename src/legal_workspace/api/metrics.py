"""Prometheus metrics (exposed at /metrics)."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()
REQUESTS = Counter(
    "lw_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY
)
LATENCY = Histogram("lw_http_request_seconds", "HTTP request latency", ["route"], registry=REGISTRY,
                    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120))  # fmt: skip
ANSWERS = Counter("lw_answers_total", "Answers produced", ["mode"], registry=REGISTRY)
UNVERIFIED = Counter(
    "lw_unverified_sentences_total", "Sentences dropped by citation verification", registry=REGISTRY
)
UPLOADS = Counter("lw_uploads_total", "Uploaded files", ["result"], registry=REGISTRY)
JOBS = Gauge("lw_jobs", "Ingestion jobs by status", ["status"], registry=REGISTRY)


def render() -> bytes:
    return generate_latest(REGISTRY)
