"""Scripted checker for the golden question set (blueprint §18.2): facts, text, citations, forbidden claims, intent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from legal_workspace.db.pool import Conn

from ..memory import queries


@dataclass
class QuestionResult:
    id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    answer: dict[str, Any] | None = None


def _norm(s: str) -> str:
    s = (s or "").lower().replace("₹", "").replace("rs.", "").replace("rs ", "")
    return " ".join(s.split())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def sentences_text(answer: dict[str, Any]) -> str:
    return "\n".join(
        s["text"]
        for s in answer.get("answer_sentences", [])
        if s.get("status") != "INFO" or s.get("kind") != "decline"
    )


def _value_matches(fact: dict[str, Any], expected: str) -> bool:
    exp = expected.strip()
    try:
        if fact["value_amount"] is not None:
            return Decimal(exp) == fact["value_amount"]
    except InvalidOperation:
        return False
    if fact.get("value_number") is not None:
        digits = re.sub(r"\D", "", exp)
        return digits == str(fact["value_number"])
    if fact["value_date"] is not None:
        return exp == fact["value_date"].isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", exp) else False
    if fact["value_bool"] is not None:
        return exp.lower() == str(fact["value_bool"]).lower()
    return _norm(fact["value_text"] or "") == _norm(exp)


def check_question(conn: Conn, matter_id: str, q: dict[str, Any], answer: dict[str, Any]) -> QuestionResult:
    fails: list[str] = []
    text = sentences_text(answer)
    as_of = answer["as_of_batch_seq"]
    if q.get("intent") and q["intent"] not in answer.get("intents", []):
        fails.append(f"intent {q['intent']} not routed (got {answer.get('intents')})")
    if q.get("not_found"):
        real = [s for s in answer.get("answer_sentences", []) if s.get("status") == "VERIFIED"]
        if real or not answer.get("not_found"):
            fails.append("expected a 'not found' answer")
        return QuestionResult(q["id"], not fails, fails, answer)
    current = {f["fact_key"]: f for f in queries.facts_as_of(conn, matter_id, as_of)}
    for spec in q.get("expected_facts", []):
        key, _, val = spec.partition("=")
        f = current.get(key.strip())
        if f is None:
            fails.append(f"fact {key.strip()} is not current in the case memory")
        elif not _value_matches(f, val):
            fails.append(f"fact {key.strip()} has the wrong value (expected {val.strip()})")
    for exp in q.get("expected_text", []):
        if _norm(exp) not in _norm(text) and (not _digits(exp) or _digits(exp) not in _digits(text)):
            fails.append(f"answer does not mention {exp!r}")
    for bad in q.get("must_not_say", []):
        if _norm(bad) in _norm(text):
            fails.append(f"answer says {bad!r}")
    cites = [c for s in answer.get("answer_sentences", []) for c in s.get("citations", [])]
    for want in q.get("expected_citations", []):
        if not any(
            want["document"].lower() in (c.get("document_title") or "").lower()
            and c.get("page") == want["page"]
            for c in cites
        ):
            fails.append(f"missing citation {want['document']} p.{want['page']}")
    return QuestionResult(q["id"], not fails, fails, answer)


def check_planted(report: dict[str, Any], planted: list[dict[str, Any]], batch: int) -> list[str]:
    """Every planted change of this batch must appear in the batch's What-Changed report with the right rule."""
    found = {(c["change_type"], c["rule_id"], c["fact_key"]) for c in report["changes"]}
    # NEW rows that were grouped under another change are not listed; accept the change they caused
    return [
        f"{p['change_type']} {p['rule_id']} {p['fact_key']}"
        for p in planted
        if p["batch"] == batch and (p["change_type"], p["rule_id"], p["fact_key"]) not in found
    ]


def today_for(matter_dates: list[date] | None = None) -> date:
    return max(matter_dates) if matter_dates else date.today()
