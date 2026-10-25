"""S02: schema integrity, repositories and the job queue, including negative cases."""

from __future__ import annotations

import threading
import uuid

import psycopg
import pytest

from legal_workspace.db import audit, documents, jobs, matters
from legal_workspace.db.migrate import MIGRATIONS_DIR, MigrationError, migrate
from legal_workspace.errors import (
    BatchClosed,
    Conflict,
    DuplicateDocument,
    NotFound,
    ValidationFailed,
)
from tests.conftest import TEST_URL

pytestmark = pytest.mark.db


def make_matter(conn, number="CS(COMM) 1/2025", parties=True):
    return matters.create_matter(
        conn,
        matter_number=number,
        title="Vardhan v Kestrel",
        matter_type="PAYMENT_RECOVERY",
        parties=[
            {
                "name": "Vardhan Infotech Private Limited",
                "role": "PLAINTIFF",
                "aliases": ["Vardhan", "the Supplier"],
            },
            {"name": "Kestrel Limited", "role": "DEFENDANT", "aliases": ["Kestrel Ltd", "the Customer"]},
        ]
        if parties
        else None,
    )


def new_doc(conn, m, batch, name="a.pdf", sha=None):
    return documents.create_document(
        conn,
        matter_id=m["matter_id"],
        batch_seq=batch,
        title=name,
        original_filename=name,
        mime_type="application/pdf",
        storage_uri=f"file:///x/{name}",
        sha256=sha or uuid.uuid4().hex + uuid.uuid4().hex,
    )


# ------------------------------------------------------------------------------------- migrations
def test_migrations_idempotent_and_checksummed():
    assert migrate(TEST_URL) == []  # nothing pending
    path = MIGRATIONS_DIR / "002_audit.sql"
    original = path.read_text()
    try:
        path.write_text(original + "\n-- tampered\n")
        with pytest.raises(MigrationError):
            migrate(TEST_URL)
    finally:
        path.write_text(original)


# ------------------------------------------------------------------------------------- matters
def test_create_and_get_matter(conn):
    m = make_matter(conn)
    assert matters.get_matter(conn, m["matter_id"])["title"] == "Vardhan v Kestrel"
    assert len(matters.list_parties(conn, m["matter_id"])) == 2
    assert matters.list_matters(conn)[0]["document_count"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(matter_number="", title="t", matter_type="BREACH"),
        dict(matter_number="n", title=" ", matter_type="BREACH"),
        dict(matter_number="n", title="t", matter_type="CRIMINAL"),
    ],
)
def test_create_matter_validation(conn, kwargs):
    with pytest.raises(ValidationFailed):
        matters.create_matter(conn, **kwargs)


def test_duplicate_matter_number_conflicts(conn):
    make_matter(conn)
    with pytest.raises(Conflict):
        make_matter(conn)


@pytest.mark.parametrize("bad", ["not-a-uuid", "00000000-0000-0000-0000-000000000000", ""])
def test_get_matter_not_found(conn, bad):
    with pytest.raises(NotFound):
        matters.get_matter(conn, bad)
    conn.rollback()


def test_party_validation(conn):
    m = make_matter(conn, parties=False)
    with pytest.raises(ValidationFailed):
        matters.add_party(conn, m["matter_id"], "", "PLAINTIFF", [])
    with pytest.raises(ValidationFailed):
        matters.add_party(conn, m["matter_id"], "X Ltd", "WITNESS", [])


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Kestrel Limited", "Kestrel Limited"),
        ("KESTREL LTD.", "Kestrel Limited"),
        ("the Customer", "Kestrel Limited"),
        ("M/s. Kestrel Ltd", "Kestrel Limited"),
        ("Defendant No. 1", "Kestrel Limited"),
        ("the Defendant", "Kestrel Limited"),
        ("Plaintiff", "Vardhan Infotech Private Limited"),
        ("Vardhan", "Vardhan Infotech Private Limited"),
        ("Vardhan Infotech Pvt Ltd", "Vardhan Infotech Private Limited"),
    ],
)
def test_resolve_party(conn, text, expected):
    m = make_matter(conn)
    assert matters.resolve_party(conn, m["matter_id"], text)["canonical_name"] == expected


