"""Build adapters from settings (cached; `reset_adapters()` for tests)."""

from __future__ import annotations

import threading

from ..config import Settings, get_settings
from .embed import Embedder, HashingEmbedder, OllamaEmbedder
from .llm import LLM, FixtureLLM, OllamaBackend, OpenAICompatBackend, ResilientLLM
from .rerank import CrossEncoderReranker, NoopReranker, Reranker

_lock = threading.Lock()
_cache: dict[str, object] = {}


def build_llm(s: Settings) -> LLM:
    if s.llm_provider == "fixture":
        return FixtureLLM(s.fixtures_dir)
    backend: OpenAICompatBackend | OllamaBackend
    if s.llm_provider == "openai_compat":
        backend = OpenAICompatBackend(
            s.openai_base_url, s.openai_api_key, s.llm_main_model, s.llm_fast_model, s.llm_timeout_s
        )
    else:
        backend = OllamaBackend(
            s.ollama_base_url,
            s.llm_main_model,
            s.llm_fast_model,
            s.llm_context_main,
            s.llm_context_fast,
            s.llm_timeout_s,
        )
    return ResilientLLM(backend, fallback_to_fast=s.standby_to_fast_model)


def build_embedder(s: Settings) -> Embedder:
    if s.embedder == "hashing":
        return HashingEmbedder()
    return OllamaEmbedder(s.ollama_base_url, s.embedding_model)


def build_reranker(s: Settings) -> Reranker:
    return CrossEncoderReranker(s.reranker_model) if s.reranker == "cross_encoder" else NoopReranker()


def get_llm() -> LLM:
    with _lock:
        if "llm" not in _cache:
            _cache["llm"] = build_llm(get_settings())
        return _cache["llm"]  # type: ignore[return-value]


def get_embedder() -> Embedder:
    with _lock:
        if "embedder" not in _cache:
            _cache["embedder"] = build_embedder(get_settings())
        return _cache["embedder"]  # type: ignore[return-value]


def get_reranker() -> Reranker:
    with _lock:
        if "reranker" not in _cache:
            _cache["reranker"] = build_reranker(get_settings())
        return _cache["reranker"]  # type: ignore[return-value]


def override(
    llm: LLM | None = None, embedder: Embedder | None = None, reranker: Reranker | None = None
) -> None:
    """Install specific adapters (tests, notebooks)."""
    with _lock:
        if llm is not None:
            _cache["llm"] = llm
        if embedder is not None:
            _cache["embedder"] = embedder
        if reranker is not None:
            _cache["reranker"] = reranker


def reset_adapters() -> None:
    with _lock:
        _cache.clear()
