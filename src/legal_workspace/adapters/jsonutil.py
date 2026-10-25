"""Lenient JSON extraction: models sometimes wrap JSON in fences, prose or <think> blocks."""

from __future__ import annotations

import json
import re
from typing import Any

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def strip_noise(text: str) -> str:
    text = _THINK.sub("", text or "")
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    return _FENCE.sub("", text.strip()).strip()


def _first_balanced(text: str) -> str | None:
    """The first balanced {...} or [...] block, respecting strings."""
    start = next((i for i, ch in enumerate(text) if ch in "{["), None)
    if start is None:
        return None
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def loads_lenient(text: str) -> Any:
    """Parse JSON from model output. Raises ValueError if nothing usable is found."""
    cleaned = strip_noise(text)
    if not cleaned:
        raise ValueError("empty model output")
    candidates = [cleaned]
    block = _first_balanced(cleaned)
    if block and block != cleaned:
        candidates.append(block)
    for cand in candidates:
        for attempt in (cand, _TRAILING_COMMA.sub(r"\1", cand)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no valid JSON in model output: {cleaned[:120]!r}")
