"""Structure-aware chunking (blueprint §7.4).

One child chunk = one clause / numbered paragraph / direction / e-mail message / statement row.
Parents give the model context (small-to-big). Every chunk keeps page and character coordinates and
bounding boxes so a citation can be highlighted on the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.authority import CLAUSE_DOCS, PARAGRAPH_DOCS
from ..domain.normalise import find_dates
from ..domain.types import DocType
from .pdfio import PageContent, rects_for_range

MAX_CHILD_TOKENS = 800
TARGET_CHILD_TOKENS = 450
WINDOW_TOKENS = 400
WINDOW_OVERLAP_LINES = 1
PARENT_MAX_TOKENS = 900
PARENT_MAX_CHILDREN = 8

_NOISE = re.compile(r"^\s*(page\s+\d+(\s+of\s+\d+)?|-\s*\d+\s*-|\d{1,3})\s*$", re.IGNORECASE)
_CLAUSE = re.compile(r"^\s*(\d+(?:\.\d+){0,3})[.)]?\s+(\S.*)$")
_PARA = re.compile(r"^\s*(\d+)[.)]\s+(\S.*)$")
_FROM = re.compile(r"^\s*from\s*:", re.IGNORECASE)
_PRAYER = re.compile(r"(?i)^\s*prayer\b")
_SIGN_TAIL = re.compile(
    r"(?i)^\s*(signed\s+by|for\s+and\s+on\s+behalf|in\s+witness|witness(es)?\s*:|executed\s+by)"
)
_TAIL = re.compile(
    r"(?i)^\s*(verification|place\s*:|dated\s*(at|:|this)|date\s*:|\(?sd\.?\)?|signed|advocate|through\s*:|for\s+the\s+(plaintiff|defendant|petitioner|respondent))"
)
_MONEY = re.compile(r"\d[\d,]*\.\d{2}|\d{1,3}(?:,\d{2,3})+")
_SENTENCE = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z0-9(])")


def est_tokens(text: str) -> int:
    return int(len(text.split()) * 1.35) + 1


@dataclass
class Line:
    page: int
    start: int
    end: int
    text: str
    noise: bool = False


@dataclass
class Draft:
    level: str  # PARENT | CHILD
    ref: str | None
    heading: str | None
    pieces: list[tuple[int, int, int]]  # (page, start, end) character ranges, in reading order
    parent: int | None = None  # index of the parent draft
    ordinal: int = 0
    text: str = ""
    bboxes: list[dict] = field(default_factory=list)
    tokens: int = 0

    @property
    def page_start(self) -> int:
        return self.pieces[0][0]

    @property
    def page_end(self) -> int:
        return self.pieces[-1][0]

    @property
    def char_start(self) -> int:
        return self.pieces[0][1]

    @property
    def char_end(self) -> int:
        return self.pieces[-1][2]


# ---------------------------------------------------------------------------------------- lines
def split_lines(pages: list[PageContent]) -> list[Line]:
    repeated: set[str] = set()
    if len(pages) >= 3:
        counts: dict[str, int] = {}
        for p in pages:
            for t in {ln.strip() for ln in p.text.split("\n") if ln.strip()}:
                counts[t] = counts.get(t, 0) + 1
        repeated = {t for t, c in counts.items() if c >= max(3, int(len(pages) * 0.6)) and len(t) < 90}
    out: list[Line] = []
    for p in pages:
        pos = 0
        for raw in p.text.split("\n"):
            start, end = pos, pos + len(raw)
            pos = end + 1
            stripped = raw.strip()
            if not stripped:
                continue
            noise = bool(_NOISE.match(raw)) or stripped in repeated
            out.append(Line(p.number, start, end, raw, noise))
    return out


def _pieces(lines: list[Line]) -> list[tuple[int, int, int]]:
    """Collapse lines into one (page, start, end) range per page."""
    out: list[tuple[int, int, int]] = []
    for ln in lines:
        if out and out[-1][0] == ln.page:
            out[-1] = (ln.page, out[-1][1], ln.end)
        else:
            out.append((ln.page, ln.start, ln.end))
    return out


def _mk(
    level: str,
    lines: list[Line],
    ref: str | None = None,
    heading: str | None = None,
    parent: int | None = None,
) -> Draft:
    return Draft(level, ref, heading, _pieces(lines), parent)


# ------------------------------------------------------------------------------------ strategies
def _clause_drafts(lines: list[Line]) -> list[Draft]:
    @dataclass
    class Top:
        num: int
        lines: list[Line]
        heading: str | None
        intro: list[Line]
        subs: list[tuple[str, list[Line]]]

    preamble: list[Line] = []
    tops: list[Top] = []
    cur_top = 0
    last_sub = 0
    last_subsub = 0
    cur_sub_key = ""
    for ln in lines:
        m = _CLAUSE.match(ln.text)
        parts = [int(x) for x in m.group(1).split(".")] if m else []
        if m and any(p > 99 for p in parts[1:]):
            m = None
        accepted = False
        if m:
            if len(parts) == 1:
                accepted = parts[0] == cur_top + 1 and parts[0] < 400
                if accepted:
                    cur_top, last_sub, last_subsub, cur_sub_key = parts[0], 0, 0, ""
                    head = m.group(2).strip()
                    tops.append(Top(parts[0], [ln], head if len(head.split()) <= 8 else None, [ln], []))
            elif cur_top and parts[0] == cur_top:
                if len(parts) == 2 and parts[1] > last_sub:
                    accepted, last_sub, last_subsub, cur_sub_key = True, parts[1], 0, m.group(1)
                    tops[-1].subs.append((f"cl. {m.group(1)}", [ln]))
                    tops[-1].lines.append(ln)
                elif (
                    len(parts) >= 3
                    and cur_sub_key
                    and ".".join(map(str, parts[:2])) == cur_sub_key
                    and parts[2] > last_subsub
                ):
                    accepted, last_subsub = True, parts[2]
                    tops[-1].subs.append((f"cl. {m.group(1)}", [ln]))
                    tops[-1].lines.append(ln)
        if accepted:
            continue
        if not tops:
            preamble.append(ln)
        else:
            t = tops[-1]
            t.lines.append(ln)
            if t.subs:
                t.subs[-1][1].append(ln)
            else:
                t.intro.append(ln)

    signatures: list[Line] = []
    if tops:  # signature blocks are not part of the last clause
        last_lines = tops[-1].subs[-1][1] if tops[-1].subs else tops[-1].lines
        cut = next((i for i, ln in enumerate(last_lines) if i > 0 and _SIGN_TAIL.match(ln.text)), None)
        if cut is not None:
            signatures = last_lines[cut:]
            del last_lines[cut:]
            if tops[-1].subs:
                del tops[-1].lines[len(tops[-1].lines) - len(signatures) :]
    drafts: list[Draft] = []
    if preamble:
        drafts.append(_mk("CHILD", preamble, "Preamble"))
    for t in tops:
        if not t.subs:
            drafts.append(_mk("CHILD", t.lines, f"cl. {t.num}", t.heading))
            continue
        parent_idx = len(drafts)
        drafts.append(_mk("PARENT", t.lines, f"cl. {t.num}", t.heading))
        intro_words = sum(len(x.text.split()) for x in t.intro[1:])
        if intro_words >= 12:
            drafts.append(_mk("CHILD", t.intro, f"cl. {t.num}", t.heading, parent_idx))
        for ref, sub_lines in t.subs:
            drafts.append(_mk("CHILD", sub_lines, ref, t.heading, parent_idx))
    if signatures:
        drafts.append(_mk("CHILD", signatures, "Signatures"))
    return drafts


def _numbered_units(lines: list[Line]) -> tuple[list[Line], list[tuple[int, list[Line]]]]:
    """(header lines, [(n, lines)]) for sequentially numbered paragraphs 1, 2, 3, ..."""
    header: list[Line] = []
    units: list[tuple[int, list[Line]]] = []
    last = 0
    for ln in lines:
        m = _PARA.match(ln.text)
        if m and int(m.group(1)) == last + 1:
            last += 1
            units.append((last, [ln]))
        elif units:
            units[-1][1].append(ln)
        else:
            header.append(ln)
    return header, units


def _group_parents(children: list[Draft], drafts: list[Draft], texts: dict[int, str]) -> None:
    """Add PARENT windows over consecutive children (only when a window holds more than one child)."""
    window: list[Draft] = []
    tokens = 0

    def flush() -> None:
        nonlocal window, tokens
        if len(window) > 1:
            pidx = len(drafts)
            lines_pieces = [p for d in window for p in d.pieces]
            parent = Draft("PARENT", f"{window[0].ref}–{window[-1].ref}", None, _merge_pieces(lines_pieces))
            drafts.append(parent)
            for d in window:
                d.parent = pidx
        window, tokens = [], 0

    for d in children:
        t = _tokens_of(d, texts)
        if window and (tokens + t > PARENT_MAX_TOKENS or len(window) >= PARENT_MAX_CHILDREN):
            flush()
        window.append(d)
        tokens += t
    flush()


def _merge_pieces(pieces: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for pg, a, b in pieces:
        if out and out[-1][0] == pg:
            out[-1] = (pg, min(out[-1][1], a), max(out[-1][2], b))
        else:
            out.append((pg, a, b))
    return out


def _tokens_of(d: Draft, texts: dict[int, str]) -> int:
    return sum(est_tokens(texts[pg][a:b]) for pg, a, b in d.pieces)


def _paragraph_drafts(
    lines: list[Line], label: str, split_tail: bool, texts: dict[int, str]
) -> list[Draft] | None:
    header, units = _numbered_units(lines)
    if len(units) < 2:
        return None
    children: list[Draft] = []
    if header:
        children.append(_mk("CHILD", header, "Header"))
    for n, ls in units:
        ref = f"{label}{n}" if label == "¶" else f"{label} {n}"
        if split_tail and n == units[-1][0]:
            prayer_at = next((i for i, ln in enumerate(ls) if i > 0 and _PRAYER.match(ln.text)), None)
            tail_at = next(
                (
                    i
                    for i, ln in enumerate(ls)
                    if i > 0 and _TAIL.match(ln.text) and (prayer_at is None or i > prayer_at)
                ),
                None,
            )
            cut = [x for x in (prayer_at, tail_at) if x is not None]
            if cut:
                children.append(_mk("CHILD", ls[: cut[0]], ref))
                if prayer_at is not None:
                    children.append(_mk("CHILD", ls[prayer_at:tail_at], "Prayer"))
                if tail_at is not None:
                    children.append(_mk("CHILD", ls[tail_at:], "Closing"))
                continue
        children.append(_mk("CHILD", ls, ref))
    drafts: list[Draft] = []
    _group_parents(children, drafts, texts)  # drafts now holds the parents; children carry their index
    return [*drafts, *children]  # parents first, so a parent index is also a list index


def _email_drafts(lines: list[Line]) -> list[Draft] | None:
    starts = [i for i, ln in enumerate(lines) if _FROM.match(ln.text)]
    if len(starts) < 2:
        return None
    drafts: list[Draft] = []
    bounds = [*starts, len(lines)]
    for n, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False), 1):
        drafts.append(_mk("CHILD", lines[a:b], f"Email {n}"))
    if starts[0] > 0:
        drafts.insert(0, _mk("CHILD", lines[: starts[0]], "Header"))
    return drafts


def _row_drafts(pages: list[PageContent], lines: list[Line]) -> list[Draft] | None:
    """Statement-style documents: one child per transaction row (a line with a date and an amount)."""
    rows = [ln for ln in lines if _MONEY.search(ln.text) and find_dates(ln.text)]
    if not rows:
        return None
    drafts: list[Draft] = []
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        by_page.setdefault(ln.page, []).append(ln)
    for pg in sorted(by_page):
        page_lines = by_page[pg]
        page_rows = [ln for ln in page_lines if ln in rows]
        if not page_rows:
            drafts.append(_mk("CHILD", page_lines, f"p.{pg}"))
            continue
        pidx = len(drafts)
        drafts.append(_mk("PARENT", page_lines, f"p.{pg}"))
        others = [ln for ln in page_lines if ln not in rows]
        if others and sum(len(x.text.split()) for x in others) >= 6:
            drafts.append(_mk("CHILD", others, "Header", None, pidx))
        for k, ln in enumerate(page_rows, 1):
            drafts.append(_mk("CHILD", [ln], f"Row {k}", None, pidx))
    return drafts


def _window_drafts(lines: list[Line]) -> list[Draft]:
    """Fallback: ~400-token windows on line boundaries with one line of overlap."""
    drafts: list[Draft] = []
    buf: list[Line] = []
    tokens = 0
    for ln in lines:
        t = est_tokens(ln.text)
        if buf and tokens + t > WINDOW_TOKENS:
            drafts.append(_mk("CHILD", buf, f"Part {len(drafts) + 1}"))
            buf = buf[-WINDOW_OVERLAP_LINES:] if WINDOW_OVERLAP_LINES else []
            tokens = sum(est_tokens(x.text) for x in buf)
        buf.append(ln)
        tokens += t
    if buf:
        if drafts and tokens < 50:  # merge a tiny tail into the previous window
            prev = drafts[-1]
            prev.pieces = _merge_pieces([*prev.pieces, *_pieces(buf)])
        else:
            drafts.append(_mk("CHILD", buf, f"Part {len(drafts) + 1}"))
    return drafts


def _split_long(d: Draft, pages: dict[int, PageContent]) -> list[Draft]:
    """Size guard: a child above MAX_CHILD_TOKENS is cut at sentence boundaries into <= TARGET-sized parts."""
    if _tokens_of(d, {k: v.text for k, v in pages.items()}) <= MAX_CHILD_TOKENS:
        return [d]
    sentences: list[tuple[int, int, int]] = []
    for pg, a, b in d.pieces:
        text = pages[pg].text[a:b]
        pos = 0
        for m in _SENTENCE.finditer(text):
            sentences.append((pg, a + pos, a + m.start()))
            pos = m.end()
        sentences.append((pg, a + pos, b))
    parts: list[list[tuple[int, int, int]]] = [[]]
    tok = 0
    for s in sentences:
        t = est_tokens(pages[s[0]].text[s[1] : s[2]])
        if parts[-1] and tok + t > TARGET_CHILD_TOKENS:
            parts.append([])
            tok = 0
        parts[-1].append(s)
        tok += t
    out = []
    for k, ps in enumerate(parts, 1):
        out.append(
            Draft(
                "CHILD",
                f"{d.ref} (part {k})" if d.ref else f"part {k}",
                d.heading,
                _merge_pieces(ps),
                d.parent,
            )
        )
    return out


# --------------------------------------------------------------------------------------- public
def chunk_document(doc_type: DocType | None, pages: list[PageContent]) -> list[Draft]:
    """Chunk a parsed document. Returns drafts: parents first (referenced by index), then children."""
    page_map = {p.number: p for p in pages}
    texts = {p.number: p.text for p in pages}
    lines = [ln for ln in split_lines(pages) if not ln.noise]
    if not lines:
        return []

    drafts: list[Draft] | None = None
    if doc_type in CLAUSE_DOCS:
        drafts = _clause_drafts(lines)
        if len([d for d in drafts if d.level == "CHILD"]) < 2:
            drafts = None
    elif doc_type == DocType.ORDER:
        drafts = _paragraph_drafts(lines, "Direction", True, texts)
    elif doc_type in PARAGRAPH_DOCS:
        drafts = _paragraph_drafts(lines, "¶", True, texts)
    elif doc_type == DocType.EMAIL:
        drafts = _email_drafts(lines)
    elif doc_type in (DocType.BANK_STATEMENT, DocType.PAYMENT_RECORD):
        drafts = _row_drafts(pages, lines)
    elif doc_type in (DocType.INVOICE, DocType.RECEIPT, DocType.COURIER_PROOF, DocType.DELIVERY_NOTE):
        by_page: dict[int, list[Line]] = {}
        for ln in lines:
            by_page.setdefault(ln.page, []).append(ln)
        drafts = [_mk("CHILD", ls, f"p.{pg}") for pg, ls in sorted(by_page.items())]
    else:
        drafts = _paragraph_drafts(lines, "¶", False, texts)
    if not drafts:
        drafts = _window_drafts(lines)

    drafts = _finalise(drafts, page_map)
    return drafts


def _finalise(drafts: list[Draft], pages: dict[int, PageContent]) -> list[Draft]:
    """Apply the size guard, order parents before children, compute text, bboxes and tokens."""
    parents = [d for d in drafts if d.level == "PARENT"]
    children = [d for d in drafts if d.level == "CHILD"]
    remap = {id(p): i for i, p in enumerate(parents)}
    # parent references are indices into the original list: translate through object identity
    old_to_obj = dict(enumerate(drafts))
    final_children: list[Draft] = []
    for c in children:
        parent_obj = old_to_obj.get(c.parent) if c.parent is not None else None
        for part in _split_long(c, pages):
            part.parent = remap[id(parent_obj)] if parent_obj is not None else None
            final_children.append(part)
    out = [*parents, *final_children]
    for p in parents:
        p.parent = None
    for i, c in enumerate(final_children):
        c.ordinal = i
    for d in out:
        parts = [pages[pg].text[a:b] for pg, a, b in d.pieces]
        d.text = "\n".join(parts)
        d.tokens = est_tokens(d.text)
        d.bboxes = [r for pg, a, b in d.pieces for r in rects_for_range(pages[pg], a, b)]
    return out
