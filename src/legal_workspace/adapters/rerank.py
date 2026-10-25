"""Reranker port. Default: none (RRF order is kept). Optional: BGE cross-encoder (open source)."""

from __future__ import annotations

from typing import Any, Protocol


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """One relevance score per text (higher = better)."""
        ...

    def health(self) -> dict[str, Any]: ...


class NoopReranker:
    name = "none"

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        n = len(texts)
        return [1.0 - i / max(n, 1) for i in range(n)]  # preserves the incoming (fused) order

    def health(self) -> dict[str, Any]:
        return {"ok": True, "detail": "disabled"}


class CrossEncoderReranker:
    """bge-reranker-v2-m3 via sentence-transformers (pip install '.[rerank]'; first use downloads ~2 GB)."""

    def __init__(self, model: str) -> None:
        self.name = f"cross-encoder:{model}"
        self.model_id = model
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:  # pragma: no cover - depends on optional extra
                raise RuntimeError("install the reranker extra: pip install '.[rerank]'") from e
            self._model = CrossEncoder(self.model_id, max_length=512)
        return self._model

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        scores = self._load().predict([(query, t) for t in texts])
        return [float(s) for s in scores]

    def health(self) -> dict[str, Any]:
        try:
            self._load()
            return {"ok": True, "detail": "ok"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": str(e)}
