"""Fact keys (blueprint §8.2): built by code from what a fact is *about*, never by the model."""

from __future__ import annotations

from .normalise import slugify
from .slots import SUBJECT_SLOTS, slot_def

KEY_SEP = "/"


class KeyError_(ValueError):
    """Raised when a key cannot be built from the given parts."""


def build_key(subject_type: str, subject_ref: str, slot: str) -> str:
    """`<subject_type>/<subject_ref>/<slot>`, lowercase. Example: contract/msa-2023/delivery_date."""
    st = (subject_type or "").strip().lower()
    if st.upper() not in SUBJECT_SLOTS:
        raise KeyError_(f"unknown subject type {subject_type!r}")
    ref = slugify(subject_ref or "")
    if not ref:
        raise KeyError_("empty subject reference")
    sl = (slot or "").strip().lower()
    if not slot_def(st, sl):
        raise KeyError_(f"slot {slot!r} is not valid for subject type {subject_type!r}")
    return KEY_SEP.join((st, ref, sl))


def split_key(key: str) -> tuple[str, str, str]:
    parts = key.split(KEY_SEP)
    if len(parts) != 3 or not all(parts):
        raise KeyError_(f"malformed fact key {key!r}")
    return parts[0], parts[1], parts[2]


def subject_of(key: str) -> str:
    st, ref, _ = split_key(key)
    return f"{st}/{ref}"
