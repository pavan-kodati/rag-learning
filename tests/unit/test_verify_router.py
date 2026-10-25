"""S06/S07: citation verification and routing, including adversarial model output."""

from __future__ import annotations

import pytest

from legal_workspace.adapters.testing import ScriptedLLM
from legal_workspace.errors import ModelOutputInvalid
from legal_workspace.grounding.verify import (
    Evidence,
    norm,
    numeric_tokens,
    quote_on_page,
    verify_law_citation,
    verify_sentence,
    verify_statement_citation,
)
from legal_workspace.retrieval.router import route, route_by_rules
from legal_workspace.retrieval.types import Intent

PAGE = "2.2 Completion of the Deliverables shall occur on or before 31 July 2024.\n3.1 Each invoice is payable within 30 days. The contract value is Rs. 48,00,000."


def ev(**kw):
    base = dict(
        id="E1",
        kind="chunk",
        text="Completion of the Deliverables shall occur on or before 31 July 2024.",
        page_text=PAGE,
        document_id="d1",
        document_title="Amendment No. 1",
        page=2,
        structural_ref="cl. 2.2",
    )
    base.update(kw)
    return {base["id"]: Evidence(**base)}


# ------------------------------------------------------------------------------------- numbers
@pytest.mark.parametrize(
    "text, expected",
    [
        ("Rs. 18,40,000 and 18.4 lakh", {"1840000"}),
        ("on 31 July 2024", {"2024-07-31", "31", "2024"}),
        ("31/07/2024", {"2024-07-31", "31", "7", "2024"}),
        ("INR 1.2 crore", {"12000000"}),
        ("no numbers here", set()),
    ],
)
def test_numeric_tokens(text, expected):
    assert expected <= numeric_tokens(text)


def test_norm_collapses_quotes_dashes_and_space():
    assert norm("The  “Go-Live”—Date\n shall") == 'the "go-live"-date shall'


@pytest.mark.parametrize(
    "quote, ok",
    [
        ("Completion of the Deliverables shall occur on or before 31 July 2024", True),
        ("completion of the deliverables  shall occur\non or before 31 july 2024", True),
        (
            "Completion of the Deliverables shall occur on or before 31 Jluy 2024",
            True,
        ),  # small typo tolerated
        ("The Supplier shall deliver by 31 August 2024 without fail", False),
        ("", False),
        ("ab", False),
    ],
)
def test_quote_on_page(quote, ok):
    assert quote_on_page(quote, PAGE) is ok


# ------------------------------------------------------------------------------------- sentences
def check(text, ids, quote, evidence, **kw):
    return verify_sentence(text, ids, quote, evidence, **kw)


def test_a_grounded_sentence_passes():
    c = check("The Go-Live Date is 31 July 2024.", ["E1"], "shall occur on or before 31 July 2024", ev())
    assert c.ok, c.reasons


@pytest.mark.parametrize(
    "text, ids, quote, why",
    [
        ("Delivery is due on 31 July 2024.", [], "x" * 10, "no evidence cited"),
        (
            "Delivery is due on 31 July 2024.",
            ["E9"],
            "shall occur on or before 31 July 2024",
            "not retrieved",
        ),
        (
            "Delivery is due on 15 August 2024.",
            ["E1"],
            "shall occur on or before 31 July 2024",
            "numbers or dates",
        ),
        (
            "The contract value is Rs. 99,00,000.",
            ["E1"],
            "shall occur on or before 31 July 2024",
            "numbers or dates",
        ),
        (
            "Delivery is due on 31 July 2024.",
            ["E1"],
            "the parties agreed to deliver in August",
            "quote not found",
        ),
    ],
)
def test_ungrounded_sentences_are_rejected(text, ids, quote, why):
    c = check(text, ids, quote, ev())
    assert not c.ok and any(why in r for r in c.reasons)


def test_numbers_may_come_from_the_facts_attached_to_the_evidence():
    e = ev(extra_text="Outstanding on INV-014: ₹12,40,000 (computed)")
    assert check("Rs. 12,40,000 is outstanding.", ["E1"], "shall occur on or before 31 July 2024", e).ok


