"""S06/S07: questions answered over the replayed M2 matter, scored with the scripted golden checker."""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from legal_workspace.eval.checker import check_question
from legal_workspace.grounding.answer import ask
from tests.conftest import DATA_DIR

pytestmark = [pytest.mark.db, pytest.mark.e2e]
GOLDEN = yaml.safe_load((DATA_DIR / "synthetic" / "M2" / "golden.yaml").read_text())


def run_batch_questions(m2, corpus, batch):
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    results = []
    for q in (g for g in GOLDEN if g["batch"] == batch):
        ans = ask(conn, deps, mid, q["question"], as_of=batch, today=date(2025, 10, 20))
        conn.commit()
        results.append(check_question(conn, mid, q, ans))
    return results


def test_round_one_golden_questions(m2, corpus):
    m2["replay_next"](1)
    results = run_batch_questions(m2, corpus, 1)
    failed = {r.id: r.failures for r in results if not r.passed}
    assert not failed, failed


def test_round_two_golden_questions(m2, corpus):
    m2["replay_next"](1)
    m2["replay_next"](2)
    results = run_batch_questions(m2, corpus, 2)
    failed = {r.id: r.failures for r in results if not r.passed}
    assert not failed, failed


def test_every_returned_sentence_is_verified_and_cited(m2, corpus):
    m2["replay_next"](1)
    m2["replay_next"](2)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    for question in [
        "Give me the gist of the matter",
        "What is the chronology?",
        "What changed?",
        "What did the court direct?",
        "What are the claims and defences?",
    ]:
        ans = ask(conn, deps, mid, question)
        assert ans["answer_sentences"], question
        for s in ans["answer_sentences"]:
            assert s["status"] in ("VERIFIED", "INFO", "POSSIBLE"), (question, s)
            if s["status"] == "VERIFIED":
                assert s["citations"] and all(
                    c["page"] for c in s["citations"] if c["source_kind"] == "matter"
                )
        assert not ans["unverified"], (question, ans["unverified"])


def test_current_position_never_presents_superseded_values_as_current(m2, corpus):
    m2["replay_next"](1)
    m2["replay_next"](2)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    gist = ask(conn, deps, mid, "Give me the gist of the matter")
    texts = "\n".join(s["text"] for s in gist["answer_sentences"])
    assert "31 Jul 2024" in texts and "12,40,000" in texts
    assert "Delivery / completion date (MSA-2023): 30 Jun 2024" not in texts
    assert "Outstanding on INV-014: ₹18,40,000" not in texts
    assert any(
        "30 Jun 2024" in n["fact"] and "Amendment" in str(n["superseded_by"])
        for n in gist["superseded_notes"]
    )
    disputed = [s for s in gist["answer_sentences"] if s["state"] == "DISPUTED"]
    assert len(disputed) == 2 and {"received" in s["text"] or "served" in s["text"] for s in disputed} == {
        True
    }


def test_as_of_batch_one_answers_from_the_earlier_position(m2, corpus):
    m2["replay_next"](1)
    m2["replay_next"](2)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    ans = ask(conn, deps, mid, "When is delivery due?", as_of=1)
    assert (
        "30 Jun 2024" in "\n".join(s["text"] for s in ans["answer_sentences"]) and ans["as_of_batch_seq"] == 1
    )
    assert "31 Jul 2024" not in "\n".join(s["text"] for s in ans["answer_sentences"])


def test_chronology_shows_superseded_entries_struck_through(m2, corpus):
    m2["replay_next"](1)
    m2["replay_next"](2)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    ans = ask(conn, deps, mid, "Show me the timeline of events")
    sec = ans["sections"][0]
    assert sec["plan"] == "CHRONOLOGY"
    dates = [s["meta"]["date"] for s in sec["sentences"]]
    assert dates == sorted(dates)
    struck = [s for s in sec["sentences"] if s["state"] == "SUPERSEDED"]
    assert struck and any("Amendment" in (s["superseded_by"] or "") for s in struck)


