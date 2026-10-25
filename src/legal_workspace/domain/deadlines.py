"""Court deadlines (blueprint §8.6). Due dates are computed in code, never by the model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .normalise import Period, add_period, find_dates, parse_period


class DueStatus(StrEnum):
    COMPLIED = "COMPLIED"
    OVERDUE = "OVERDUE"
    PENDING = "PENDING"
    NO_DATE = "NO_DATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class DueResult:
    due_date: date | None
    period: Period
    trigger_date: date | None
    weekend: bool
    needs_review: bool
    reason: str


_FROM_RECEIPT = re.compile(
    r"(?i)\b(from|after|of)\s+(the\s+)?(date\s+of\s+)?(receipt|service|communication|being\s+served|notice)\b"
)
_FROM_ORDER = re.compile(r"(?i)\b(from\s+(today|the\s+date\s+of\s+(this|the)\s+order)|today|hereof)\b")


def compute_due(
    value_text: str | None, order_date: date | None, receipt_date: date | None = None
) -> DueResult:
    """Turn 'within four weeks from today' / '10 October 2025' into a due date.

    Trigger date: the order date by default; the receipt date when the period runs 'from receipt of the copy'
    (if that date is unknown, no date is computed and the direction goes to the review queue).
    """
    text = (value_text or "").strip()
    if not text or text.lower() in {
        "unspecified",
        "none",
        "n/a",
        "na",
        "not specified",
        "no period specified",
    }:
        return DueResult(None, Period(text=text), order_date, False, False, "no period or date stated")

    period = parse_period(text)
    explicit = [d for d, _ in find_dates(text)]
    if explicit and period.is_empty():
        d = explicit[0]
        return DueResult(d, period, None, d.weekday() >= 5, False, "date stated in the order")

    if period.is_empty():
        return DueResult(
            None, period, order_date, False, True, f"could not read a period or date from {text!r}"
        )

    from_receipt = bool(_FROM_RECEIPT.search(text)) and not _FROM_ORDER.search(text)
    trigger = receipt_date if from_receipt else order_date
    if trigger is None:
        why = (
            "period runs from receipt of the copy and the receipt date is unknown"
            if from_receipt
            else "order date unknown"
        )
        return DueResult(None, period, None, False, True, why)

    due = add_period(trigger, period)
    assert due is not None
    return DueResult(
        due, period, trigger, due.weekday() >= 5, False, "computed from trigger date plus period"
    )


def status_of(due: date | None, compliance: str, today: date) -> DueStatus:
    """Overdue is computed at query time: the due date has passed and the direction is still pending."""
    if compliance == "COMPLIED":
        return DueStatus.COMPLIED
    if compliance == "NOT_APPLICABLE":
        return DueStatus.NOT_APPLICABLE
    if due is None:
        return DueStatus.NO_DATE
    return DueStatus.OVERDUE if due < today else DueStatus.PENDING
