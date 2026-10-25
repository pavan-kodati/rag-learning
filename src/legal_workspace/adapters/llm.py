"""LLM port and adapters (blueprint §12). Temperature 0, thinking off, JSON-schema constrained output."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from ..errors import ModelOutputInvalid, ModelUnavailable
from .jsonutil import loads_lenient

log = logging.getLogger(__name__)
Role = Literal["main", "fast"]


class LLM(Protocol):
    """Everything the product needs from a language model."""

    supports_generation: bool

    def chat_json(
        self, *, role: Role, system: str, user: str, schema: dict[str, Any], task: str = "",
        meta: dict[str, Any] | None = None, max_tokens: int = 2048,
    ) -> dict[str, Any]: ...  # fmt: skip

    def health(self) -> dict[str, Any]: ...

    def model_names(self) -> dict[str, str]: ...


class RawBackend(Protocol):
    """A single HTTP/model call returning raw text. Wrapped by `ResilientLLM`."""

    def call(self, *, role: Role, system: str, user: str, schema: dict[str, Any], max_tokens: int) -> str: ...

    def health(self) -> dict[str, Any]: ...

    def model_names(self) -> dict[str, str]: ...


# ------------------------------------------------------------------------------------- Ollama
class OllamaBackend:
    def __init__(
        self, base_url: str, main_model: str, fast_model: str, ctx_main: int, ctx_fast: int, timeout_s: float = 600.0,
        client: httpx.Client | None = None,
    ) -> None:  # fmt: skip
        self.base = base_url.rstrip("/")
        self.models = {"main": main_model, "fast": fast_model}
        self.ctx = {"main": ctx_main, "fast": ctx_fast}
        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout_s, connect=5.0))

    def call(self, *, role: Role, system: str, user: str, schema: dict[str, Any], max_tokens: int) -> str:
        body = {
            "model": self.models[role],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": schema,
            "think": False,
            "options": {"temperature": 0, "num_ctx": self.ctx[role], "num_predict": max_tokens},
        }
        data = self._post("/api/chat", body)
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise ModelOutputInvalid("Ollama response has no message content")
        return content

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self.client.post(self.base + path, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ModelUnavailable(
                f"cannot reach Ollama at {self.base}: is it running? (`ollama serve`)"
            ) from e
        except httpx.TimeoutException as e:
            raise ModelUnavailable(f"Ollama timed out after {self.client.timeout.read}s") from e
        if r.status_code == 404:
            raise ModelUnavailable(
                f"model not found on Ollama: run `ollama pull {body.get('model')}`", retryable=False
            )
        if r.status_code == 400 and "think" in r.text.lower() and body.get("think") is False:
            body = {k: v for k, v in body.items() if k != "think"}  # older server / non-thinking model
            return self._post(path, body)
        if r.status_code >= 500:
            raise ModelUnavailable(f"Ollama error {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise ModelOutputInvalid(f"Ollama rejected the request ({r.status_code}): {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise ModelOutputInvalid("Ollama returned a non-JSON body") from e

    def health(self) -> dict[str, Any]:
        try:
            r = self.client.get(self.base + "/api/tags", timeout=5.0)
            r.raise_for_status()
            have = {m["name"] for m in r.json().get("models", [])}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"Ollama unreachable at {self.base}: {e.__class__.__name__}"}

        def present(name: str) -> bool:
            return name in have or f"{name}:latest" in have

        missing = [m for m in {self.models["main"], self.models["fast"]} if not present(m)]
        return {
            "ok": not missing,
            "detail": f"missing models: {missing}" if missing else "ok",
            "models": sorted(have),
        }

    def model_names(self) -> dict[str, str]:
        return dict(self.models)


# ------------------------------------------------------------------------------ OpenAI-compatible
class OpenAICompatBackend:
    """vLLM / llama.cpp server / LM Studio: /v1/chat/completions with JSON-schema output."""

    def __init__(
        self, base_url: str, api_key: str, main_model: str, fast_model: str, timeout_s: float = 600.0,
        client: httpx.Client | None = None,
    ) -> None:  # fmt: skip
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.models = {"main": main_model, "fast": fast_model}
        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout_s, connect=5.0))

    def call(self, *, role: Role, system: str, user: str, schema: dict[str, Any], max_tokens: int) -> str:
        body = {
            "model": self.models[role],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            r = self.client.post(self.base + "/chat/completions", json=body, headers=self.headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ModelUnavailable(f"cannot reach the model server at {self.base}") from e
        except httpx.TimeoutException as e:
            raise ModelUnavailable("model server timed out") from e
        if r.status_code in (401, 403):
            raise ModelUnavailable("model server rejected the API key", retryable=False, auth=True)
        if r.status_code == 404:
            raise ModelUnavailable(f"model {body['model']!r} not served at {self.base}", retryable=False)
        if r.status_code >= 500:
            raise ModelUnavailable(f"model server error {r.status_code}")
        if r.status_code >= 400:
            raise ModelOutputInvalid(f"model server rejected the request ({r.status_code}): {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ModelOutputInvalid("unexpected response shape from the model server") from e

    def health(self) -> dict[str, Any]:
        try:
            r = self.client.get(self.base + "/models", headers=self.headers, timeout=5.0)
            r.raise_for_status()
            ids = {m["id"] for m in r.json().get("data", [])}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"model server unreachable: {e.__class__.__name__}"}
        missing = [m for m in set(self.models.values()) if m not in ids]
        return {"ok": not missing, "detail": f"missing models: {missing}" if missing else "ok"}

    def model_names(self) -> dict[str, str]:
        return dict(self.models)


# --------------------------------------------------------------------------------------- resilience
class CircuitBreaker:
    """Opens after `threshold` consecutive failures; half-opens after `cooldown_s`."""

    def __init__(
        self, threshold: int = 4, cooldown_s: float = 20.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.threshold, self.cooldown_s, self.clock = threshold, cooldown_s, clock
        self._fails = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            return self.clock() - self._opened_at >= self.cooldown_s  # half-open: let one probe through

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            return "half-open" if self.clock() - self._opened_at >= self.cooldown_s else "open"

    def success(self) -> None:
        with self._lock:
            self._fails, self._opened_at = 0, None

    def failure(self) -> None:
        with self._lock:
            self._fails += 1
            if self._fails >= self.threshold:
                self._opened_at = self.clock()


class ResilientLLM:
    """Retries, circuit breaker, lenient JSON parsing and main -> fast standby fallback around any raw backend."""

    supports_generation = True

    def __init__(
        self, backend: RawBackend, *, retries: int = 2, backoff_s: float = 0.5, breaker: CircuitBreaker | None = None,
        fallback_to_fast: bool = True, sleep: Callable[[float], None] = time.sleep,
    ) -> None:  # fmt: skip
        self.backend = backend
        self.retries = retries
        self.backoff_s = backoff_s
        self.breaker = breaker or CircuitBreaker()
        self.fallback_to_fast = fallback_to_fast
        self._sleep = sleep
        self.last_role_used: Role | None = None

    def chat_json(
        self, *, role: Role, system: str, user: str, schema: dict[str, Any], task: str = "",
        meta: dict[str, Any] | None = None, max_tokens: int = 2048,
    ) -> dict[str, Any]:  # fmt: skip
        try:
            out = self._with_retries(role, system, user, schema, max_tokens)
            self.last_role_used = role
            return out
        except ModelUnavailable as e:
            if role == "main" and self.fallback_to_fast and not e.extra.get("auth"):
                log.warning("main model unavailable (%s); falling back to the fast model", e.detail)
                out = self._with_retries("fast", system, user, schema, max_tokens)
                self.last_role_used = "fast"
                return out
            raise

    def _with_retries(
        self, role: Role, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        last: Exception | None = None
        nudge = ""
        for attempt in range(self.retries + 1):
            if not self.breaker.allow():
                raise ModelUnavailable("the model is temporarily unavailable (circuit open)")
            try:
                text = self.backend.call(
                    role=role, system=system, user=user + nudge, schema=schema, max_tokens=max_tokens
                )
                try:
                    parsed = loads_lenient(text)
                except ValueError as e:
                    self.breaker.success()  # the server is fine; the output was not
                    last = ModelOutputInvalid(str(e))
                    nudge = "\n\nReturn ONLY a valid JSON object that matches the schema. No prose."
                    continue
                if not isinstance(parsed, dict):
                    if isinstance(parsed, list):
                        parsed = {"items": parsed}
                    else:
                        last = ModelOutputInvalid("model returned JSON that is not an object")
                        continue
                self.breaker.success()
                return parsed
            except ModelUnavailable as e:
                self.breaker.failure()
                last = e
                if not e.extra.get("retryable", True):
                    raise
                if attempt < self.retries:
                    self._sleep(self.backoff_s * (2**attempt) * (0.5 + random.random() / 2))  # noqa: S311
        assert last is not None
        raise last

    def health(self) -> dict[str, Any]:
        h = self.backend.health()
        h["breaker"] = self.breaker.state
        return h

    def model_names(self) -> dict[str, str]:
        return self.backend.model_names()


# ------------------------------------------------------------------------------------------ fixture
class FixtureLLM:
    """Replays recorded classification / extraction output for the bundled synthetic matters.

    Demo and CI mode: no model needed. It cannot read *new* documents; unknown documents fail loudly so nobody
    mistakes a replay for a real model run. Free-text generation is not supported (`supports_generation=False`):
    answers fall back to extractive mode.
    """

    supports_generation = False

    def __init__(
        self, fixtures_dir: Path | None = None, records: dict[str, dict[str, Any]] | None = None
    ) -> None:
        self.dir = Path(fixtures_dir) if fixtures_dir else None
        self._data: dict[str, dict[str, Any]] | None = (
            {"classify": dict(records.get("classify", {})), "extract": dict(records.get("extract", {}))}
            if records is not None
            else None
        )

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._data is None:
            self._data = {"classify": {}, "extract": {}}
            for f in sorted(self.dir.glob("*.json")) if self.dir else []:
                try:
                    blob = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    log.warning("ignoring unreadable fixture file %s", f)
                    continue
                for task in ("classify", "extract"):
                    self._data[task].update(blob.get(task, {}))
        return self._data

    def chat_json(
        self, *, role: Role, system: str, user: str, schema: dict[str, Any], task: str = "",
        meta: dict[str, Any] | None = None, max_tokens: int = 2048,
    ) -> dict[str, Any]:  # fmt: skip
        key = (meta or {}).get("fixture_key")
        if task in ("classify", "extract"):
            window = (meta or {}).get("window")
            data = self._load()[task]
            alt = (meta or {}).get("fixture_alt")
            key = (
                key if key in data else (alt if alt in data else key)
            )  # content hash first, then the file name
            if key and key in data:
                rec = data[key]
                if (
                    task == "extract"
                ):  # the recording covers the whole document: return it for the first window only
                    return {"items": rec.get("items", [])} if not window else {"items": []}
                return rec
            raise ModelUnavailable(
                f"fixture mode has no recorded {task} output for this document (key={key}). "
                "Use a real model (LLM_PROVIDER=ollama) for documents outside the bundled synthetic matters.",
                retryable=False,
            )
        if task == "route":
            return {"intents": ["FACTUAL_QA"], "party": None, "document": None}
        raise ModelUnavailable(f"fixture mode does not support task {task!r}", retryable=False)

    def health(self) -> dict[str, Any]:
        n = len(self._load()["extract"])
        return {"ok": n > 0, "detail": f"{n} recorded document extractions" if n else "no fixtures found"}

    def model_names(self) -> dict[str, str]:
        return {"main": "fixture", "fast": "fixture"}
