"""Embedding port: Ollama (bge-m3, 1024-d) and an offline deterministic hashing embedder."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

import httpx
import numpy as np

from ..config import EMBEDDING_DIM
from ..errors import ModelOutputInvalid, ModelUnavailable


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def health(self) -> dict[str, Any]: ...


def _l2(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        batch: int = 16,
        timeout_s: float = 300.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base, self.model, self.batch = base_url.rstrip("/"), model, batch
        self.name, self.dim = f"ollama:{model}", EMBEDDING_DIM
        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout_s, connect=5.0))

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            chunk = [t if t.strip() else " " for t in texts[i : i + self.batch]]
            try:
                r = self.client.post(
                    self.base + "/api/embed", json={"model": self.model, "input": chunk, "truncate": True}
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                raise ModelUnavailable(f"cannot reach Ollama at {self.base} for embeddings") from e
            except httpx.TimeoutException as e:
                raise ModelUnavailable("Ollama embedding request timed out") from e
            if r.status_code == 404:
                raise ModelUnavailable(
                    f"embedding model not found: run `ollama pull {self.model}`", retryable=False
                )
            if r.status_code >= 500:
                raise ModelUnavailable(f"Ollama embedding error {r.status_code}")
            if r.status_code >= 400:
                raise ModelOutputInvalid(f"Ollama rejected the embedding request: {r.text[:200]}")
            try:
                vecs = r.json()["embeddings"]
            except (ValueError, KeyError) as e:
                raise ModelOutputInvalid("unexpected embedding response shape") from e
            if len(vecs) != len(chunk):
                raise ModelOutputInvalid(f"expected {len(chunk)} embeddings, got {len(vecs)}")
            for v in vecs:
                if len(v) != self.dim:
                    raise ModelOutputInvalid(
                        f"embedding model {self.model!r} returns {len(v)}-d vectors but the database is vector({self.dim}). "
                        "Use a 1024-d model (bge-m3) or change the schema."
                    )
                out.append(_l2(np.asarray(v, dtype=np.float32)).tolist())
        return out

    def health(self) -> dict[str, Any]:
        try:
            v = self.embed(["health check"])
            return {"ok": len(v[0]) == self.dim, "detail": "ok"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": str(getattr(e, "detail", e))}


_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Deterministic feature-hashing embedder (word uni/bi-grams + char tri-grams). Offline; lexical-ish quality.

    For tests, CI and the no-model demo. Not a substitute for a real embedding model on real data.
    """

    name = "hashing-1024"
    dim = EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t).tolist() for t in texts]

    def _idx(self, token: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        return h % self.dim, 1.0 if (h >> 63) & 1 else -1.0

    def _one(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        words = _TOKEN.findall((text or "").lower())
        feats: list[tuple[str, float]] = [(w, 1.0) for w in words]
        feats += [(f"{a}_{b}", 0.7) for a, b in zip(words, words[1:], strict=False)]
        for w in words:
            padded = f"^{w}$"
            feats += [("c:" + padded[i : i + 3], 0.25) for i in range(max(len(padded) - 2, 0))]
        for tok, weight in feats:
            i, sign = self._idx(tok)
            v[i] += sign * weight
        return _l2(v)

    def health(self) -> dict[str, Any]:
        return {"ok": True, "detail": "offline hashing embedder"}


def cosine(a: list[float], b: list[float]) -> float:
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (da * db)
