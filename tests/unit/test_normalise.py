from datetime import date
from decimal import Decimal

import pytest

from legal_workspace.domain.normalise import (
    Period,
    add_period,
    extract_identifier,
    find_dates,
    format_inr,
    normalise_name,
    parse_amount,
    parse_bool,
    parse_date,
    parse_period,
    slugify,
    words_to_number,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("₹18,40,000", "1840000.00"),
        ("Rs. 18.4 lakh", "1840000.00"),
        ("Rs.18,40,000/-", "1840000.00"),
        ("INR 1.2 crore", "12000000.00"),
        ("INR 12,40,000", "1240000.00"),
        ("Rs 6,00,000", "600000.00"),
        ("1,240,000.50", "1240000.50"),
        ("₹ 0", "0.00"),
        ("5k", "5000.00"),
        ("2 lakhs", "200000.00"),
        ("Rupees Eighteen Lakh Forty Thousand only", "1840000.00"),
        ("Rs. 18,40,000 (Rupees Eighteen Lakh Forty Thousand only)", "1840000.00"),
        ("twelve lakh", "1200000.00"),
    ],
)
def test_parse_amount_ok(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "   ", None, "abc", "no amount here", "Rupees", "₹", "lakh"])
def test_parse_amount_rejects_garbage(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    "amount, expected",
    [
        (1840000, "18,40,000"),
        (1240000, "12,40,000"),
        (600000, "6,00,000"),
        (999, "999"),
        (1000, "1,000"),
        (12000000, "1,20,00,000"),
        ("1234.5", "1,234.50"),
        (-1500000, "-15,00,000"),
        (0, "0"),
    ],
)
def test_format_inr(amount, expected):
    assert format_inr(amount) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("12.01.2024", date(2024, 1, 12)),
        ("12/01/2024", date(2024, 1, 12)),  # day-first by default
        ("12-01-2024", date(2024, 1, 12)),
        ("12th January, 2024", date(2024, 1, 12)),
        ("12 Jan 2024", date(2024, 1, 12)),
        ("January 12, 2024", date(2024, 1, 12)),
        ("Sept 5, 2024", date(2024, 9, 5)),
        ("2024-01-12", date(2024, 1, 12)),
        ("5th day of February 2025", date(2025, 2, 5)),
        ("12.01.24", date(2024, 1, 12)),
        ("03/25/2024", date(2024, 3, 25)),  # clearly month-first
        ("Dated this 3rd March, 2025 at Delhi", date(2025, 3, 3)),
        ("29 February 2024", date(2024, 2, 29)),
    ],
)
def test_parse_date_ok(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    "text", ["", None, "no date", "31.02.2024", "31 February 2024", "13/13/2024", "2024-13-45"]
)
def test_parse_date_rejects(text):
    assert parse_date(text) is None


def test_find_dates_returns_all_in_order():
    hits = find_dates("Notice dated 5 February 2025 was replied on 20.02.2025.")
    assert [d for d, _ in hits] == [date(2025, 2, 5), date(2025, 2, 20)]


@pytest.mark.parametrize(
    "text, days, months",
    [
        ("within four weeks", 28, None),
        ("within four weeks from today", 28, None),
        ("30 days", 30, None),
        ("thirty (30) days", 30, None),
        ("forty five days", 45, None),
        ("within 4 weeks of receipt", 28, None),
        ("a fortnight", 14, None),
        ("two months", None, 2),
        ("one year", None, 12),
        ("15 working days", 15, None),
        ("within a week", 7, None),
    ],
)
def test_parse_period(text, days, months):
    p = parse_period(text)
    assert (p.days, p.months) == (days, months)


@pytest.mark.parametrize("text", ["", None, "forthwith", "soon", "next hearing", "in due course"])
def test_parse_period_empty(text):
    assert parse_period(text).is_empty()


def test_add_period_days_and_months():
    assert add_period(date(2025, 9, 12), Period(days=28)) == date(2025, 10, 10)  # blueprint worked example
    assert add_period(date(2025, 1, 31), Period(months=1)) == date(2025, 2, 28)  # month-end clamps
    assert add_period(date(2025, 1, 1), Period()) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("received", True),
        ("Yes", True),
        ("served", True),
        ("not received", False),
        ("never received", False),
        ("denied", False),
        ("no", False),
        ("was never served", False),
        ("was served", True),
        ("true", True),
        ("false", False),
        ("The notice was not received by us", False),
    ],
)
def test_parse_bool(text, expected):
    assert parse_bool(text) is expected


@pytest.mark.parametrize("text", ["", None, "maybe", "perhaps later", "???"])
def test_parse_bool_unreadable(text):
    assert parse_bool(text) is None


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Kestrel Ltd.", "kestrel limited"),
        ("KESTREL LIMITED", "kestrel limited"),
        ("M/s. Kestrel Pvt. Ltd.", "kestrel private limited"),
        ("Vardhan Infotech Pvt Ltd", "vardhan infotech private limited"),
        ("  A & B  Co. ", "a and b company"),
        ("", ""),
    ],
)
def test_normalise_name(name, expected):
    assert normalise_name(name) == expected


def test_slugify_and_identifier():
    assert slugify("Master Services Agreement!") == "master-services-agreement"
    assert slugify("INV/2024/014") == "inv-2024-014"
    assert slugify("") == ""
    assert extract_identifier("Invoice No. INV-014 dated 5 March 2025") == "inv-014"
    assert extract_identifier("Invoice INV/2024/014") == "inv-2024-014"
    assert extract_identifier("no digits here") is None
    assert extract_identifier("dated 12.01.2024 only") is None


def test_words_to_number():
    assert words_to_number("four") == 4
    assert words_to_number("one hundred and five") == 105
    assert words_to_number("two crore") == 20_000_000
    assert words_to_number("banana") is None
    assert words_to_number("") is None