@pytest.mark.parametrize("text", ["", None, "Unknown Corp", "Defendant No. 2", "Kes", "Third Party"])
def test_resolve_party_unknown_is_none(conn, text):
    m = make_matter(conn)
    assert matters.resolve_party(conn, m["matter_id"], text) is None


def test_resolve_party_role_word_ambiguous_with_two_defendants(conn):
    m = make_matter(conn)
    matters.add_party(conn, m["matter_id"], "Second Defendant Corp", "DEFENDANT", [])
    assert matters.resolve_party(conn, m["matter_id"], "the defendant") is None  # ambiguous
    assert (
        matters.resolve_party(conn, m["matter_id"], "Defendant No. 2")["canonical_name"]
        == "Second Defendant Corp"
    )


# ------------------------------------------------------------------------------------- batches
def test_batches_are_sequential_and_exclusive(conn):
    m = make_matter(conn)
    b1 = matters.open_batch(conn, m["matter_id"], "initial")
    assert b1["batch_seq"] == 1 and b1["status"] == "OPEN"
    with pytest.raises(Conflict):
        matters.open_batch(conn, m["matter_id"])
    matters.set_batch_status(conn, m["matter_id"], 1, "COMMITTED")
    assert matters.latest_committed_seq(conn, m["matter_id"]) == 1
    assert matters.open_batch(conn, m["matter_id"])["batch_seq"] == 2


def test_batch_status_validation_and_missing_batch(conn):
    m = make_matter(conn)
    with pytest.raises(NotFound):
        matters.get_batch(conn, m["matter_id"], 9)
    from legal_workspace.errors import BadRequest

    with pytest.raises(BadRequest):
        matters.set_batch_status(conn, m["matter_id"], 1, "WHATEVER")


