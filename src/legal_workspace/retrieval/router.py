"""Router (blueprint §9.1): rules first, then the fast model; multi-intent questions run several plans."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..adapters.llm import LLM
from ..errors import ModelOutputInvalid, ModelUnavailable
from .types import Intent

log = logging.getLogger(__name__)

_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    (
        Intent.OUT_OF_SCOPE,
        re.compile(
            r"(?i)\b(criminal|ipc|bns|crpc|bnss|murder|bail|divorce|custody|alimony|maintenance|income[- ]tax|gst return|patent|trade ?mark|copyright|land revenue|will and succession|probate)\b"
        ),
    ),
    (
        Intent.WHAT_CHANGED,
        re.compile(
            r"(?i)(what('?s| has| have)?\s+(changed|is new|are new|was added)|since the last|latest batch|new documents?|newly added|no longer (valid|true|current)|superseded|what is different|what.s different|update[sd]?\b.*\b(matter|batch|documents?))"
        ),
    ),
    (
        Intent.CHRONOLOGY,
        re.compile(
            r"(?i)\b(chronolog\w*|timeline|sequence of events|what happened when|key dates|dates? of events)\b"
        ),
    ),
    (
        Intent.DIRECTIONS,
        re.compile(
            r"(?i)(\bdirect(s|ed|ion|ions)?\b|\bdeadlines?\b|\bdue dates?\b|\boverdue\b|\bundertakings?\b|\bpending (actions?|steps?|compliance)\b|\bcourt (has )?(ordered|directed)\b|\bnext hearing\b|\bhearing date\b|\bwhen is .*\blisted\b|\bcompliance\b)"
        ),
    ),
    (
        Intent.CLAIMS,
        re.compile(
            r"(?i)(\bclaims?\b|\bcounter-?claims?\b|\bdefences?\b|\bdefenses?\b|\brelief\b|\breliefs\b|\bprays? for\b|\bwhat (does|do|did) (the )?(plaintiff|defendant|petitioner|respondent|[A-Z]\w+)\b.*\b(seek|claim|allege|argue|say|contend)\b|\bper party\b)"
        ),
    ),
    (
        Intent.EVIDENCE,
        re.compile(
            r"(?i)(\bevidence (for|against|supports?|contradicts?|on)\b|\bsupports? (the )?(claim|contention)\b|\bcontradict\w*\b|\bproof (of|that)\b|\bwhat evidence\b|\bcorroborat\w*\b)"
        ),
    ),
    (
        Intent.LEGAL_RESEARCH,
        re.compile(
            r"(?i)(\b(the )?law (say|on|relating|regarding|governing)\b|\bstatut\w*\b|\bsection\s+\d+|\bs\.\s*\d+|\bcase law\b|\bprecedents?\b|\bjudg(e)?ments?\b|\bauthorit(y|ies)\b|\blegal (position|principle|test|framework|provisions?)\b|\bprovisions? (of|under)\b|\bcpc\b|\bcode of civil procedure\b|\bcontract act\b|\bspecific relief\b|\bcommercial courts act\b|\barbitration (and conciliation )?act\b|\bliquidated damages\b.*\b(law|enforce|penalt)\w*|\bpenalty clauses?\b|\bwhat (does|do) the law\b|\bsupreme court (has )?held\b|\bwhich (section|act|order)\b)"
        ),
    ),
    (
        Intent.GIST,
        re.compile(
            r"(?i)\b(gist|summar(y|ise|ize)|overview|current position|status of the matter|where do we stand|brief me|what is this (case|matter) about|tell me about the (case|matter)|in a nutshell)\b"
        ),
    ),
]
# the order above doubles as priority when a question matches several rules and a single plan must lead
_MAX_INTENTS = 3


@dataclass
class Route:
    intents: list[Intent]
    routed_by: str  # RULES | MODEL | HINT
    party: str | None = None
    document: str | None = None
    notes: list[str] = field(default_factory=list)


def route_by_rules(question: str) -> list[Intent]:
    hits = [intent for intent, pat in _RULES if pat.search(question or "")]
    if Intent.OUT_OF_SCOPE in hits:
        return [Intent.OUT_OF_SCOPE]
    return hits[:_MAX_INTENTS]


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intents": {
            "type": "array",
            "items": {"type": "string", "enum": [i.value for i in Intent if i != Intent.OUT_OF_SCOPE]},
        },
        "party": {"type": "string"},
        "document": {"type": "string"},
    },
    "required": ["intents"],
}
_SYSTEM = (
    "You route questions about one Indian commercial litigation matter to retrieval plans. Return JSON only.\n"
    "intents (one or more): GIST (summary / current position), CHRONOLOGY (dated events), CLAIMS (claims, defences, relief per party), "
    "EVIDENCE (what supports or contradicts an assertion), DIRECTIONS (court directions, deadlines, hearing dates), "
    "WHAT_CHANGED (what is new or no longer valid), LEGAL_RESEARCH (statutes or judgments), FACTUAL_QA (a specific fact about the case).\n"
    'party: a party the question is about, as written; document: a document it is about, as written. Use "" when absent.'
)


def route(question: str, llm: LLM, hint: str | None = None) -> Route:
    """Pick plans for a question. A caller-supplied hint wins; otherwise rules; otherwise the fast model; else FACTUAL_QA."""
    if hint:
        try:
            return Route([Intent(hint.upper())], "HINT")
        except ValueError:
            pass
    hits = route_by_rules(question)
    if hits:
        return Route(hits, "RULES")
    try:
        out = llm.chat_json(
            role="fast",
            system=_SYSTEM,
            user=f"Question: {question}",
            schema=_SCHEMA,
            task="route",
            max_tokens=200,
        )
        intents = []
        for v in out.get("intents", []):
            try:
                intents.append(Intent(str(v).upper()))
            except ValueError:
                continue
        if intents:
            return Route(
                intents[:_MAX_INTENTS], "MODEL", out.get("party") or None, out.get("document") or None
            )
    except (ModelUnavailable, ModelOutputInvalid) as e:
        log.info("router model unavailable (%s); defaulting to factual QA", getattr(e, "detail", e))
        return Route([Intent.FACTUAL_QA], "RULES", notes=["router model unavailable; used the default plan"])
    return Route([Intent.FACTUAL_QA], "MODEL" if llm.supports_generation else "RULES")
