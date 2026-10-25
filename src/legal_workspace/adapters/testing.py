"""Test doubles (also handy for local experiments)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Handler = Callable[[str, str, str, dict[str, Any], dict[str, Any]], dict[str, Any]]


class ScriptedLLM:
    """An LLM whose answers come from a function. Records every call for assertions."""

    supports_generation = True

    def __init__(self, handler: Handler, *, generation: bool = True) -> None:
        self.handler = handler
        self.supports_generation = generation
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, *, role, system, user, schema, task="", meta=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.calls.append({"role": role, "system": system, "user": user, "task": task, "meta": meta or {}})
        return self.handler(task, system, user, schema, meta or {})

    def health(self) -> dict[str, Any]:
        return {"ok": True, "detail": "scripted"}

    def model_names(self) -> dict[str, str]:
        return {"main": "scripted", "fast": "scripted"}
