"""S09: the HTTP API end to end: validation, errors, uploads, queries, documents, review, roles, limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from legal_workspace.config import get_settings
from legal_workspace.worker import Worker
from tests.conftest import DATA_DIR

pytestmark = pytest.mark.db
M2 = DATA_DIR / "synthetic" / "M2"
V1 = "/api/v1"


def upload(api, mid, batch, paths):
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in paths]
    return api.post(f"{V1}/matters/{mid}/batches/{batch}/documents", files=files)


@pytest.fixture
def matter(api):
    r = api.post(
        f"{V1}/matters",
        json={
            "matter_number": "CS(COMM) 412/2025",
            "title": "Vardhan v Kestrel",
            "matter_type": "PAYMENT_RECOVERY",
            "forum": "High Court of Delhi",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def run_batch(api, mid, batch):
    r = api.post(f"{V1}/matters/{mid}/batches", json={"label": f"batch {batch}"})
    assert r.status_code == 201 and r.json()["batch_seq"] == batch
    paths = sorted((M2 / f"batch{batch}").glob("*.pdf"))
    u = upload(api, mid, batch, paths)
    assert u.status_code == 202, u.text
    c = api.post(f"{V1}/matters/{mid}/batches/{batch}/commit")
    assert c.status_code == 202, c.text
    Worker(api.deps, concurrency=1).run_until_idle(120)
    return u.json()


@pytest.fixture
def full(api, matter, corpus):
    mid = matter["matter_id"]
    run_batch(api, mid, 1)
    run_batch(api, mid, 2)
    api.deps.settings.workspace_today = None
    return mid


# ------------------------------------------------------------------------------------------ system
def test_health_live_ready_metrics_docs(api):
    assert api.get(f"{V1}/healthz/live").json() == {"status": "alive"}
    h = api.get(f"{V1}/healthz")
    assert (
        h.status_code == 200
        and h.json()["checks"]["database"]["ok"] is True
        and h.json()["mode"]["llm_provider"] in ("fixture", "ollama")
    )
    m = api.get("/metrics")
    assert m.status_code == 200 and "lw_http_requests_total" in m.text
    assert api.get("/api/openapi.json").json()["info"]["title"] == "Legal Workspace API"
    assert api.get(f"{V1}/version").json()["version"]


def test_request_id_is_generated_echoed_and_security_headers_are_set(api):
    r = api.get(f"{V1}/healthz/live")
    assert (
        len(r.headers["x-request-id"]) >= 8
        and r.headers["x-content-type-options"] == "nosniff"
        and r.headers["cache-control"] == "no-store"
    )
    assert (
        api.get(f"{V1}/healthz/live", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )


def test_errors_are_problem_json_with_the_request_id(api):
    r = api.get(f"{V1}/nothing-here", headers={"X-Request-ID": "rid-1"})
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "not_found" and body["request_id"] == "rid-1" and body["status"] == 404
    assert api.post(f"{V1}/healthz/live").status_code == 405


def test_unhandled_errors_do_not_leak_internals(api, monkeypatch):
    from legal_workspace.api.routes import system

    def boom():
        raise RuntimeError("secret database password is hunter2")

    monkeypatch.setattr(system, "live", boom, raising=True)
    api.app_ref.router.routes  # noqa: B018 - make sure routes are resolved
    from legal_workspace.api.routes.matters import list_matters  # noqa: F401

    monkeypatch.setattr(
        "legal_workspace.db.matters.list_matters",
        lambda conn: (_ for _ in ()).throw(RuntimeError("secret database password is hunter2")),
    )
    r = api.get(f"{V1}/matters")
    assert (
        r.status_code == 500
        and "hunter2" not in r.text
        and r.json()["code"] == "internal_error"
        and r.json()["request_id"]
    )


# ------------------------------------------------------------------------------------------ matters
def test_matter_validation_errors_are_clear_and_field_specific(api):
    r = api.post(f"{V1}/matters", json={"matter_number": "", "title": "t", "matter_type": "CRIMINAL"})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} >= {
        "matter_number",
        "matter_type",
    }
    assert api.post(f"{V1}/matters", json={}).status_code == 422
    assert (
        api.post(
            f"{V1}/matters", content="not json", headers={"content-type": "application/json"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            f"{V1}/matters",
            json={
                "matter_number": "x",
                "title": "t",
                "matter_type": "BREACH",
                "parties": [{"name": "A", "role": "KING"}],
            },
        ).status_code
        == 422
    )


def test_matter_crud_and_conflicts(api, matter):
    mid = matter["matter_id"]
    assert (
        api.post(
            f"{V1}/matters",
            json={"matter_number": matter["matter_number"], "title": "dup", "matter_type": "BREACH"},
        ).status_code
        == 409
    )
    got = api.get(f"{V1}/matters/{mid}").json()
    assert got["title"] == "Vardhan v Kestrel" and got["latest_batch"] == 0
    assert [m["matter_id"] for m in api.get(f"{V1}/matters").json()] == [mid]
    assert api.get(f"{V1}/matters/00000000-0000-0000-0000-000000000000").status_code == 404
    assert api.get(f"{V1}/matters/not-a-uuid").status_code == 422


def test_parties_can_be_declared_up_front(api):
    r = api.post(
        f"{V1}/matters",
        json={
            "matter_number": "P/1",
            "title": "t",
            "matter_type": "BREACH",
            "parties": [{"name": "Alpha Ltd", "role": "PLAINTIFF", "aliases": ["Alpha"]}],
        },
    )
    mid = r.json()["matter_id"]
    assert [p["canonical_name"] for p in api.get(f"{V1}/matters/{mid}/parties").json()] == ["Alpha Ltd"]
    assert (
        api.post(f"{V1}/matters/{mid}/parties", json={"name": "Beta Ltd", "role": "DEFENDANT"}).status_code
        == 201
    )


# ------------------------------------------------------------------------------------------ uploads
def test_only_one_batch_may_be_open_and_commit_needs_documents(api, matter):
    mid = matter["matter_id"]
    assert api.post(f"{V1}/matters/{mid}/batches").status_code == 201
    assert api.post(f"{V1}/matters/{mid}/batches").status_code == 409
    assert (
        api.post(f"{V1}/matters/{mid}/batches/1/commit").status_code == 422
        or api.post(f"{V1}/matters/{mid}/batches/1/commit").status_code == 400
    )
    assert api.get(f"{V1}/matters/{mid}/batches/9").status_code == 404


def test_upload_accepts_duplicates_and_rejections_are_reported_per_file(api, matter):
    mid = matter["matter_id"]
    api.post(f"{V1}/matters/{mid}/batches")
    f1 = M2 / "batch1" / "01_Master_Services_Agreement.pdf"
    r = api.post(
        f"{V1}/matters/{mid}/batches/1/documents",
        files=[
            ("files", ("msa.pdf", f1.read_bytes(), "application/pdf")),
            ("files", ("msa_again.pdf", f1.read_bytes(), "application/pdf")),
            ("files", ("virus.pdf", b"MZ\x90\x00" + b"0" * 64, "application/pdf")),
            ("files", ("empty.pdf", b"", "application/pdf")),
            ("files", ("../../etc/passwd", b"plain text", "text/plain")),
        ],
    )
    body = r.json()
    assert r.status_code == 202
    assert [a["filename"] for a in body["accepted"]] == ["msa.pdf", "passwd"]
    assert [d["filename"] for d in body["duplicates"]] == ["msa_again.pdf"]
    assert {x["filename"]: x["code"] for x in body["rejected"]} == {
        "virus.pdf": "unsupported_media_type",
        "empty.pdf": "validation_failed",
    }


def test_upload_status_codes_when_nothing_is_accepted(api, matter):
    mid = matter["matter_id"]
    api.post(f"{V1}/matters/{mid}/batches")
    f1 = M2 / "batch1" / "01_Master_Services_Agreement.pdf"
    assert upload(api, mid, 1, [f1]).status_code == 202
    assert upload(api, mid, 1, [f1]).status_code == 409  # all duplicates
    bad = api.post(
        f"{V1}/matters/{mid}/batches/1/documents",
        files=[("files", ("x.exe", b"MZ" + b"0" * 50, "application/octet-stream"))],
    )
    assert bad.status_code == 415
    api.deps.settings.max_upload_mb = 0
    big = api.post(
        f"{V1}/matters/{mid}/batches/1/documents", files=[("files", ("big.txt", b"x" * 10, "text/plain"))]
    )
    assert big.status_code == 413
    api.deps.settings.max_upload_mb = 50
    assert api.post(f"{V1}/matters/{mid}/batches/1/documents").status_code == 422  # no files field


def test_cannot_upload_to_a_closed_or_unknown_batch(api, matter):
    mid = matter["matter_id"]
    api.post(f"{V1}/matters/{mid}/batches")
    f1 = M2 / "batch1" / "01_Master_Services_Agreement.pdf"
    upload(api, mid, 1, [f1])
    api.post(f"{V1}/matters/{mid}/batches/1/commit")
    r = upload(api, mid, 1, [M2 / "batch1" / "02_Email_thread_go_live_date.pdf"])
    assert r.status_code == 409 and r.json()["code"] == "batch_closed"
    assert upload(api, mid, 5, [f1]).status_code == 404


def test_batch_status_shows_documents_progress_and_reconcile(api, matter):
    mid = matter["matter_id"]
    api.post(f"{V1}/matters/{mid}/batches")
    upload(api, mid, 1, sorted((M2 / "batch1").glob("*.pdf")))
    queued = api.get(f"{V1}/matters/{mid}/batches/1").json()
    assert (
        queued["status"] == "OPEN"
        and queued["progress"]["QUEUED"] == 5
        and {d["current_step"] for d in queued["documents"]} == {"PARSE (queued)"}
    )
    api.post(f"{V1}/matters/{mid}/batches/1/commit")
    Worker(api.deps, concurrency=1).run_until_idle(120)
    done = api.get(f"{V1}/matters/{mid}/batches/1").json()
    assert (
        done["status"] == "COMMITTED"
        and done["reconcile"] == "DONE"
        and {d["status"] for d in done["documents"]} == {"PROCESSED"}
    )
    assert api.get(f"{V1}/matters/{mid}/batches/1/changes").status_code == 200


def test_changes_report_requires_a_committed_batch_and_has_a_text_form(api, matter):
    mid = matter["matter_id"]
    api.post(f"{V1}/matters/{mid}/batches")
    assert api.get(f"{V1}/matters/{mid}/batches/1/changes").status_code == 409
    full_mid = mid
    run_batch_after = None  # noqa: F841
    # finish batch 1 and 2 to render the report as text
    upload(api, mid, 1, sorted((M2 / "batch1").glob("*.pdf")))
    api.post(f"{V1}/matters/{mid}/batches/1/commit")
    Worker(api.deps, concurrency=1).run_until_idle(120)
    run_batch(api, full_mid, 2)
    t = api.get(f"{V1}/matters/{mid}/batches/2/changes?format=text")
    assert t.status_code == 200 and "WHAT CHANGED IN BATCH 2" in t.text and "NARROWED" in t.text
    assert api.get(f"{V1}/matters/{mid}/batches/2/changes?format=xml").status_code == 422


def test_failed_documents_can_be_retried_after_the_model_recovers(api, matter):
    from legal_workspace.adapters.llm import FixtureLLM
    from tests.conftest import HybridLLM  # noqa: F401

    mid = matter["matter_id"]
    api.post(f"{V1}/matters/{mid}/batches")
    upload(api, mid, 1, [M2 / "batch1" / "01_Master_Services_Agreement.pdf"])
    real = api.deps.llm
    api.deps.llm = FixtureLLM(
        records={"classify": {}, "extract": {}}
    )  # a model that knows nothing = outage for this document
    api.post(f"{V1}/matters/{mid}/batches/1/commit")
    Worker(api.deps, concurrency=1).run_until_idle(60)
    b = api.get(f"{V1}/matters/{mid}/batches/1").json()
    assert b["documents"][0]["status"] == "FAILED"
    assert api.get(f"{V1}/matters/{mid}/review-queue").json()["items"][0]["kind"] == "FAILED_DOCUMENT"
    assert (
        b["status"] == "COMMITTED"
    )  # the batch still commits; the failed file is listed, never silently ignored
    assert (
        api.post(f"{V1}/matters/{mid}/batches/1/retry").status_code == 400
    )  # nothing to retry in a committed batch
    api.deps.llm = real
    api.post(f"{V1}/matters/{mid}/batches")
    again = upload(
        api, mid, 2, [M2 / "batch1" / "01_Master_Services_Agreement.pdf"]
    )  # a failed file may be uploaded again
    assert again.status_code == 202 and not again.json()["duplicates"]
    api.post(f"{V1}/matters/{mid}/batches/2/commit")
    Worker(api.deps, concurrency=1).run_until_idle(60)
    assert api.get(f"{V1}/matters/{mid}/batches/2").json()["documents"][0]["status"] == "PROCESSED"
    assert api.get(f"{V1}/matters/{mid}/review-queue").json()["count"] == 0


# ------------------------------------------------------------------------------------------ queries
def test_views_return_verified_cited_sentences(api, full):
    for path in (
        "gist",
        "chronology",
        "claims",
        "directions",
        "evidence?q=notice",
        "legal?q=liquidated+damages",
    ):
        r = api.get(f"{V1}/matters/{full}/{path}")
        assert r.status_code == 200, (path, r.text)
        body = r.json()
        assert body["sentences"] and not body["unverified"], path
        assert body["as_of_batch_seq"] == 2
    assert api.get(f"{V1}/matters/{full}/gist?as_of=1").json()["as_of_batch_seq"] == 1
    assert api.get(f"{V1}/matters/{full}/gist?as_of=7").status_code == 422
    assert api.get(f"{V1}/matters/{full}/gist?as_of=0").status_code == 422
    d = api.get(f"{V1}/matters/{full}/directions?status=overdue&today=2025-10-20").json()
    assert d["sentences"] and all("OVERDUE" in s["text"] for s in d["sentences"])
    assert api.get(f"{V1}/matters/{full}/directions?status=bogus").status_code == 422


def test_claims_board_filters_by_party_and_carries_evidence(api, full):
    parties = {p["canonical_name"]: p["party_id"] for p in api.get(f"{V1}/matters/{full}/parties").json()}
    one = api.get(f"{V1}/matters/{full}/claims?party_id={parties['Kestrel Limited']}").json()
    assert one["sentences"] and {s["meta"]["party"] for s in one["sentences"]} == {"Kestrel Limited"}
    assert (
        api.get(f"{V1}/matters/{full}/claims?party_id=00000000-0000-0000-0000-000000000000").status_code
        == 404
    )
    allc = api.get(f"{V1}/matters/{full}/claims").json()
    assert set(allc["extras"]["by_party"]) >= {"Vardhan Infotech Private Limited", "Kestrel Limited"}


def test_ask_endpoint_validation_and_answers(api, full):
    r = api.post(f"{V1}/matters/{full}/ask", json={"question": "When is delivery due now?"})
    assert (
        r.status_code == 200
        and "31 Jul 2024" in " ".join(s["text"] for s in r.json()["answer_sentences"])
        and r.json()["trace_id"]
    )
    assert api.post(f"{V1}/matters/{full}/ask", json={"question": ""}).status_code == 422
    assert api.post(f"{V1}/matters/{full}/ask", json={"question": "x" * 2001}).status_code == 422
    assert (
        api.post(f"{V1}/matters/{full}/ask", json={"question": "hi", "as_of_batch_seq": 0}).status_code == 422
    )
    assert (
        api.post(f"{V1}/matters/{full}/ask", json={"question": "hi", "as_of_batch_seq": 9}).status_code == 422
    )
    assert (
        api.post(
            f"{V1}/matters/00000000-0000-0000-0000-000000000000/ask", json={"question": "hi"}
        ).status_code
        == 404
    )
    t = api.get(f"{V1}/traces/{r.json()['trace_id']}")
    assert t.status_code == 200 and t.json()["question"] == "When is delivery due now?"
    assert api.get(f"{V1}/traces/00000000-0000-0000-0000-000000000000").status_code == 404
    assert len(api.get(f"{V1}/matters/{full}/traces").json()) >= 1


def test_hearing_brief_json_and_markdown(api, full):
    j = api.post(f"{V1}/matters/{full}/hearing-brief", json={"today": "2025-10-20"})
    assert j.status_code == 200 and [s["n"] for s in j.json()["sections"]] == list(range(1, 9))
    md = api.post(f"{V1}/matters/{full}/hearing-brief?format=markdown", json={})
    assert (
        md.status_code == 200
        and md.headers["content-type"].startswith("text/markdown")
        and md.text.startswith("# Hearing brief")
    )
    assert api.post(f"{V1}/matters/{full}/hearing-brief", json={"as_of_batch_seq": 9}).status_code == 422


def test_hearing_brief_for_an_empty_matter_is_a_clear_error(api, matter):
    r = api.post(f"{V1}/matters/{matter['matter_id']}/hearing-brief", json={})
    assert r.status_code == 422 and "no committed batch" in r.json()["detail"]


def test_empty_matter_views_say_so_instead_of_failing(api, matter):
    mid = matter["matter_id"]
    for path in ("gist", "chronology", "claims", "directions", "evidence"):
        r = api.get(f"{V1}/matters/{mid}/{path}")
        assert r.status_code == 200 and r.json()["sentences"] == []
    assert api.post(f"{V1}/matters/{mid}/ask", json={"question": "anything"}).json()["not_found"]


def test_overview_numbers(api, full):
    o = api.get(f"{V1}/matters/{full}/overview?today=2025-10-20").json()
    assert (
        o["documents"] == 9
        and o["disputed"] == 2
        and o["overdue"] == 1
        and o["next_hearing"]["date"] == "2025-11-14"
        and o["latest_batch"] == 2
    )


def test_fact_listing_as_of_and_fact_detail_with_history(api, full):
    f1 = {f["fact_key"]: f for f in api.get(f"{V1}/matters/{full}/facts?as_of=1").json()["facts"]}
    f2 = {f["fact_key"]: f for f in api.get(f"{V1}/matters/{full}/facts").json()["facts"]}
    assert "direction/replication/due_date" not in f1 and "direction/replication/due_date" in f2
    assert (
        f1["contract/msa-2023/delivery_date"]["assertion_id"]
        != f2["contract/msa-2023/delivery_date"]["assertion_id"]
    )
    detail = api.get(f"{V1}/facts/{f1['contract/msa-2023/delivery_date']['assertion_id']}").json()
    assert [h["change_type"] for h in detail["history"]] == ["NEW", "SUPERSEDED"] and detail[
        "state"
    ] == "SUPERSEDED"
    assert api.get(f"{V1}/facts/00000000-0000-0000-0000-000000000000").status_code == 404


def test_legal_search_endpoint(api, conn, fixture_deps):
    from legal_workspace.corpus.loader import load_corpus

    load_corpus(conn, fixture_deps.embedder, DATA_DIR / "corpus" / "seed.yaml")
    conn.commit()
    r = api.get(f"{V1}/legal/search?q=penalty+stipulated+damages&tags=liquidated_damages,penalty&k=3")
    assert (
        r.status_code == 200
        and 1 <= len(r.json()) <= 3
        and r.json()[0]["verification_status"] == "UNVERIFIED"
    )
    assert api.get(f"{V1}/legal/search?q=x&k=999").status_code == 422


# ------------------------------------------------------------------------------------------ documents
def test_document_endpoints_serve_pdf_page_text_image_and_highlights(api, full):
    docs = api.get(f"{V1}/matters/{full}/batches/1").json()["documents"]
    msa = next(d for d in docs if d["title"] == "Master Services Agreement")
    did = msa["document_id"]
    meta = api.get(f"{V1}/documents/{did}").json()
    assert (
        meta["document_type"] == "CONTRACT"
        and meta["pages"][0]["page_number"] == 1
        and "storage_uri" not in meta
    )
    p = api.get(f"{V1}/documents/{did}/pdf")
    assert (
        p.status_code == 200
        and p.headers["content-type"] == "application/pdf"
        and p.content.startswith(b"%PDF")
    )
    page = api.get(f"{V1}/documents/{did}/pages/1").json()
    assert (
        "30 June 2024" in page["text"]
        and page["width"] > 0
        and any(c["structural_ref"] == "cl. 2.2" and c["bboxes"] for c in page["chunks"])
        and page["facts"]
    )
    img = api.get(f"{V1}/documents/{did}/pages/1/image")
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    hl = api.get(
        f"{V1}/documents/{did}/pages/1/highlight", params={"quote": "shall occur on or before 30 June 2024"}
    ).json()
    assert hl["found"] and hl["rects"] and all(r["x1"] > r["x0"] for r in hl["rects"])
    miss = api.get(
        f"{V1}/documents/{did}/pages/1/highlight",
        params={"quote": "a sentence that is not in the document at all"},
    ).json()
    assert miss["found"] is False
    assert api.get(f"{V1}/documents/{did}/pages/9").status_code == 404
    assert api.get(f"{V1}/documents/{did}/pages/9/image").status_code == 404
    assert api.get(f"{V1}/documents/{did}/pages/1/image?scale=99").status_code == 422
    assert api.get(f"{V1}/documents/{did}/pages/1/highlight", params={"quote": "x"}).status_code == 422
    assert api.get(f"{V1}/documents/00000000-0000-0000-0000-000000000000/pdf").status_code == 404


# ------------------------------------------------------------------------------------------ review
def test_review_flow_over_http(api, matter):
    from tests.integration.test_reconcile_edges import spec  # noqa: F401

    mid = matter["matter_id"]
    run_batch(api, mid, 1)
    run_batch(api, mid, 2)
    q = api.get(f"{V1}/matters/{mid}/review-queue").json()
    assert q["count"] >= 0
    facts = api.get(f"{V1}/matters/{mid}/facts").json()["facts"]
    disputed = next(f for f in facts if f["state"] == "DISPUTED")
    r = api.post(
        f"{V1}/facts/{disputed['assertion_id']}/review",
        json={"action": "CONFIRM", "reason": "checked the service record"},
    )
    assert r.status_code == 200 and r.json()["state"] == "DISPUTED"
    hist = api.get(f"{V1}/facts/{disputed['assertion_id']}").json()["history"]
    assert hist[-1]["rule_id"] == "MANUAL" and hist[-1]["reviewer"] == "local"
    assert (
        api.post(
            f"{V1}/facts/{disputed['assertion_id']}/review", json={"action": "NUKE", "reason": "x"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            f"{V1}/facts/{disputed['assertion_id']}/review", json={"action": "CONFIRM", "reason": ""}
        ).status_code
        == 422
    )
    assert (
        api.post(
            f"{V1}/facts/00000000-0000-0000-0000-000000000000/review",
            json={"action": "CONFIRM", "reason": "x"},
        ).status_code
        == 404
    )
    assert (
        api.post(
            f"{V1}/facts/{disputed['assertion_id']}/review",
            json={"action": "CORRECT_VALUE", "reason": "typo", "value": "banana"},
        ).status_code
        == 422
    )


# ------------------------------------------------------------------------------- auth, roles, limits
@pytest.fixture
def secured(api, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "jwt_secret", "unit-test-secret-with-32-chars-or-more!")
    monkeypatch.setattr(s, "auth_users", "root:rootpw:admin,lawyer:lawpw:analyst,intern:internpw:viewer")
    api.app_ref.state.login_limiter.reset()
    return api


def login(api, user, pw):
    return api.post(f"{V1}/auth/login", json={"username": user, "password": pw})


def hdr(api, user, pw):
    return {"Authorization": f"Bearer {login(api, user, pw).json()['access_token']}"}


def test_auth_is_off_by_default_and_reports_its_state(api):
    assert api.get(f"{V1}/auth/config").json() == {"enabled": False}
    assert api.get(f"{V1}/auth/me").json() == {"username": "local", "role": "admin"}


def test_login_logout_flow_and_bad_credentials(secured):
    assert secured.get(f"{V1}/auth/config").json() == {"enabled": True}
    assert secured.get(f"{V1}/matters").status_code == 401
    assert (
        login(secured, "root", "wrong").status_code == 401 and login(secured, "ghost", "x").status_code == 401
    )
    ok = login(secured, "lawyer", "lawpw").json()
    assert ok["role"] == "analyst" and ok["token_type"] == "bearer"
    assert secured.get(f"{V1}/auth/me", headers={"Authorization": f"Bearer {ok['access_token']}"}).json() == {
        "username": "lawyer",
        "role": "analyst",
    }
    assert secured.get(f"{V1}/healthz/live").status_code == 200  # health stays public


def test_tampered_expired_and_foreign_tokens_are_rejected(secured):
    good = login(secured, "root", "rootpw").json()["access_token"]
    s = get_settings()
    bad = [
        good[:-3] + "abc",
        jwt.encode(
            {"sub": "root", "role": "admin", "exp": datetime.now(UTC) - timedelta(minutes=1)},
            s.jwt_secret,
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": "root", "role": "admin", "exp": datetime.now(UTC) + timedelta(minutes=5)},
            "another-secret-another-secret-123456",
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": "root", "role": "superuser", "exp": datetime.now(UTC) + timedelta(minutes=5)},
            s.jwt_secret,
            algorithm="HS256",
        ),
        jwt.encode({"sub": "root", "role": "admin"}, s.jwt_secret, algorithm="HS256"),  # no expiry
        "not.a.jwt",
    ]
    for t in bad:
        r = secured.get(f"{V1}/matters", headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 401, t
    assert secured.get(f"{V1}/matters", headers={"Authorization": "Basic abc"}).status_code == 401


def test_roles_are_enforced(secured):
    viewer, analyst, admin = (
        hdr(secured, "intern", "internpw"),
        hdr(secured, "lawyer", "lawpw"),
        hdr(secured, "root", "rootpw"),
    )
    new = {"matter_number": "R/1", "title": "t", "matter_type": "BREACH"}
    assert secured.post(f"{V1}/matters", json=new, headers=viewer).status_code == 403
    r = secured.post(f"{V1}/matters", json=new, headers=analyst)
    assert r.status_code == 201
    mid = r.json()["matter_id"]
    assert secured.get(f"{V1}/matters/{mid}", headers=viewer).status_code == 200
    assert secured.post(f"{V1}/matters/{mid}/batches", headers=viewer).status_code == 403
    assert secured.delete(f"{V1}/matters/{mid}", headers=analyst).status_code == 403
    assert secured.get(f"{V1}/audit", headers=analyst).status_code == 403
    assert (
        secured.post(f"{V1}/matters/{mid}/ask", json={"question": "hello"}, headers=viewer).status_code == 200
    )  # viewers may ask
    log = secured.get(f"{V1}/audit", headers=admin).json()
    assert {e["action"] for e in log} >= {"matter.create", "ask"} and {e["actor"] for e in log} >= {
        "lawyer",
        "intern",
    }
    assert secured.delete(f"{V1}/matters/{mid}", headers=admin).status_code == 204
    assert secured.get(f"{V1}/matters/{mid}", headers=admin).status_code == 404


def test_login_is_rate_limited_per_user_and_address(secured, monkeypatch):
    monkeypatch.setattr(
        secured.app_ref.state,
        "login_limiter",
        __import__("legal_workspace.api.security", fromlist=["RateLimiter"]).RateLimiter(3),
    )
    codes = [login(secured, "root", "nope").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    r = login(secured, "root", "nope")
    assert r.headers["retry-after"] and r.json()["code"] == "rate_limited"


def test_page_images_accept_a_query_token_for_img_tags(secured):
    admin = hdr(secured, "root", "rootpw")
    secured.post(
        f"{V1}/matters", json={"matter_number": "I/1", "title": "t", "matter_type": "BREACH"}, headers=admin
    )
    token = admin["Authorization"].split()[1]
    assert secured.get(f"{V1}/matters?access_token={token}").status_code == 200
    assert secured.get(f"{V1}/matters?access_token=junk").status_code == 401


def test_api_rate_limit_returns_429_with_retry_after(api, monkeypatch):
    from legal_workspace.api.security import RateLimiter

    monkeypatch.setattr(api.app_ref.state, "limiter", RateLimiter(5))
    codes = [api.get(f"{V1}/version").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}
    r = api.get(f"{V1}/version")
    assert r.headers["retry-after"] and r.json()["code"] == "rate_limited"


def test_deleting_a_matter_removes_its_stored_files(api, matter):
    mid = matter["matter_id"]
    api.post(f"{V1}/matters/{mid}/batches")
    upload(api, mid, 1, [M2 / "batch1" / "01_Master_Services_Agreement.pdf"])
    root = api.deps.storage.root / "matters" / mid
    assert root.exists() and any(root.iterdir())
    assert api.delete(f"{V1}/matters/{mid}").status_code == 204
    assert not root.exists()
    assert api.delete(f"{V1}/matters/{mid}").status_code == 404
