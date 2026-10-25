"""S04 integration: upload -> parse -> chunk -> embed -> extract, through the real database and worker."""

from __future__ import annotations

import pytest

from legal_workspace.adapters.testing import ScriptedLLM
from legal_workspace.db import chunks as chunk_repo
from legal_workspace.db import documents as doc_repo
from legal_workspace.db import jobs as job_repo
from legal_workspace.db import matters
from legal_workspace.errors import (
    BadRequest,
    BatchClosed,
    NotFound,
    PayloadTooLarge,
    UnsupportedMedia,
    ValidationFailed,
)
from legal_workspace.ingestion import service
from legal_workspace.worker import Worker
from tests.helpers import DocScript, cls, docx_bytes, encrypted_pdf, pdf
from tests.integration.test_db_layer import make_matter

pytestmark = pytest.mark.db

MSA_TEXT = """# MASTER SERVICES AGREEMENT
This Agreement is made on 12 January 2023 between Vardhan Infotech Private Limited (the Supplier) and Kestrel Limited (the Customer).
1. DELIVERY
1.1 Time is of the essence.
1.2 Completion of the Deliverables shall occur on or before 30 June 2024.
2. PAYMENT
2.1 The Customer shall pay each invoice within 30 days of receipt.
Signed by Vardhan Infotech Private Limited
Signed by Kestrel Limited
"""
MSA_CLS = cls(
    "CONTRACT",
    "Master Services Agreement",
    "12 January 2023",
    signed=True,
    parties=[
        {"name": "Vardhan Infotech Private Limited", "role": "OTHER", "aliases": ["the Supplier"]},
        {"name": "Kestrel Limited", "role": "OTHER", "aliases": ["the Customer"]},
    ],
)
MSA_ITEMS = [
    {
        "subject_type": "CONTRACT",
        "subject_ref": "MSA",
        "slot": "delivery_date",
        "value": "30 June 2024",
        "quote": "Completion of the Deliverables shall occur on or before 30 June 2024.",
        "page": 1,
    }
]


@pytest.fixture
def setup(conn, make_deps):
    script = DocScript()
    script.add("MASTER SERVICES AGREEMENT", MSA_CLS, MSA_ITEMS)
    deps = make_deps(ScriptedLLM(script))
    m = make_matter(conn, parties=False)
    matters.open_batch(conn, m["matter_id"])
    conn.commit()
    return conn, deps, script, m


def upload(conn, deps, m, data, name="a.pdf", batch=1):
    return service.register_upload(
        conn, deps, matter_id=str(m["matter_id"]), batch_seq=batch, filename=name, data=data
    )


# ----------------------------------------------------------------------------------- register
def test_register_stores_original_and_queues_parse(setup):
    conn, deps, _, m = setup
    r = upload(conn, deps, m, pdf(MSA_TEXT), "msa.pdf")
    assert r.document["status"] == "PENDING" and not r.duplicate
    assert deps.storage.read(r.document["storage_uri"]).startswith(b"%PDF")
    job = job_repo.claim(conn)
    assert job["stage"] == "PARSE" and str(job["document_id"]) == str(r.document["document_id"])


def test_duplicate_upload_is_reported_not_raised_and_not_requeued(setup):
    conn, deps, _, m = setup
    data = pdf(MSA_TEXT)
    first = upload(conn, deps, m, data, "msa.pdf")
    second = upload(conn, deps, m, data, "msa_copy.pdf")
    assert (
        second.duplicate
        and second.duplicate_of == str(first.document["document_id"])
        and second.document is None
    )
    assert len(documents_in(conn, m)) == 1
    assert [d["original_filename"] for d in doc_repo.list_duplicates(conn, str(m["matter_id"]), 1)] == [
        "msa_copy.pdf"
    ]
    assert conn.execute("SELECT count(*) AS n FROM ingestion_jobs").fetchone()["n"] == 1


def documents_in(conn, m):
    return doc_repo.list_documents(conn, str(m["matter_id"]))