# ------------------------------------------------------------------------------------- documents
def test_duplicate_upload_is_rejected_and_recorded(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    sha = "a" * 64
    first = new_doc(conn, m, 1, "a.pdf", sha)
    with pytest.raises(DuplicateDocument) as ei:
        new_doc(conn, m, 1, "copy_of_a.pdf", sha)
    assert ei.value.extra["document_id"] == str(first["document_id"])
    dups = documents.list_duplicates(conn, m["matter_id"], 1)
    assert [d["original_filename"] for d in dups] == ["copy_of_a.pdf"]


def test_same_file_allowed_in_different_matters(conn):
    m1, m2 = make_matter(conn, "A/1"), make_matter(conn, "B/1")
    for m in (m1, m2):
        matters.open_batch(conn, m["matter_id"])
        new_doc(conn, m, 1, "a.pdf", "b" * 64)


def test_upload_to_closed_or_missing_batch_fails(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    matters.set_batch_status(conn, m["matter_id"], 1, "PROCESSING")
    with pytest.raises(BatchClosed):
        new_doc(conn, m, 1)
    with pytest.raises(NotFound):
        new_doc(conn, m, 7)


def test_update_document_rejects_unknown_columns(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    with pytest.raises(ValueError):
        documents.update_document(conn, d["document_id"], sha256="x")
    documents.update_document(conn, d["document_id"], status="PROCESSING", total_pages=3)
    assert documents.get_document(conn, d["document_id"])["total_pages"] == 3


def test_pages_roundtrip_and_missing_page(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    documents.save_pages(
        conn,
        d["document_id"],
        [
            {
                "page_number": 1,
                "page_text": "one",
                "extraction_method": "DIGITAL",
                "page_width": 595.0,
                "page_height": 842.0,
            },
            {"page_number": 2, "page_text": "two", "extraction_method": "OCR", "ocr_confidence": 71.5},
        ],
    )
    assert [p["page_text"] for p in documents.get_pages(conn, d["document_id"])] == ["one", "two"]
    with pytest.raises(NotFound):
        documents.get_page(conn, d["document_id"], 3)
    with pytest.raises(psycopg.errors.CheckViolation):
        documents.save_pages(
            conn, d["document_id"], [{"page_number": 0, "page_text": "x", "extraction_method": "DIGITAL"}]
        )


def test_get_document_not_found(conn):
    with pytest.raises(NotFound):
        documents.get_document(conn, "nope")
    conn.rollback()


# ------------------------------------------------------------------------------------- integrity
def _fact_sql(conn, m, doc, **over):
    cols = dict(
        matter_id=m["matter_id"],
        fact_key="contract/msa/delivery_date",
        subject_type="CONTRACT",
        slot="delivery_date",
        assertion_category="TERM",
        assertion_text="t",
        originating_document_id=doc["document_id"],
        source_page=1,
        source_quote="q",
        learned_in_batch_seq=1,
        state="ACTIVE",
        ended_in_batch_seq=None,
    )
    cols.update(over)
    keys = ", ".join(cols)
    ph = ", ".join(["%s"] * len(cols))
    return conn.execute(
        f"INSERT INTO matter_fact_assertions ({keys}) VALUES ({ph}) RETURNING *", list(cols.values())
    ).fetchone()  # noqa: S608


def test_fact_state_ended_batch_invariant_is_enforced_by_the_database(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    _fact_sql(conn, m, d)  # valid
    with pytest.raises(psycopg.errors.CheckViolation):
        _fact_sql(conn, m, d, state="SUPERSEDED", ended_in_batch_seq=None)
    conn.rollback()


def test_fact_cannot_end_before_it_was_learned_and_batch_must_exist(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        _fact_sql(conn, m, d, learned_in_batch_seq=1, ended_in_batch_seq=0, state="SUPERSEDED")
    conn.rollback()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _fact_sql(conn, m, d, learned_in_batch_seq=5)
    conn.rollback()


def test_fact_category_and_state_vocabulary_enforced(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        _fact_sql(conn, m, d, assertion_category="OPINION")
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        _fact_sql(conn, m, d, state="MAYBE")
    conn.rollback()


def test_link_must_have_exactly_one_target(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    f = _fact_sql(conn, m, d)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO fact_links (matter_id, assertion_id, link_type, batch_seq, rule_id) VALUES (%s,%s,'SUPPORTS',1,'R1')",
            (m["matter_id"], f["assertion_id"]),
        )
    conn.rollback()


def test_deleting_a_matter_cascades_everything(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    _fact_sql(conn, m, d)
    conn.execute("DELETE FROM matters WHERE matter_id = %s", (m["matter_id"],))
    for t in ("documents", "matter_fact_assertions", "parties", "ingestion_batches"):
        assert conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] == 0  # noqa: S608


def test_chunk_page_range_check(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d = new_doc(conn, m, 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO document_chunks (matter_id, document_id, batch_seq, chunk_level, context_header, chunk_text, "
            "page_start, page_end, char_start, char_end, token_count) VALUES (%s,%s,1,'CHILD','h','t',3,2,0,1,1)",
            (m["matter_id"], d["document_id"]),
        )
    conn.rollback()


# ------------------------------------------------------------------------------------- job queue
def _queue_doc_job(conn, m, name="a.pdf"):
    d = new_doc(conn, m, 1, name)
    return d, jobs.enqueue(conn, m["matter_id"], 1, "PARSE", d["document_id"])


def test_job_claim_is_exclusive_and_ordered(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    _, j1 = _queue_doc_job(conn, m, "a.pdf")
    _, j2 = _queue_doc_job(conn, m, "b.pdf")
    conn.commit()
    got1 = jobs.claim(conn)
    got2 = jobs.claim(conn)
    assert (got1["job_id"], got2["job_id"]) == (j1, j2) and got1["attempts"] == 1
    assert jobs.claim(conn) is None


def test_two_workers_never_claim_the_same_job(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    for i in range(12):
        _queue_doc_job(conn, m, f"{i}.pdf")
    conn.commit()
    claimed: list[int] = []
    lock = threading.Lock()

    def worker():
        with psycopg.connect(TEST_URL, row_factory=psycopg.rows.dict_row, autocommit=True) as c:
            while (job := jobs.claim(c)) is not None:
                with lock:
                    claimed.append(job["job_id"])

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(claimed) == 12 and len(set(claimed)) == 12


def test_enqueue_is_idempotent(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    d, j = _queue_doc_job(conn, m)
    assert jobs.enqueue(conn, m["matter_id"], 1, "PARSE", d["document_id"]) is None
    assert jobs.enqueue(conn, m["matter_id"], 1, "RECONCILE") is not None
    assert jobs.enqueue(conn, m["matter_id"], 1, "RECONCILE") is None


def test_reconcile_waits_for_the_other_jobs_of_its_batch(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    _, j = _queue_doc_job(conn, m)
    rec = jobs.enqueue(conn, m["matter_id"], 1, "RECONCILE")
    first = jobs.claim(conn)
    assert first["job_id"] == j
    assert jobs.claim(conn) is None  # parse job still RUNNING -> reconcile must wait
    jobs.complete(conn, j)
    assert jobs.claim(conn)["job_id"] == rec


def test_failed_job_retries_then_fails_permanently(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    _, j = _queue_doc_job(conn, m)
    for attempt in (1, 2):
        assert jobs.claim(conn)["attempts"] == attempt
        assert jobs.fail(conn, j, "boom", max_attempts=3) == "QUEUED"
    assert jobs.claim(conn)["attempts"] == 3
    assert jobs.fail(conn, j, "boom", max_attempts=3) == "FAILED"
    assert jobs.claim(conn) is None
    assert jobs.get_job(conn, j)["last_error"] == "boom"


def test_non_retryable_failure_is_final_immediately(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    _, j = _queue_doc_job(conn, m)
    jobs.claim(conn)
    assert jobs.fail(conn, j, "corrupt pdf", max_attempts=3, retryable=False) == "FAILED"


def test_stale_running_job_is_requeued_or_failed(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    _, j = _queue_doc_job(conn, m)
    jobs.claim(conn)
    assert jobs.requeue_stale(conn, older_than_s=600, max_attempts=3) == 0  # fresh lock
    conn.execute("UPDATE ingestion_jobs SET locked_at = now() - interval '1 hour'")
    assert jobs.requeue_stale(conn, older_than_s=600, max_attempts=3) == 1
    assert jobs.get_job(conn, j)["status"] == "QUEUED"
    jobs.claim(conn)
    conn.execute("UPDATE ingestion_jobs SET locked_at = now() - interval '1 hour', attempts = 3")
    jobs.requeue_stale(conn, older_than_s=600, max_attempts=3)
    assert jobs.get_job(conn, j)["status"] == "FAILED"


def test_batch_progress_counts(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    _queue_doc_job(conn, m, "a.pdf")
    _queue_doc_job(conn, m, "b.pdf")
    jobs.claim(conn)
    assert jobs.batch_progress(conn, m["matter_id"], 1) == {"QUEUED": 1, "RUNNING": 1, "DONE": 0, "FAILED": 0}


def test_audit_log_roundtrip(conn):
    m = make_matter(conn)
    audit.record(
        conn, actor="alice", role="admin", action="matter.create", matter_id=m["matter_id"], detail={"x": 1}
    )
    rows = audit.list_entries(conn, m["matter_id"])
    assert rows[0]["actor"] == "alice" and rows[0]["detail"] == {"x": 1}


def test_a_failed_document_can_be_uploaded_again_but_a_good_one_cannot(conn):
    m = make_matter(conn)
    matters.open_batch(conn, m["matter_id"])
    sha = "c" * 64
    first = new_doc(conn, m, 1, "a.pdf", sha)
    documents.update_document(conn, first["document_id"], status="FAILED", error_message="boom")
    second = new_doc(conn, m, 1, "a_again.pdf", sha)  # replaces the failed row
    assert second["document_id"] != first["document_id"]
    assert [d["original_filename"] for d in documents.list_documents(conn, m["matter_id"])] == ["a_again.pdf"]
    with pytest.raises(DuplicateDocument):
        new_doc(conn, m, 1, "a_third.pdf", sha)
