"""Subject resolution: turn "the Agreement dated 12.01.2023" into `msa-2023`.

Blueprint §8.2: contract references are resolved through a registry of the matter's contracts; an ambiguous
reference goes to the review queue. The same idea is applied to notices, invoices and payments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .normalise import extract_identifier, find_dates, normalise_name, slugify
from .types import DocType

_STOP = {"the", "a", "an"}
_SELF_REF = re.compile(
    r"(?i)^\s*$|\b(this|the\s+said|the\s+present|aforesaid)\s+(agreement|contract|amendment|notice|document|order)\b|\bhereof\b|\bherein\b"
)


@dataclass
class Resolution:
    ref: str | None
    ambiguous: bool = False
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.ref is not None and not self.ambiguous


@dataclass
class ContractRef:
    contract_id: str
    title: str
    doc_date: date | None
    aliases: set[str] = field(default_factory=set)


def _initials(title: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", title) if w.lower() not in _STOP]
    return "".join(w[0].lower() for w in words)


def contract_id_for(title: str, doc_type: DocType, doc_date: date | None) -> str:
    """'Master Services Agreement' dated 2023 -> 'msa-2023'; 'Purchase Order No. PO-4471' -> 'po-4471'."""
    if doc_type == DocType.PURCHASE_ORDER:
        ident = extract_identifier(title)
        if ident:
            return ident if ident.startswith("po") else f"po-{ident}"
    ini = _initials(title)
    base = ini[:8] if len(ini) >= 3 else (slugify(" ".join(title.split()[:2])) or "contract")[:40]
    return f"{base}-{doc_date.year}" if doc_date else base


def make_contract_ref(title: str, doc_type: DocType, doc_date: date | None) -> ContractRef:
    cid = contract_id_for(title, doc_type, doc_date)
    aliases = {cid, slugify(title), normalise_name(title), _initials(title)}
    aliases.discard("")
    return ContractRef(cid, title, doc_date, aliases)


def resolve_contract(
    ref_text: str | None, registry: list[ContractRef], default_id: str | None = None
) -> Resolution:
    """Resolve a contract reference as written to a contract id from the matter's registry."""
    text = (ref_text or "").strip()
    if _SELF_REF.search(text) and default_id:
        return Resolution(default_id)
    if not registry:
        return Resolution(None, True, "no contract registered in this matter yet")
    norm = normalise_name(text)
    slug = slugify(text)
    candidates: list[ContractRef] = []
    for c in registry:
        hit = False
        for alias in c.aliases:
            if not alias:
                continue
            if len(alias) <= 4:  # initials such as "msa": whole-word match only
                if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", norm):
                    hit = True
            elif alias in slug or alias in norm:
                hit = True
        if hit:
            candidates.append(c)
    dates = [d for d, _ in find_dates(text)]
    if dates:
        dated = [c for c in registry if c.doc_date in dates]
        if len(dated) == 1:
            return Resolution(dated[0].contract_id)
        if dated and candidates:
            both = [c for c in candidates if c in dated]
            if len(both) == 1:
                return Resolution(both[0].contract_id)
    if len(candidates) == 1:
        return Resolution(candidates[0].contract_id)
    if default_id and not candidates:
        return Resolution(default_id)
    if len(registry) == 1 and not candidates:
        return Resolution(registry[0].contract_id)
    if len(candidates) > 1:
        return Resolution(None, True, f"reference {text!r} matches several contracts")
    return Resolution(None, True, f"reference {text!r} matches no registered contract")


def resolve_milestone(
    ref_text: str | None, registry: list[ContractRef], default_contract: str | None
) -> Resolution:
    text = ref_text or ""
    res = resolve_contract(text, registry, default_contract)
    num = re.search(r"(?i)(?:milestone|m|stage|phase)\s*(?:no\.?\s*)?(\d+)", text) or re.search(
        r"\b(\d+)\b", text
    )
    if res.ok and num:
        return Resolution(f"{res.ref}-m{int(num.group(1))}")
    if res.ok:
        return Resolution(None, True, f"milestone number not found in {text!r}")
    return res


def resolve_invoice(ref_text: str | None) -> Resolution:
    ident = extract_identifier(ref_text or "")
    if ident:
        return Resolution(ident)
    slug = slugify(ref_text or "")
    return Resolution(slug or None, ambiguous=not slug, reason="" if slug else "empty invoice reference")


def resolve_payment(ref_text: str | None, date_hint: date | None) -> Resolution:
    """Payment reference (UTR / cheque no.) if it looks like one, else the payment date."""
    ident = extract_identifier(ref_text or "")
    if ident and len(re.sub(r"[^0-9]", "", ident)) >= 6:
        return Resolution(ident)
    dates = [d for d, _ in find_dates(ref_text or "")]
    d = dates[0] if dates else date_hint
    if d:
        return Resolution(d.isoformat())
    return Resolution(None, True, "payment has neither a reference nor a date")


@dataclass(frozen=True)
class NoticeRef:
    notice_id: str
    notice_date: date
    party_slug: str


def party_slug(canonical_name: str) -> str:
    """'Vardhan Infotech Private Limited' -> 'vardhan'."""
    norm = normalise_name(canonical_name)
    first = norm.split()[0] if norm else ""
    return slugify(first)


def notice_id(notice_date: date, party: str) -> str:
    return f"{notice_date.isoformat()}-{party}"


def resolve_notice(
    ref_text: str | None,
    date_hint: date | None,
    party_hint: str | None,
    known: list[NoticeRef],
    own: NoticeRef | None = None,
) -> Resolution:
    """Notice references are `<iso date>-<sender slug>`; the date and sender come from the text or hints."""
    text = ref_text or ""
    dates = [d for d, _ in find_dates(text)]
    d = date_hint or (dates[0] if dates else None)
    if _SELF_REF.search(text) and own and not d:
        return Resolution(own.notice_id)
    if d and party_hint:
        return Resolution(notice_id(d, party_hint))
    pool = known[:]
    if d:
        pool = [k for k in pool if k.notice_date == d]
    if party_hint:
        pool = [k for k in pool if k.party_slug == party_hint]
    if len(pool) == 1:
        return Resolution(pool[0].notice_id)
    if not pool and own and (not d or own.notice_date == d):
        return Resolution(own.notice_id)
    if not pool:
        if d:
            return Resolution(None, True, f"notice dated {d.isoformat()}: sender unknown")
        return Resolution(None, True, f"no notice matches {text!r}")
    return Resolution(None, True, f"reference {text!r} matches {len(pool)} notices")