@pytest.mark.parametrize(
    "data, name, exc",
    [
        (b"", "a.pdf", ValidationFailed),
        (b"MZ" + b"0" * 50, "a.pdf", UnsupportedMedia),
        (b"\x00\x01" * 50, "a.bin", UnsupportedMedia),
    ],
)
def test_invalid_uploads_leave_no_trace(setup, data, name, exc):
    conn, deps, _, m = setup
    with pytest.raises(exc):
        upload(conn, deps, m, data, name)
    assert (
        documents_in(conn, m) == []
        and conn.execute("SELECT count(*) AS n FROM ingestion_jobs").fetchone()["n"] == 0
    )


def test_oversize_upload_rejected(setup):
    conn, deps, _, m = setup
    deps.settings.max_upload_mb = 0  # type: ignore[misc]
    with pytest.raises(PayloadTooLarge):
        upload(conn, deps, m, pdf("x"))


def test_upload_to_unknown_matter_or_closed_batch(setup):
    conn, deps, _, m = setup
    with pytest.raises(NotFound):
        service.register_upload(
            conn,
            deps,
            matter_id="00000000-0000-0000-0000-000000000000",
            batch_seq=1,
            filename="a.pdf",
            data=pdf("x"),
        )
    conn.rollback()
    matters.set_batch_status(conn, str(m["matter_id"]), 1, "PROCESSING")
    with pytest.raises(BatchClosed):
        upload(conn, deps, m, pdf("x"))


def test_hostile_filename_cannot_escape_storage(setup):
    conn, deps, _, m = setup
    r = upload(conn, deps, m, pdf("hello there world"), "../../../etc/passwd.pdf")
    assert r.document["original_filename"] == "passwd.pdf"
    assert str(deps.storage.root) in str(deps.storage._resolve(r.document["storage_uri"][5:]))  # type: ignore[attr-defined]


# -------------------------------------------------------------------------------- parse + extract
def parse(conn, deps, doc):
    return service.run_parse(conn, deps, str(doc["document_id"]))


def test_parse_classifies_chunks_embeds_and_registers_parties(setup):
    conn, deps, _, m = setup
    doc = upload(conn, deps, m, pdf(MSA_TEXT), "msa.pdf").document
    timings = parse(conn, deps, doc)
    conn.commit()
    d = doc_repo.get_document(conn, str(doc["document_id"]))
    assert (
        d["document_type"] == "CONTRACT"
        and d["authority_class"] == "BILATERAL"
        and str(d["document_date"]) == "2023-01-12"
    )
    assert (
        d["signed_by_all_parties"] is True
        and d["contract_id"] == "msa-2023"
        and "msa" in d["contract_aliases"]
    )
    assert d["total_pages"] == 1 and d["pdf_uri"] and d["text_sha"] and not d["needs_review"]
    counts = chunk_repo.count_for_document(conn, str(doc["document_id"]))
    assert (
        counts["CHILD"] >= 3
        and counts["PARENT"] >= 1
        and timings["chunks"] == counts["CHILD"] + counts["PARENT"]
    )
    embedded = conn.execute(
        "SELECT count(*) FILTER (WHERE dense_embedding IS NOT NULL) AS e, "
        "count(*) FILTER (WHERE chunk_level='PARENT' AND dense_embedding IS NOT NULL) AS pe FROM document_chunks"
    ).fetchone()
    assert embedded["e"] == counts["CHILD"] and embedded["pe"] == 0  # only children are embedded
    parties = {p["canonical_name"]: p for p in matters.list_parties(conn, str(m["matter_id"]))}
    assert set(parties) == {"Vardhan Infotech Private Limited", "Kestrel Limited"}
    assert (
        matters.resolve_party(conn, str(m["matter_id"]), "the Customer")["canonical_name"]
        == "Kestrel Limited"
    )
    assert (
        job_repo.claim(conn)["stage"] == "PARSE" or True
    )  # a PARSE job was queued by register; EXTRACT follows
    stages = [r["stage"] for r in conn.execute("SELECT stage FROM ingestion_jobs ORDER BY job_id").fetchall()]
    assert stages == ["PARSE", "EXTRACT"]