def test_directions_answer_has_computed_deadlines_and_overdue_status(m2, corpus):
    m2["replay_next"](1)
    m2["replay_next"](2)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    ans = ask(conn, deps, mid, "What are the pending deadlines?", today=date(2025, 10, 20))
    text = "\n".join(s["text"] for s in ans["answer_sentences"])
    assert "10 Oct 2025" in text and "OVERDUE" in text and "24 Oct 2025" in text and "PENDING" in text
    assert "14 Nov 2025" in text


def test_legal_research_returns_authorities_from_the_corpus_with_unverified_badge(m2, corpus):
    m2["replay_next"](1)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    ans = ask(conn, deps, mid, "What does the law say about liquidated damages and penalty?")
    law = [s for s in ans["answer_sentences"] if s["kind"] == "authority"]
    assert law and any("s.74" in s["text"] for s in law)
    assert all(s["meta"]["verification_status"] == "UNVERIFIED" for s in law)
    assert all(c["source_kind"] == "law" and c["source_id"] for s in law for c in s["citations"])
    assert "indian-contract-act-1872" in {s["meta"]["source_key"] for s in law}


def test_out_of_scope_questions_are_declined_politely(m2, corpus):
    m2["replay_next"](1)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    ans = ask(conn, deps, mid, "Can he get bail under the IPC for this murder charge?")
    assert ans["intents"] == ["OUT_OF_SCOPE"] and "outside its scope" in ans["answer_sentences"][0]["text"]


def test_unanswerable_question_says_not_found_and_invents_nothing(m2, corpus):
    m2["replay_next"](1)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    ans = ask(conn, deps, mid, "What colour is the Defendant's office building?")
    assert not [s for s in ans["answer_sentences"] if s["status"] == "VERIFIED"] and ans["not_found"]


def test_a_trace_is_stored_for_every_answer(m2, corpus):
    m2["replay_next"](1)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    ans = ask(conn, deps, mid, "What is the contract value?", actor="alice")
    row = conn.execute("SELECT * FROM query_traces WHERE trace_id = %s", (ans["trace_id"],)).fetchone()
    assert (
        row["actor"] == "alice"
        and row["question"] == "What is the contract value?"
        and row["intents"] == ans["intents"]
    )
    assert row["plans"] and "total_ms" in row["timings_ms"]


def test_hearing_brief_has_all_sections_every_line_cited_and_markdown(m2, corpus):
    from legal_workspace.grounding.brief import generate_brief

    m2["replay_next"](1)
    m2["replay_next"](2)
    conn, deps, mid = m2["conn"], m2["deps"], str(m2["matter"]["matter_id"])
    brief = generate_brief(conn, deps, mid, today=date(2025, 10, 20))
    assert [s["n"] for s in brief["sections"]] == list(range(1, 9))
    sec = {s["n"]: s for s in brief["sections"]}
    assert any("Next hearing" in s["text"] and "14 Nov 2025" in s["text"] for s in sec[1]["sentences"])
    assert (
        len([s for s in sec[3]["sentences"] if s["state"] == "DISPUTED"]) == 2
    )  # both versions of the notice
    assert any("OVERDUE" in s["text"] for s in sec[8]["sentences"])
    assert any("SUPERSEDED" in s["text"] or "NARROWED" in s["text"] for s in sec[6]["sentences"])
    assert sec[7]["sentences"], "authorities section is empty"
    for n in (2, 3, 5, 6):
        for s in sec[n]["sentences"]:
            assert s["status"] == "VERIFIED" and s["citations"], s
    assert not brief["unverified"]
    md = brief["markdown"]
    assert (
        md.startswith("# Hearing brief: Vardhan Infotech")
        and "## 6. Changes since the last hearing" in md
        and "[Order dated 12 September 2025, p.1]" in md
    )


def test_brief_before_any_batch_is_refused(conn, fixture_deps):
    from legal_workspace.db import matters
    from legal_workspace.errors import ValidationFailed
    from legal_workspace.grounding.brief import generate_brief

    m = matters.create_matter(conn, matter_number="B/1", title="t", matter_type="BREACH")
    with pytest.raises(ValidationFailed):
        generate_brief(conn, fixture_deps, str(m["matter_id"]))
