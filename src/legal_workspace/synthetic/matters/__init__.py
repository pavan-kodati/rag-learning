"""Registry of synthetic matters."""

from __future__ import annotations

import importlib

from ..spec import Matter

_MODULES = {"M1": "m1", "M2": "m2", "M3": "m3", "M4": "m4"}


def load(matter_id: str) -> Matter:
    return importlib.import_module(f"{__name__}.{_MODULES[matter_id]}").MATTER


def available() -> list[str]:
    out = []
    for mid, mod in _MODULES.items():
        try:
            importlib.import_module(f"{__name__}.{mod}")
            out.append(mid)
        except ModuleNotFoundError:
            continue
    return out
