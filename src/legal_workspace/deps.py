"""Runtime dependencies bundled for the services (explicit, so tests can swap any of them)."""

from __future__ import annotations

from dataclasses import dataclass

from .adapters import factory
from .adapters.embed import Embedder
from .adapters.llm import LLM
from .adapters.rerank import Reranker
from .config import Settings, get_settings
from .storage import FileStorage, Storage


@dataclass
class Deps:
    settings: Settings
    llm: LLM
    embedder: Embedder
    reranker: Reranker
    storage: Storage


def default_deps() -> Deps:
    s = get_settings()
    return Deps(
        s, factory.get_llm(), factory.get_embedder(), factory.get_reranker(), FileStorage(s.storage_dir)
    )
