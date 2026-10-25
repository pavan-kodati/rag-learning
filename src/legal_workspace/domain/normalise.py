"""Normalisers: amounts, dates, periods, booleans, names (blueprint §7.5).

All pure functions. The model supplies values *as written*; this module turns them into typed values.
Day-first dates and the lakh/crore system are the Indian conventions.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta

# ----------------------------------------------------------------------------------------------
# number words
# ----------------------------------------------------------------------------------------------
_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "a": 1, "an": 1, "single": 1,
}  # fmt: skip
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {
    "hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "million": 1_000_000, "crore": 10_000_000, "crores": 10_000_000,
}  # fmt: skip
_FILLER = {"and", "only", "rupees", "rupee", "inr", "rs", "of"}


def words_to_number(text: str) -> Decimal | None:
    """'eighteen lakh forty thousand' -> 1840000; 'four' -> 4. None if the text is not a number in words."""
    tokens = [t for t in re.split(r"[\s\-,]+", text.lower().strip()) if t]
    tokens = [t.strip(".()") for t in tokens]
    tokens = [t for t in tokens if t and t not in _FILLER]
    if not tokens:
        return None
    total = Decimal(0)
    current = Decimal(0)
    seen = False
    for tok in tokens:
        if tok in _UNITS:
            current += _UNITS[tok]
            seen = True
        elif tok in _TENS:
            current += _TENS[tok]
            seen = True
        elif tok in _SCALES:
            scale = _SCALES[tok]
            if current == 0:  # a bare scale word ("lakh") with no number in front of it is not an amount
                return None
            if scale == 100:
                current = current * 100
            else:
                total += current * scale
                current = Decimal(0)
            seen = True
        else:
            return None
    return total + current if seen else None


# ----------------------------------------------------------------------------------------------
# amounts
# ----------------------------------------------------------------------------------------------
_CURRENCY = re.compile(r"(?i)(₹|\brs\.?|\binr\b|\brupees?\b|/-)")
_AMOUNT_RE = re.compile(r"(?i)(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr\b|thousand|million|mn\b|k\b)?")
_MULT = {
    "lakh": Decimal(100_000), "lakhs": Decimal(100_000), "lac": Decimal(100_000), "lacs": Decimal(100_000),
    "crore": Decimal(10_000_000), "crores": Decimal(10_000_000), "cr": Decimal(10_000_000),
    "thousand": Decimal(1_000), "k": Decimal(1_000), "million": Decimal(1_000_000), "mn": Decimal(1_000_000),
}  # fmt: skip


def parse_amount(text: str) -> Decimal | None:
    """Rupee amount as Decimal(2dp). Handles ₹/Rs/INR, Indian grouping, lakh/crore and amounts in words."""
    if text is None:
        return None
    s = unicodedata.normalize("NFKC", str(text)).strip()
    if not s:
        return None
    cleaned = _CURRENCY.sub(" ", s)
    m = _AMOUNT_RE.search(cleaned)
    if m:
        digits = m.group(1).replace(",", "")
        try:
            value = Decimal(digits)
        except InvalidOperation:
            return None
        unit = (m.group(2) or "").lower()
        if unit:
            value *= _MULT[unit]
        return value.quantize(Decimal("0.01"))
    # amount in words, e.g. "Rupees Eighteen Lakh Forty Thousand only"
    words = re.sub(r"\(.*?\)", " ", cleaned)
    num = words_to_number(words)
    return num.quantize(Decimal("0.01")) if num is not None else None


def amounts_in(text: str) -> list[Decimal]:
    """Every rupee amount written as digits in `text` (used to check that an extracted value is really there)."""
    out: list[Decimal] = []
    cleaned = _CURRENCY.sub(" ", text or "")
    for m in _AMOUNT_RE.finditer(cleaned):
        try:
            v = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            continue
        unit = (m.group(2) or "").lower()
        out.append((v * _MULT[unit] if unit else v).quantize(Decimal("0.01")))
    return out


def format_inr(amount: Decimal | int | float) -> str:
    """1240000 -> '12,40,000' (Indian digit grouping)."""
    d = Decimal(amount).quantize(Decimal("0.01"))
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    sign = "-" if d < 0 else ""
    return f"{sign}{whole}" + (f".{frac}" if frac != "00" else "")


# ----------------------------------------------------------------------------------------------
# dates
# ----------------------------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}  # fmt: skip
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4}|\d{2})\b")
_DMY = re.compile(rf"(?i)\b(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?{_MONTH_RE}\.?,?\s*(\d{{4}})\b")
_MDY = re.compile(rf"(?i)\b{_MONTH_RE}\.?\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?,?\s*(\d{{4}})\b")
_DATE_PATTERNS = (_ISO, _DMY, _MDY, _NUMERIC)


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _match_to_date(pattern: re.Pattern[str], m: re.Match[str]) -> date | None:
    if pattern is _ISO:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if pattern is _DMY:
        return _mk(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    if pattern is _MDY:
        return _mk(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    if b > 12 >= a:  # clearly month-first (e.g. 03/25/2024)
        a, b = b, a
    return _mk(y, b, a)  # day-first by default (Indian convention)


def find_dates(text: str) -> list[tuple[date, int]]:
    """All dates found in `text` with their start offsets (first match per overlapping span)."""
    found: list[tuple[int, int, date]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text or ""):
            d = _match_to_date(pat, m)
            if d and not any(s <= m.start() < e for s, e, _ in found):
                found.append((m.start(), m.end(), d))
    found.sort()
    return [(d, s) for s, _e, d in found]


def parse_date(text: str | None) -> date | None:
    """First date in `text`: 12.01.2024, 12/01/2024, 12th January, 2024, Jan 12 2024, 2024-01-12."""
    if not text:
        return None
    hits = find_dates(str(text))
    return hits[0][0] if hits else None


def fmt_date(d: date | None) -> str:
    return f"{d.day} {d.strftime('%b %Y')}" if d else "unknown date"


# ----------------------------------------------------------------------------------------------
# periods
# ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Period:
    days: int | None = None
    months: int | None = None
    text: str = ""

    def is_empty(self) -> bool:
        return self.days is None and self.months is None


_PERIOD_RE = re.compile(
    r"(?i)\b(\d+|[a-z\-]+(?:\s+[a-z\-]+)?)\s*(?:\(\s*(\d+)\s*\))?\s*(business\s+days?|working\s+days?|days?|weeks?|fortnights?|months?|years?)\b"
)


def parse_period(text: str | None) -> Period:
    """'within four weeks' -> 28 days; '30 days' -> 30; 'two months' -> 2 months; 'a fortnight' -> 14."""
    if not text:
        return Period(text="")
    s = str(text).strip()
    for m in _PERIOD_RE.finditer(s):
        raw_num, paren, unit = m.group(1), m.group(2), m.group(3).lower()
        n: int | None = None
        if paren:
            n = int(paren)
        elif raw_num.isdigit():
            n = int(raw_num)
        else:
            # take the last 1-2 words (e.g. "within four" -> "four", "forty five")
            words = raw_num.lower().replace("-", " ").split()
            for k in (2, 1):
                if len(words) >= k:
                    num = words_to_number(" ".join(words[-k:]))
                    if num is not None:
                        n = int(num)
                        break
        if n is None:
            continue
        unit = unit.split()[-1] if "day" in unit else unit
        if unit.startswith("fortnight"):
            return Period(days=14 * n, text=s)
        if unit.startswith("week"):
            return Period(days=7 * n, text=s)
        if unit.startswith("day"):
            return Period(days=n, text=s)
        if unit.startswith("month"):
            return Period(months=n, text=s)
        if unit.startswith("year"):
            return Period(months=12 * n, text=s)
    return Period(text=s)


def add_period(trigger: date, period: Period) -> date | None:
    if period.is_empty():
        return None
    d = trigger
    if period.months:
        d = d + relativedelta(months=period.months)
    if period.days:
        d = d + timedelta(days=period.days)
    return d


# ----------------------------------------------------------------------------------------------
# booleans, names, slugs
# ----------------------------------------------------------------------------------------------
_TRUE_WORDS = {"true", "yes", "y", "1", "received", "served", "admitted", "asserted", "sought", "allowed",
               "complied", "accepted", "completed", "paid", "delivered", "present", "exists"}  # fmt: skip
_FALSE_WORDS = {"false", "no", "n", "0", "denied", "refused", "rejected", "absent", "none", "nil"}


_NEG_TOKENS = {"not", "never", "no", "nor", "without", "neither", "didn", "wasn", "hasn", "haven", "isn"}


def parse_bool(text: str | None) -> bool | None:
    """'received' -> True; 'not received' / 'never received' / 'denied' -> False; unreadable -> None."""
    if text is None:
        return None
    s = re.sub(r"[^a-z0-9 ]", " ", str(text).lower()).strip()
    toks = s.split()
    if not toks:
        return None
    if any(t in _NEG_TOKENS or t in _FALSE_WORDS for t in toks):
        return False
    if any(t in _TRUE_WORDS for t in toks):
        return True
    return None


_NAME_SUBS = (
    (r"\bltd\b", "limited"), (r"\bpvt\b", "private"), (r"\bco\b", "company"), (r"\binc\b", "incorporated"),
    (r"\bcorp\b", "corporation"), (r"\bllp\b", "llp"), (r"\band\b", "and"),
)  # fmt: skip


def normalise_name(name: str) -> str:
    """'Kestrel Ltd.' / 'KESTREL LIMITED' -> 'kestrel limited'."""
    s = unicodedata.normalize("NFKC", name or "").lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    for pat, rep in _NAME_SUBS:
        s = re.sub(pat, rep, s)
    s = re.sub(r"^m s\b", " ", s.strip())  # "M/s." prefix
    return " ".join(s.split())


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


_ID_RE = re.compile(r"(?i)\b([a-z]{0,6}[-/#]?\d[\w\-/]*)")


def extract_identifier(text: str) -> str | None:
    """'Invoice No. INV-014 dated ...' -> 'inv-014'. None when no identifier-like token exists."""
    stripped = text or ""
    for pat in _DATE_PATTERNS:  # dates are not identifiers
        stripped = pat.sub(" ", stripped)
    for m in _ID_RE.finditer(stripped):
        token = m.group(1)
        if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", token):  # a date, not an identifier
            continue
        return slugify(token)
    return None
