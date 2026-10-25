"""Central configuration. Everything is overridable by environment variable (see .env.example)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIM = 1024  # fixed by the schema (vector(1024)); every embedder must produce this size


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- database -------------------------------------------------------------------------
    database_url: str = "postgresql://lw:lw@localhost:5432/legal_workspace"
    db_pool_max: int = 12

    # --- storage --------------------------------------------------------------------------
    storage_dir: Path = Path("./storage")

    # --- models ---------------------------------------------------------------------------
    # ollama: local open-weight models via Ollama (default; no cost, runs on a laptop)
    # openai_compat: any OpenAI-compatible server (vLLM, llama.cpp server, LM Studio, ...)
    # fixture: replays recorded extractions for the bundled synthetic matters (demo / CI; no model needed)
    llm_provider: Literal["ollama", "openai_compat", "fixture"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str = "http://localhost:8000/v1"
    openai_api_key: str = "EMPTY"
    llm_main_model: str = "qwen3:8b"  # extraction, answers, hearing brief
    llm_fast_model: str = "qwen3:4b"  # router, classifier
    llm_context_main: int = 16384
    llm_context_fast: int = 8192
    llm_timeout_s: float = 600.0

    # ollama: real embeddings via Ollama (bge-m3, 1024-d) | hashing: offline deterministic (tests, demo)
    embedder: Literal["ollama", "hashing"] = "ollama"
    embedding_model: str = "bge-m3"

    reranker: Literal["none", "cross_encoder"] = "none"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # --- ingestion ------------------------------------------------------------------------
    max_upload_mb: int = 50
    ocr_min_chars: int = 25  # a page with fewer extractable characters is sent to OCR
    ocr_low_confidence: float = 60.0  # pages below this mean confidence are flagged in the UI
    classification_min_confidence: float = 0.7
    extract_window_tokens: int = 1500
    quote_match_threshold: int = 90  # rapidfuzz score for "quote is on the cited page"
    worker_concurrency: int = 2
    job_stale_after_s: int = 600
    job_max_attempts: int = 3
    embedded_worker: bool = True  # run the worker inside the API process (handy locally)

    # --- retrieval / answers --------------------------------------------------------------
    retrieval_candidates: int = 30
    retrieval_final: int = 8
    narrative_enabled: bool = True  # LLM-written summaries on top of code-rendered statements
    standby_to_fast_model: bool = True

    # --- time -----------------------------------------------------------------------------
    # The synthetic matters are dated 2023-2025; set WORKSPACE_TODAY to demo "overdue" logic.
    workspace_today: date | None = None

    # --- auth -----------------------------------------------------------------------------
    auth_enabled: bool = False
    jwt_secret: str = "change-me"
    jwt_ttl_minutes: int = 480
    # "user:password,user2:password2"
    auth_users: str = "admin:admin:admin"  # user:password[:role], roles viewer < analyst < admin
    rate_limit_per_min: int = 240  # per client IP; 0 disables
    login_attempts_per_min: int = 8
    auto_migrate: bool = True
    corpus_autoload: bool = True

    # --- misc -----------------------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    log_level: str = "INFO"
    log_json: bool = False
    api_host: str = "0.0.0.0"  # noqa: S104 - bound inside a container / on localhost by default
    api_port: int = 8000

    fixtures_dir: Path = Field(default=Path("./data/fixtures"))
    ui_dist: Path | None = Path("./ui/dist")  # served at / when it has been built (single-process local run)

    def today(self) -> date:
        return self.workspace_today or date.today()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def users(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in self.auth_users.split(","):
            if ":" in pair:
                u, p = pair.split(":", 1)
                out[u.strip()] = p.strip()
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