def test_sentence_built_only_from_superseded_facts_is_rejected_unless_allowed():
    e = ev(state="SUPERSEDED")
    assert not check("Delivery is due on 31 July 2024.", ["E1"], "on or before 31 July 2024", e).ok
    assert check(
        "Delivery was due on 31 July 2024.", ["E1"], "on or before 31 July 2024", e, allow_superseded=True
    ).ok


def test_mixed_current_and_superseded_evidence_is_allowed():
    e = {**ev(state="SUPERSEDED"), **ev(id="F1", kind="fact", state="CURRENT")}
    assert check("Delivery is due on 31 July 2024.", ["E1", "F1"], "on or before 31 July 2024", e).ok


# ----------------------------------------------------------------------------------- structured plans
def test_statement_citations_are_checked_against_the_stored_page():
    pages = {("d1", 2): PAGE}
    assert verify_statement_citation(pages, "d1", 2, "on or before 31 July 2024").ok
    assert not verify_statement_citation(pages, "d1", 2, "something never written").ok
    assert not verify_statement_citation(pages, "d1", 9, "x" * 8).ok  # page does not exist
    assert not verify_statement_citation(pages, None, 2, "x" * 8).ok
    assert verify_statement_citation(pages, "d1", 2, None).ok  # document-level event: the page must exist


def test_law_citations_must_exist_in_the_corpus():
    known = {"p1": {"title": "Indian Contract Act"}}
    assert verify_law_citation("p1", known).ok
    assert not verify_law_citation("made-up", known).ok and not verify_law_citation(None, known).ok


# -------------------------------------------------------------------------------------------- router
@pytest.mark.parametrize(
    "q, expected",
    [
        ("What changed since the last batch?", Intent.WHAT_CHANGED),
        ("What is no longer valid?", Intent.WHAT_CHANGED),
        ("Give me a chronology of the matter", Intent.CHRONOLOGY),
        ("What did the court direct and by when?", Intent.DIRECTIONS),
        ("Is anything overdue?", Intent.DIRECTIONS),
        ("What is the next hearing date?", Intent.DIRECTIONS),
        ("What are the plaintiff's claims and the defendant's defences?", Intent.CLAIMS),
        ("What relief is sought?", Intent.CLAIMS),
        ("What evidence contradicts the denial?", Intent.EVIDENCE),
        ("What does the law say about penalty clauses?", Intent.LEGAL_RESEARCH),
        ("Which section of the Contract Act applies?", Intent.LEGAL_RESEARCH),
        ("Summarise the matter", Intent.GIST),
        ("Where do we stand?", Intent.GIST),
    ],
)
def test_rules_route_to_the_expected_plan(q, expected):
    assert expected in route_by_rules(q)


def test_out_of_scope_wins_over_everything():
    assert route_by_rules("What changed in the murder case under the IPC?") == [Intent.OUT_OF_SCOPE]
    assert route_by_rules("Is the patent infringement claim time-barred?") == [Intent.OUT_OF_SCOPE]


def test_multi_intent_questions_run_several_plans_but_never_more_than_three():
    got = route_by_rules("Summarise the claims, the deadlines and what changed, and the law on penalty")
    assert 2 <= len(got) <= 3


def test_unmatched_question_goes_to_the_fast_model_then_defaults_to_factual():
    llm = ScriptedLLM(lambda *_: {"intents": ["CLAIMS", "BOGUS"], "party": "Kestrel", "document": ""})
    r = route("Tell me something interesting about Kestrel's position", llm)
    assert r.routed_by == "MODEL" and r.intents == [Intent.CLAIMS] and r.party == "Kestrel"
    r = route("What is the price?", ScriptedLLM(lambda *_: {"intents": []}))
    assert r.intents == [Intent.FACTUAL_QA]


def test_router_survives_a_broken_model():
    def boom(*_):
        raise ModelOutputInvalid("garbage")

    r = route("What is the price?", ScriptedLLM(boom))
    assert r.intents == [Intent.FACTUAL_QA] and r.notes


def test_hint_overrides_rules_and_bad_hint_is_ignored():
    llm = ScriptedLLM(lambda *_: {"intents": []})
    assert (
        route("What changed?", llm, hint="gist").intents == [Intent.GIST]
        and route("What changed?", llm, hint="gist").routed_by == "HINT"
    )
    assert route("What changed?", llm, hint="nonsense").intents == [Intent.WHAT_CHANGED]