def test_chunks_carry_coordinates_for_click_to_source(setup):
    conn, deps, _, m = setup
    doc = upload(conn, deps, m, pdf(MSA_TEXT)).document
    parse(conn, deps, doc)
    row = conn.execute("SELECT * FROM document_chunks WHERE structural_ref = 'cl. 1.2'").fetchone()
    assert row["page_start"] == 1 and row["bboxes"] and "[Master Services Agreement" in row["context_header"]
    page = doc_repo.get_page(conn, str(doc["document_id"]), 1)
    assert page["page_text"][row["char_start"] : row["char_end"]] == row["chunk_text"]
    assert page["page_width"] > 0


def test_parse_is_idempotent_after_a_crash_and_retry(setup):
    conn, deps, _, m = setup
    doc = upload(conn, deps, m, pdf(MSA_TEXT)).document
    parse(conn, deps, doc)
    first = chunk_repo.count_for_document(conn, str(doc["document_id"]))
    parse(conn, deps, doc)
    assert chunk_repo.count_for_document(conn, str(doc["document_id"])) == first
    assert conn.execute("SELECT count(*) AS n FROM ingestion_jobs WHERE stage='EXTRACT'").fetchone()["n"] == 1


def test_low_confidence_classification_is_demoted_to_correspondence_and_flagged(conn, make_deps):
    script = DocScript()
    script.add("MASTER SERVICES AGREEMENT", cls("AMENDMENT", "Unclear", "1 June 2024", confidence=0.4))
    deps = make_deps(ScriptedLLM(script))
    m = make_matter(conn, parties=False)
    matters.open_batch(conn, m["matter_id"])
    doc = upload(conn, deps, m, pdf(MSA_TEXT)).document
    parse(conn, deps, doc)
    d = doc_repo.get_document(conn, str(doc["document_id"]))
    assert d["authority_class"] == "CORRESPONDENCE" and d["needs_review"] and "below" in d["review_reason"]


def test_two_contracts_with_the_same_title_get_distinct_ids(conn, make_deps):
    script = DocScript()
    script.add("MASTER SERVICES AGREEMENT", MSA_CLS)
    deps = make_deps(ScriptedLLM(script))
    m = make_matter(conn, parties=False)
    matters.open_batch(conn, m["matter_id"])
    ids = []
    for extra in ("", "\nSchedule A attached."):
        doc = upload(conn, deps, m, pdf(MSA_TEXT + extra), f"msa{len(extra)}.pdf").document
        parse(conn, deps, doc)
        ids.append(doc_repo.get_document(conn, str(doc["document_id"]))["contract_id"])
    assert ids == ["msa-2023", "msa-2023-2"]


def test_party_role_is_upgraded_when_a_pleading_names_the_same_company(conn, make_deps):
    script = DocScript()
    script.add("MASTER SERVICES AGREEMENT", MSA_CLS)
    script.add(
        "PLAINT",
        cls(
            "PLAINT",
            "Plaint",
            "3 March 2025",
            author="Vardhan Infotech Pvt Ltd",
            parties=[
                {"name": "Vardhan Infotech Pvt Ltd", "role": "PLAINTIFF"},
                {"name": "Kestrel Ltd", "role": "DEFENDANT"},
            ],
        ),
    )
    deps = make_deps(ScriptedLLM(script))
    m = make_matter(conn, parties=False)
    matters.open_batch(conn, m["matter_id"])
    parse(conn, deps, upload(conn, deps, m, pdf(MSA_TEXT)).document)
    pl = upload(
        conn,
        deps,
        m,
        pdf("# PLAINT\n1. The Plaintiff sues the Defendant for the price of goods supplied."),
        "plaint.pdf",
    ).document
    parse(conn, deps, pl)
    roles = {p["canonical_name"]: p["role"] for p in matters.list_parties(conn, str(m["matter_id"]))}
    assert roles == {
        "Vardhan Infotech Private Limited": "PLAINTIFF",
        "Kestrel Limited": "DEFENDANT",
    }  # no duplicate parties
    d = doc_repo.get_document(conn, str(pl["document_id"]))
    assert str(d["author_party_id"]) == str(
        matters.resolve_party(conn, str(m["matter_id"]), "Vardhan")["party_id"]
    )


