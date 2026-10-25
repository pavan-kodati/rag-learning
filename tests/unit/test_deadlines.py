from datetime import date

import pytest

from legal_workspace.domain.deadlines import DueStatus, compute_due, status_of

ORDER = date(2025, 9, 12)


def test_blueprint_worked_example():
    r = compute_due("within four weeks from today", ORDER)
    assert r.due_date == date(2025, 10, 10)
    assert r.period.days == 28 and r.trigger_date == ORDER and not r.needs_review


def test_explicit_date_wins():
    r = compute_due("on or before 10 October 2025", ORDER)
    assert r.due_date == date(2025, 10, 10) and not r.needs_review


def test_weekend_flag():
    assert compute_due("within 15 days", date(2025, 9, 12)).weekend is True  # 27 Sep 2025 is a Saturday
    assert compute_due("within 14 days", date(2025, 9, 12)).weekend is False  # 26 Sep 2025 is a Friday


def test_months_period():
    assert compute_due("within two months", date(2025, 9, 12)).due_date == date(2025, 11, 12)


def test_period_from_receipt_without_receipt_date_goes_to_review():
    r = compute_due("within four weeks from receipt of a copy of this order", ORDER)
    assert r.due_date is None and r.needs_review and "receipt" in r.reason


def test_period_from_receipt_with_receipt_date():
    r = compute_due(
        "within four weeks from receipt of a copy of this order", ORDER, receipt_date=date(2025, 9, 20)
    )
    assert r.due_date == date(2025, 10, 18) and r.trigger_date == date(2025, 9, 20)


@pytest.mark.parametrize("text", ["", None, "unspecified", "no period specified", "N/A"])
def test_no_period_is_not_an_error(text):
    r = compute_due(text, ORDER)
    assert r.due_date is None and not r.needs_review


def test_unreadable_text_needs_review():
    r = compute_due("at the earliest convenience of the parties", ORDER)
    assert r.due_date is None and r.needs_review


def test_unknown_order_date():
    r = compute_due("within 30 days", None)
    assert r.due_date is None and r.needs_review


@pytest.mark.parametrize(
    "due, compliance, today, expected",
    [
        (date(2025, 10, 10), "PENDING", date(2025, 10, 9), DueStatus.PENDING),
        (date(2025, 10, 10), "PENDING", date(2025, 10, 10), DueStatus.PENDING),  # due today is not overdue
        (date(2025, 10, 10), "PENDING", date(2025, 10, 11), DueStatus.OVERDUE),
        (date(2025, 10, 10), "COMPLIED", date(2026, 1, 1), DueStatus.COMPLIED),
        (None, "PENDING", date(2025, 10, 11), DueStatus.NO_DATE),
        (date(2025, 10, 10), "NOT_APPLICABLE", date(2026, 1, 1), DueStatus.NOT_APPLICABLE),
    ],
)
def test_status(due, compliance, today, expected):
    assert status_of(due, compliance, today) == expected
