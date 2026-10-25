"""S08: legal corpus loading and search, including malformed input."""

from __future__ import annotations

import textwrap

import pytest

from legal_workspace.adapters.embed import HashingEmbedder
from legal_workspace.corpus.loader import corpus_count, load_corpus, parse_seed
from legal_workspace.corpus.search import known_authorities, search_corpus
from legal_workspace.errors import ValidationFailed
from tests.conftest import DATA_DIR

pytestmark = pytest.mark.db
SEED = DATA_DIR / "corpus" / "seed.yaml"
EMB = HashingEmbedder()


def write(tmp_path, body):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_seed_loads_embeds_and_flags_everything_unverified(conn):
    counts = load_corpus(conn, EMB, SEED)
    conn.commit()
    assert counts == {"sources": 12, "passages": 27} and corpus_count(conn) == 27
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM legal_corpus.passages WHERE dense_embedding IS NULL"
        ).fetchone()["n"]
        == 0
    )
    assert {
        r["verification_status"]
        for r in conn.execute("SELECT verification_status FROM legal_corpus.sources").fetchall()
    } == {"UNVERIFIED"}
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM legal_corpus.sources WHERE verified_by NOT LIKE 'UNVERIFIED%'"
        ).fetchone()["n"]
        == 0
    )


def test_reloading_is_idempotent(conn):
    load_corpus(conn, EMB, SEED)
    load_corpus(conn, EMB, SEED)
    conn.commit()
    assert corpus_count(conn) == 27


def test_a_source_with_a_verifier_is_marked_verified(conn, tmp_path):
    p = write(
        tmp_path,
        """
        sources:
          - key: s1
            type: STATUTE
            title: Test Act
            source_url: https://example.invalid
            verified_by: A. Lawyer
            verified_on: 2026-01-02
            passages:
              - section_ref: s.1
                content: Something enacted.
                tags: [delay]
    """,
    )
    load_corpus(conn, EMB, p)
    row = conn.execute(
        "SELECT verification_status, verified_by FROM legal_corpus.sources WHERE source_key = 's1'"
    ).fetchone()
    assert row == {"verification_status": "VERIFIED", "verified_by": "A. Lawyer"}


@pytest.mark.parametrize(
    "body",
    [
        "",
        "sources: []",
        "not: [valid",
        "sources:\n  - key: a\n    type: STATUTE\n    title: T\n    source_url: u\n",  # no passages
        "sources:\n  - key: a\n    type: BOOK\n    title: T\n    source_url: u\n    passages: [{content: x}]",
        "sources:\n  - key: a\n    type: STATUTE\n    title: T\n    source_url: u\n    passages: [{content: '  '}]",
        "sources:\n  - {key: a, type: STATUTE, title: T, source_url: u, passages: [{content: x}]}\n  - {key: a, type: STATUTE, title: T, source_url: u, passages: [{content: y}]}",
    ],
)
def test_malformed_corpus_files_are_rejected_before_anything_is_written(conn, tmp_path, body):
    with pytest.raises(ValidationFailed):
        load_corpus(conn, EMB, write(tmp_path, body))
    assert corpus_count(conn) == 0


def test_missing_corpus_file(tmp_path):
    with pytest.raises(ValidationFailed):
        parse_seed(tmp_path / "nope.yaml")


def test_search_by_question_and_tags_ranks_the_right_authority_first(conn):
    load_corpus(conn, EMB, SEED)
    top = search_corpus(
        conn, EMB, "liquidated damages stipulated sum penalty", tags=["liquidated_damages", "penalty"], k=3
    )
    assert top[0]["section_ref"] == "s.74" or top[0]["source_key"] in (
        "kailash-nath-associates-v-dda",
        "ongc-v-saw-pipes",
    )
    assert {p["source_key"] for p in top} & {"indian-contract-act-1872", "kailash-nath-associates-v-dda"}
    inj = search_corpus(
        conn,
        EMB,
        "temporary injunction prima facie case balance of convenience",
        tags=["interim_injunction"],
        k=3,
    )
    assert {p["source_key"] for p in inj} & {"dalpat-kumar-v-prahlad-singh", "code-of-civil-procedure-1908"}
    med = search_corpus(
        conn, EMB, "pre-institution mediation mandatory", tags=["pre_institution_mediation"], k=3
    )
    assert {p["source_key"] for p in med} & {
        "patil-automation-v-rakheja-engineers",
        "commercial-courts-act-2015",
    }


def test_search_works_from_tags_alone_and_returns_nothing_without_input(conn):
    load_corpus(conn, EMB, SEED)
    assert search_corpus(conn, EMB, "", tags=["time_essence"], k=3)
    assert search_corpus(conn, EMB, "", tags=[], k=3) == []
    assert search_corpus(conn, EMB, "   ", tags=None) == []


def test_search_on_an_empty_corpus_is_empty_not_an_error(conn):
    assert search_corpus(conn, EMB, "anything", tags=["delay"]) == []


def test_known_authorities_lists_every_passage(conn):
    load_corpus(conn, EMB, SEED)
    assert len(known_authorities(conn)) == 27


def test_issue_tags_follow_the_disputed_slots(m2, corpus):
    from legal_workspace.retrieval.plans import issue_tags

    m2["replay_next"](1)
    m2["replay_next"](2)
    tags = issue_tags(m2["conn"], m2["matter"], 2)
    assert {
        "service_of_notice",
        "time_essence",
        "liquidated_damages",
        "recovery_of_price",
        "part_payment",
        "pre_institution_mediation",
    } <= set(tags)