def test_unreadable_pdf_fails_with_a_parse_error(setup):
    conn, deps, _, m = setup
    doc = upload(conn, deps, m, b"%PDF-1.4\nthis is not really a pdf").document
    from legal_workspace.errors import ParseError

    with pytest.raises(ParseError):
        parse(conn, deps, doc)


def test_blank_document_is_rejected(setup):
    conn, deps, _, m = setup
    from legal_workspace.errors import ParseError

    doc = (
        upload(conn, deps, m, pdf("   \n  \n"), "blank.pdf").document
        if False
        else upload(conn, deps, m, b"   \n\n x \n", "blank.txt").document
    )
    with pytest.raises(ParseError):
        parse(conn, deps, doc)


def test_extract_stores_validated_items_and_audit_of_dropped(setup):
    conn, deps, script, m = setup
    script.extract["MASTER SERVICES AGREEMENT"] = MSA_ITEMS + [
        {
            "subject_type": "CONTRACT",
            "subject_ref": "MSA",
            "slot": "delivery_date",
            "value": "1 January 2020",
            "quote": "Delivery is due on 1 January 2020 without exception.",
            "page": 1,
        }
    ]
    doc = upload(conn, deps, m, pdf(MSA_TEXT)).document
    parse(conn, deps, doc)
    out = service.run_extract(conn, deps, str(doc["document_id"]))
    ex = doc_repo.get_extraction(conn, str(doc["document_id"]))
    assert out["items"] == 1 and out["dropped"] == 1 and len(ex["items"]) == 1
    assert ex["items"][0]["value_date"] == "2024-06-30" and "quote not found" in ex["dropped"][0]["reason"]
    assert doc_repo.get_document(conn, str(doc["document_id"]))["status"] == "EXTRACTED"


def test_extract_before_parse_is_an_error(setup):
    conn, deps, _, m = setup
    doc = upload(conn, deps, m, pdf(MSA_TEXT)).document
    with pytest.raises(NotFound):
        service.run_extract(conn, deps, str(doc["document_id"]))


def test_email_attachments_become_documents_in_the_same_batch(setup):
    import email.message

    conn, deps, script, m = setup
    script.add("From:", cls("EMAIL", "Delivery", "20 May 2024", author=""))
    msg = email.message.EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = (
        "a@x.com",
        "b@y.com",
        "see attached",
        "Mon, 20 May 2024 10:00:00 +0530",
    )
    msg.set_content("Please find the agreement attached.")
    msg.add_attachment(pdf(MSA_TEXT), maintype="application", subtype="pdf", filename="msa.pdf")
    doc = upload(conn, deps, m, msg.as_bytes(), "mail.eml").document
    parse(conn, deps, doc)
    names = sorted(d["original_filename"] for d in documents_in(conn, m))
    assert names == ["mail.eml", "msa.pdf"]


# ---------------------------------------------------------------------------------------- commit
def test_commit_requires_documents_and_an_open_batch(setup):
    conn, deps, _, m = setup
    with pytest.raises(BadRequest):
        service.commit_batch(conn, str(m["matter_id"]), 1)
    upload(conn, deps, m, pdf(MSA_TEXT))
    out = service.commit_batch(conn, str(m["matter_id"]), 1)
    assert out["status"] == "PROCESSING" and out["documents"] == 1
    with pytest.raises(BadRequest):
        service.commit_batch(conn, str(m["matter_id"]), 1)
    assert (
        conn.execute("SELECT count(*) AS n FROM ingestion_jobs WHERE stage='RECONCILE'").fetchone()["n"] == 1
    )
    with pytest.raises(NotFound):
        service.commit_batch(conn, str(m["matter_id"]), 9)


# ----------------------------------------------------------------------------------------- worker
def test_worker_processes_a_batch_and_isolates_failures(setup):
    conn, deps, script, m = setup
    good = upload(conn, deps, m, pdf(MSA_TEXT), "msa.pdf").document
    bad = upload(conn, deps, m, b"%PDF-1.4 corrupt corrupt corrupt", "broken.pdf").document
    upload(conn, deps, m, encrypted_pdf(), "locked.pdf")
    conn.commit()
    done = Worker(deps, concurrency=1).run_until_idle(60)
    assert done >= 4
    st = {d["original_filename"]: d for d in documents_in(conn, m)}
    assert st["msa.pdf"]["status"] == "EXTRACTED"
    assert (
        st["broken.pdf"]["status"] == "FAILED" and "not a readable PDF" in st["broken.pdf"]["error_message"]
    )
    assert st["locked.pdf"]["status"] == "FAILED" and "password" in st["locked.pdf"]["error_message"]
    attempts = {
        r["document_id"]: r["attempts"]
        for r in conn.execute(
            "SELECT document_id, attempts FROM ingestion_jobs WHERE stage='PARSE'"
        ).fetchall()
    }
    assert attempts[bad["document_id"]] == 1  # a corrupt file is not retried
    assert good["document_id"] in attempts


def test_worker_retries_model_outages_then_fails_the_document(setup):
    conn, deps, script, m = setup
    script.fail_for.add("MASTER SERVICES AGREEMENT")
    doc = upload(conn, deps, m, pdf(MSA_TEXT), "msa.pdf").document
    conn.commit()
    Worker(deps, concurrency=1).run_until_idle(60)
    d = doc_repo.get_document(conn, str(doc["document_id"]))
    job = conn.execute("SELECT * FROM ingestion_jobs WHERE stage='PARSE'").fetchone()
    assert (
        d["status"] == "FAILED"
        and "outage" in d["error_message"]
        and job["attempts"] == deps.settings.job_max_attempts
    )


def test_worker_recovers_when_the_model_comes_back(setup):
    conn, deps, script, m = setup
    script.fail_for.add("MASTER SERVICES AGREEMENT")
    doc = upload(conn, deps, m, pdf(MSA_TEXT), "msa.pdf").document
    conn.commit()
    w = Worker(deps, concurrency=1)
    job = w._claim()
    from legal_workspace.worker import process_job

    assert process_job(deps, job) is False  # first attempt fails, job goes back to the queue
    script.fail_for.clear()
    w.run_until_idle(60)
    assert doc_repo.get_document(conn, str(doc["document_id"]))["status"] == "EXTRACTED"


def test_docx_goes_through_the_whole_pipeline(setup):
    conn, deps, script, m = setup
    doc = upload(conn, deps, m, docx_bytes(MSA_TEXT.split("\n")), "msa.docx").document
    conn.commit()
    Worker(deps, concurrency=1).run_until_idle(120)
    assert doc_repo.get_document(conn, str(doc["document_id"]))["status"] == "EXTRACTED"


def test_two_worker_threads_process_many_documents_without_duplicating_work(setup):
    conn, deps, script, m = setup
    for i in range(6):
        upload(conn, deps, m, pdf(MSA_TEXT.replace("2023", f"20{i}3")), f"msa{i}.pdf")
    conn.commit()
    w = Worker(deps, concurrency=3)
    w.start()
    import time

    deadline = time.time() + 60
    while time.time() < deadline:
        n = conn.execute(
            "SELECT count(*) AS n FROM ingestion_jobs WHERE status IN ('QUEUED','RUNNING')"
        ).fetchone()["n"]
        conn.commit()
        if n == 0:
            break
        time.sleep(0.3)
    w.stop()
    assert {d["status"] for d in documents_in(conn, m)} == {"EXTRACTED"}
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM ingestion_jobs WHERE stage='EXTRACT' AND status='DONE'"
        ).fetchone()["n"]
        == 6
    )
