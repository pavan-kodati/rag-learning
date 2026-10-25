"""S05: reconciliation edge cases, negative paths and the review queue. Small invented matters, real database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from legal_workspace.db import matters as matter_repo
from legal_workspace.errors import BadRequest, Conflict, NotFound, ValidationFailed
from legal_workspace.eval import replay
from legal_workspace.memory import queries, review
from legal_workspace.memory.reconcile import reconcile_batch
from legal_workspace.synthetic.spec import Doc, I, Matter, Party

pytestmark = pytest.mark.db

PARTIES = [
    Party("a", "Alpha Traders Private Limited", "PLAINTIFF", ["Alpha", "the Seller"]),
    Party("b", "Beta Industries Limited", "DEFENDANT", ["Beta", "the Buyer"]),
]
TERMS = [("the Seller", "a"), ("the Buyer", "b")]
SUP = "the Supply Agreement"
KEY_DELIVERY = "contract/supply-agreement-2024/delivery_date"


def spec(docs, mtype="BREACH"):
    return Matter("T", "T/1/2025", "Alpha v Beta", mtype, "High Court of Delhi", PARTIES, docs)


CONTRACT_TXT = """# SUPPLY AGREEMENT
This Agreement is made on 1 January 2024 between Alpha Traders Private Limited (the Seller) and Beta Industries Limited (the Buyer).
1. DELIVERY
1.1 The Seller shall deliver the goods on or before 31 March 2024.
2. PRICE
2.1 The price is Rs. 10,00,000.
Signed by Alpha Traders Private Limited
Signed by Beta Industries Limited
"""


def contract(batch=1):
    return Doc(
        "c.pdf",
        batch,
        "CONTRACT",
        "Supply Agreement",
        "1 January 2024",
        CONTRACT_TXT,
        signed=True,
        suit_roles=False,
        terms=TERMS,
        items=[
            I(
                "CONTRACT",
                "Supply Agreement",
                "delivery_date",
                "31 March 2024",
                "The Seller shall deliver the goods on or before 31 March 2024",
            ),
            I(
                "CONTRACT",
                "Supply Agreement",
                "contract_value",
                "Rs. 10,00,000",
                "The price is Rs. 10,00,000",
            ),
        ],
    )


def amendment(
    file,
    batch,
    date_text,
    delivery,
    *,
    signed=True,
    title="AMENDMENT TO SUPPLY AGREEMENT",
    ref=SUP,
    amends="the Supply Agreement dated 1 January 2024",
):
    txt = (
        f"# {title}\nThis Amendment is made on {date_text} between Alpha Traders Private Limited and Beta Industries Limited.\n"
        f"1. The delivery date under the Supply Agreement is substituted by {delivery}.\n"
        + (
            "Signed by Alpha Traders Private Limited\nSigned by Beta Industries Limited\n"
            if signed
            else "Draft for discussion only\n"
        )
    )
    return Doc(
        file,
        batch,
        "AMENDMENT",
        title.title(),
        date_text,
        txt,
        signed=signed,
        suit_roles=False,
        amends=amends,
        items=[
            I(
                "CONTRACT",
                ref,
                "delivery_date",
                delivery,
                f"The delivery date under the Supply Agreement is substituted by {delivery}",
            )
        ],
    )


def current(sc, key=KEY_DELIVERY):
    return [f for f in sc.facts(key, evidence=False) if f["ended_in_batch_seq"] is None]


# ---------------------------------------------------------------------------------------- ordering
def test_two_amendments_in_one_batch_apply_in_date_order_not_upload_order(scenario):
    sc = scenario(
        spec(
            [
                contract(),
                amendment("a1.pdf", 1, "1 July 2024", "30 September 2024"),
                amendment("a2.pdf", 1, "10 May 2024", "31 July 2024", title="ADDENDUM TO SUPPLY AGREEMENT"),
            ]
        )
    )
    sc.run(1)
    cur = current(sc)
    assert len(cur) == 1 and cur[0]["value_date"] == date(2024, 9, 30)
    chain = {(f["value_date"], f["state"]) for f in sc.facts(KEY_DELIVERY, evidence=False)}
    assert chain == {
        (date(2024, 3, 31), "SUPERSEDED"),
        (date(2024, 7, 31), "SUPERSEDED"),
        (date(2024, 9, 30), "ACTIVE"),
    }


def test_an_older_amendment_arriving_later_is_born_superseded_and_never_overrides(scenario):
    sc = scenario(
        spec(
            [
                contract(),
                amendment("a1.pdf", 1, "1 July 2024", "30 September 2024"),
                amendment("a2.pdf", 2, "10 May 2024", "31 July 2024", title="ADDENDUM TO SUPPLY AGREEMENT"),
            ]
        )
    )
    sc.run(1)
    report = sc.run(2)
    cur = current(sc)
    assert [f["value_date"] for f in cur] == [date(2024, 9, 30)]
    late = next(f for f in sc.facts(KEY_DELIVERY) if f["value_date"] == date(2024, 7, 31))
    assert late["state"] == "SUPERSEDED" and late["learned_in_batch_seq"] == late["ended_in_batch_seq"] == 2
    assert any(c["change_type"] == "NEW" and c["rule_id"] == "R2" for c in report["changes"])


def test_unsigned_amendment_is_evidence_only_and_does_not_change_the_term(scenario):
    sc = scenario(
        spec([contract(), amendment("a1.pdf", 1, "1 July 2024", "30 September 2024", signed=False)])
    )
    sc.run(1)
    assert [f["value_date"] for f in current(sc)] == [date(2024, 3, 31)]
    ev = sc.facts(KEY_DELIVERY, evidence=True)
    assert len(ev) == 1 and ev[0]["value_date"] == date(2024, 9, 30)


# ----------------------------------------------------------------------------- ambiguity and doubt
def test_ambiguous_contract_reference_is_stored_and_flagged_not_guessed(scenario):
    sow = Doc(
        "sow.pdf",
        1,
        "SOW",
        "Statement of Work",
        "1 February 2024",
        "# STATEMENT OF WORK\n1. DELIVERY\n1.1 Go-live is 30 April 2024.\n"
        "Signed by Alpha Traders Private Limited\nSigned by Beta Industries Limited\n",
        signed=True,
        suit_roles=False,
        terms=TERMS,
        items=[
            I("CONTRACT", "Statement of Work", "delivery_date", "30 April 2024", "Go-live is 30 April 2024")
        ],
    )
    vague = Doc(
        "e.pdf",
        1,
        "EMAIL",
        "Delivery",
        "5 March 2024",
        "From: a@x.example\nSubject: Delivery\nThe delivery under the Agreement is now 15 May 2024.\n",
        suit_roles=False,
        items=[
            I(
                "CONTRACT",
                "the Agreement",
                "delivery_date",
                "15 May 2024",
                "The delivery under the Agreement is now 15 May 2024",
            )
        ],
    )
    sc = scenario(spec([contract(), sow, vague]))
    sc.run(1)
    rows = sc.facts("contract/unresolved-the-agreement/delivery_date")
    assert len(rows) == 1 and rows[0]["needs_review"] and "the Agreement" in rows[0]["review_reason"]
    assert [f["value_date"] for f in current(sc)] == [
        date(2024, 3, 31)
    ]  # the real contract term is untouched


def test_uncertain_document_type_demotes_authority_and_sends_facts_to_review(scenario):
    a = amendment(
        "a1.pdf", 1, "1 July 2024", "30 September 2024", title="SUPPLEMENTAL TERMS"
    )  # no title keyword: only the model speaks
    a.confidence = 0.4
    sc = scenario(spec([contract(), a]))
    sc.run(1)
    assert [f["value_date"] for f in current(sc)] == [
        date(2024, 3, 31)
    ]  # a CORRESPONDENCE-class document cannot supersede
    ev = sc.facts(KEY_DELIVERY, evidence=True)
    assert len(ev) == 1 and ev[0]["needs_review"] and "uncertain" in ev[0]["review_reason"]
    doc = sc.conn.execute(
        "SELECT authority_class, needs_review FROM documents WHERE original_filename = 'a1.pdf'"
    ).fetchone()
    assert doc["authority_class"] == "CORRESPONDENCE" and doc["needs_review"]
    items = review.list_items(sc.conn, sc.mid)
    assert {i["kind"] for i in items} >= {"FACT", "DOCUMENT"}


def test_conflicting_values_from_equal_authority_documents_are_disputed_for_review(scenario):
    inv1 = Doc(
        "i1.pdf",
        1,
        "INVOICE",
        "Tax Invoice INV-7",
        "1 March 2024",
        "# TAX INVOICE\nInvoice No. INV-7\nInvoice amount: Rs. 1,00,000\n",
        suit_roles=False,
        items=[I("INVOICE", "INV-7", "invoice_amount", "Rs. 1,00,000", "Invoice amount: Rs. 1,00,000")],
    )
    inv2 = Doc(
        "i2.pdf",
        1,
        "INVOICE",
        "Tax Invoice INV-7 (re-issued)",
        "5 March 2024",
        "# TAX INVOICE\nInvoice No. INV-7\nInvoice amount: Rs. 2,00,000\n",
        suit_roles=False,
        items=[I("INVOICE", "INV-7", "invoice_amount", "Rs. 2,00,000", "Invoice amount: Rs. 2,00,000")],
    )
    sc = scenario(spec([inv1, inv2]))
    sc.run(1)
    rows = sc.facts("invoice/inv-7/invoice_amount")
    assert {r["state"] for r in rows} == {"DISPUTED"} and all(r["needs_review"] for r in rows)
    assert {i["fact_key"] for i in review.list_items(sc.conn, sc.mid) if i["kind"] == "FACT"} == {
        "invoice/inv-7/invoice_amount"
    }


# ------------------------------------------------------------------------------ batches and failures
def test_a_failed_document_does_not_block_the_batch_and_is_reported(scenario):
    sc = scenario(spec([contract()]))
    files = [
        ("c.pdf", sc.files["c.pdf"]),
        ("broken.pdf", b"%PDF-1.4 this is not a pdf at all, sorry"),
        ("empty.txt", b"  \n "),
    ]
    report, uploads, _ = replay.replay_files(sc.conn, sc.deps, sc.mid, 1, files)
    assert report["documents_processed"] == 1
    failed = {f["title"]: f["error"] for f in report["documents_failed"]}
    assert "broken.pdf" in failed and "not a readable PDF" in failed["broken.pdf"] and "empty.txt" in failed
    assert matter_repo.latest_committed_seq(sc.conn, sc.mid) == 1
    kinds = {i["kind"] for i in review.list_items(sc.conn, sc.mid)}
    assert "FAILED_DOCUMENT" in kinds


def test_reconciling_twice_is_idempotent(scenario):
    sc = scenario(spec([contract()]))
    sc.run(1)
    before = sc.conn.execute("SELECT count(*) AS n FROM matter_fact_assertions").fetchone()["n"]
    assert reconcile_batch(sc.conn, sc.deps, sc.mid, 1) == {"already_committed": True}
    assert sc.conn.execute("SELECT count(*) AS n FROM matter_fact_assertions").fetchone()["n"] == before


def test_a_document_with_no_extractable_facts_is_processed_without_error(scenario):
    blank = Doc(
        "n.pdf",
        1,
        "LETTER",
        "Covering note",
        "2 March 2024",
        "# COVERING NOTE\nPlease find the documents enclosed. Regards.\n",
        suit_roles=False,
        items=[],
    )
    sc = scenario(spec([blank]))
    report = sc.run(1)
    assert report["documents_processed"] == 1 and report["changes"] == []


def test_duplicate_file_in_a_later_batch_is_listed_and_adds_nothing(scenario):
    sc = scenario(spec([contract()]))
    sc.run(1)
    report, uploads, _ = (
        replay.replay_files(
            sc.conn, sc.deps, sc.mid, 2, [("again.pdf", sc.files["c.pdf"]), ("c2.pdf", sc.files["c.pdf"])]
        )
        if False
        else (None, None, None)
    )
    # two different names, identical bytes: the second batch cannot be committed (nothing new) but duplicates are recorded
    b = matter_repo.open_batch(sc.conn, sc.mid, "dups")
    from legal_workspace.ingestion import service

    res = service.register_upload(
        sc.conn,
        sc.deps,
        matter_id=sc.mid,
        batch_seq=b["batch_seq"],
        filename="again.pdf",
        data=sc.files["c.pdf"],
    )
    assert res.duplicate
    with pytest.raises(BadRequest):
        service.commit_batch(
            sc.conn, sc.mid, b["batch_seq"]
        )  # an all-duplicates batch has no documents to commit


def test_cross_matter_isolation_same_keys_never_mix(scenario, conn, make_deps):
    sc = scenario(spec([contract()]))
    sc.run(1)
    from legal_workspace.adapters.llm import FixtureLLM
    from legal_workspace.synthetic.generate import render_matter

    other = Matter("T2", "T/2/2025", "Gamma v Delta", "BREACH", "HC", PARTIES, [contract()])
    files, fx, _ = render_matter(other)
    m2 = replay.create_matter_from_manifest(
        conn, {"number": other.number, "title": other.title, "type": other.matter_type, "forum": "HC"}
    )
    conn.commit()
    deps2 = make_deps(FixtureLLM(records=fx))
    replay.replay_files(conn, deps2, str(m2["matter_id"]), 1, [("c.pdf", files["c.pdf"])])
    a = conn.execute(
        "SELECT count(*) AS n FROM matter_fact_assertions WHERE matter_id = %s AND fact_key = %s",
        (sc.mid, KEY_DELIVERY),
    ).fetchone()["n"]
    b = conn.execute(
        "SELECT count(*) AS n FROM matter_fact_assertions WHERE matter_id = %s AND fact_key = %s",
        (str(m2["matter_id"]), KEY_DELIVERY),
    ).fetchone()["n"]
    assert a == b == 1
    assert {f["fact_key"] for f in queries.facts_as_of(conn, sc.mid, 1)} == {
        f["fact_key"] for f in queries.facts_as_of(conn, str(m2["matter_id"]), 1)
    }
    assert all(
        str(f["originating_document_id"])
        in {
            str(d["document_id"])
            for d in conn.execute(
                "SELECT document_id FROM documents WHERE matter_id = %s", (sc.mid,)
            ).fetchall()
        }
        for f in conn.execute(
            "SELECT originating_document_id FROM matter_fact_assertions WHERE matter_id = %s", (sc.mid,)
        ).fetchall()
    )


# ------------------------------------------------------------------------------------- derived values
def _invoice_and_payments(amounts, invoice="Rs. 1,00,000"):
    inv = Doc(
        "inv.pdf",
        1,
        "INVOICE",
        "Tax Invoice INV-9",
        "1 March 2024",
        f"# TAX INVOICE\nInvoice No. INV-9\nInvoice amount: {invoice}\n",
        suit_roles=False,
        items=[I("INVOICE", "INV-9", "invoice_amount", invoice, f"Invoice amount: {invoice}")],
    )
    rows = "\n".join(f"{10 + i} Apr 2024 NEFT credit towards INV-9 {a}" for i, a in enumerate(amounts))
    q = [
        I(
            "PAYMENT",
            f"payment {i}",
            s,
            v,
            f"{10 + i} Apr 2024 NEFT credit towards INV-9 {a}",
            date=f"{10 + i} April 2024",
        )
        for i, a in enumerate(amounts)
        for s, v in (("amount", a), ("date", f"{10 + i} Apr 2024"), ("against_invoice", "INV-9"))
    ]
    bank = Doc(
        "bank.pdf",
        1,
        "BANK_STATEMENT",
        "Bank Statement April 2024",
        "30 April 2024",
        f"# BANK STATEMENT\nStatement period: 1 April 2024 to 30 April 2024\n{rows}\n",
        suit_roles=False,
        items=q,
    )
    return [inv, bank]


def test_outstanding_is_invoice_less_all_payments(scenario):
    sc = scenario(spec(_invoice_and_payments(["30,000.00", "20,000.00"])))
    sc.run(1)
    cur = [f for f in sc.facts("invoice/inv-9/amount_outstanding") if f["ended_in_batch_seq"] is None]
    assert (
        len(cur) == 1
        and cur[0]["value_amount"] == Decimal("50000.00")
        and cur[0]["derived"]
        and not cur[0]["needs_review"]
    )


def test_overpayment_clamps_to_zero_and_is_flagged(scenario):
    sc = scenario(spec(_invoice_and_payments(["80,000.00", "40,000.00"])))
    sc.run(1)
    cur = [f for f in sc.facts("invoice/inv-9/amount_outstanding") if f["ended_in_batch_seq"] is None]
    assert (
        cur[0]["value_amount"] == Decimal("0.00")
        and cur[0]["needs_review"]
        and "exceed" in cur[0]["review_reason"]
    )


def test_no_payments_means_no_derived_outstanding(scenario):
    sc = scenario(spec(_invoice_and_payments([])[:1]))
    sc.run(1)
    assert sc.facts("invoice/inv-9/amount_outstanding") == []


# --------------------------------------------------------------------------------- court directions
def order(file, batch, date_text, body, items):
    txt = f"# IN THE HIGH COURT OF DELHI\nT/1/2025\nAlpha Traders Private Limited v Beta Industries Limited\nORDER\nDate of order: {date_text}\n{body}\n"
    return Doc(file, batch, "ORDER", f"Order dated {date_text}", date_text, txt, items=items)


def repl(file, batch, date_text, author):
    return Doc(
        file,
        batch,
        "REPLICATION",
        "Replication",
        date_text,
        "# IN THE HIGH COURT OF DELHI\nT/1/2025\nREPLICATION to the written statement\n1. The averments in the written statement are denied.\n",
        author=author,
        items=[],
    )


ORDER1 = order(
    "o1.pdf",
    1,
    "12 September 2025",
    "1. The Plaintiff shall file a replication within four weeks from today.",
    [
        I(
            "DIRECTION",
            "replication",
            "due_date",
            "within four weeks from today",
            "The Plaintiff shall file a replication within four weeks from today",
            kind="DIRECTION",
        ),
        I(
            "DIRECTION",
            "replication",
            "responsible_party",
            "the Plaintiff",
            "The Plaintiff shall file a replication within four weeks from today",
        ),
    ],
)


def dirs(sc, today=date(2025, 12, 1)):
    return {r["procedural_step"]: r for r in queries.directions(sc.conn, sc.mid, 9, today)}


def test_filing_the_replication_in_time_marks_the_direction_complied(scenario):
    sc = scenario(spec([ORDER1, repl("r.pdf", 2, "5 October 2025", "a")]))
    sc.run(1)
    assert dirs(sc)["replication"]["status"] == "OVERDUE"
    report = sc.run(2)
    d = dirs(sc)["replication"]
    assert (
        d["status"] == "COMPLIED" and d["complied_late"] is False and d["complied_by_title"] == "Replication"
    )
    assert any(c["change_type"] == "COMPLIED" for c in report["changes"])


def test_late_filing_is_complied_but_marked_late(scenario):
    sc = scenario(spec([ORDER1, repl("r.pdf", 2, "20 October 2025", "a")]))
    sc.run(1)
    sc.run(2)
    d = dirs(sc)["replication"]
    assert d["status"] == "COMPLIED" and d["complied_late"] is True


def test_filing_by_the_wrong_party_or_before_the_order_does_not_comply(scenario):
    sc = scenario(
        spec([ORDER1, repl("r1.pdf", 2, "5 October 2025", "b"), repl("r2.pdf", 2, "1 September 2025", "a")])
    )
    sc.run(1)
    sc.run(2)
    assert dirs(sc)["replication"]["status"] == "OVERDUE"


def test_period_from_receipt_has_no_due_date_and_is_flagged(scenario):
    o = order(
        "o.pdf",
        1,
        "12 September 2025",
        "1. The Defendant shall file its reply within three weeks from receipt of a copy of this order.",
        [
            I(
                "DIRECTION",
                "written statement",
                "due_date",
                "within three weeks from receipt of a copy of this order",
                "The Defendant shall file its reply within three weeks from receipt of a copy of this order",
            ),
            I(
                "DIRECTION",
                "written statement",
                "responsible_party",
                "the Defendant",
                "The Defendant shall file its reply within three weeks",
            ),
        ],
    )
    sc = scenario(spec([o]))
    sc.run(1)
    d = dirs(sc)["written_statement"]
    assert d["due_date"] is None and d["status"] == "NO_DATE"
    f = sc.facts("direction/written-statement/due_date")[0]
    assert f["needs_review"] and "receipt" in f["review_reason"]


def test_a_later_order_on_the_same_step_supersedes_the_earlier_deadline(scenario):
    o2 = order(
        "o2.pdf",
        2,
        "10 October 2025",
        "1. The Plaintiff shall file a replication within two weeks from today.",
        [
            I(
                "DIRECTION",
                "replication",
                "due_date",
                "within two weeks from today",
                "The Plaintiff shall file a replication within two weeks from today",
            ),
            I(
                "DIRECTION",
                "replication",
                "responsible_party",
                "the Plaintiff",
                "The Plaintiff shall file a replication within two weeks from today",
            ),
        ],
    )
    sc = scenario(spec([ORDER1, o2]))
    sc.run(1)
    report = sc.run(2)
    rows = sc.facts("direction/replication/due_date")
    assert {(r["value_date"], r["state"]) for r in rows} == {
        (date(2025, 10, 10), "SUPERSEDED"),
        (date(2025, 10, 24), "ACTIVE"),
    }
    assert any(c["change_type"] == "SUPERSEDED" and c["rule_id"] == "R3" for c in report["changes"])
    live = [r for r in queries.directions(sc.conn, sc.mid, 2, date(2025, 10, 20)) if not r["superseded"]]
    assert [r["due_date"] for r in live] == [date(2025, 10, 24)]


def test_an_order_without_a_date_creates_no_direction_rows(scenario):
    o = order(
        "o.pdf",
        1,
        "",
        "1. The Plaintiff shall file a replication within four weeks from today.",
        ORDER1.items,
    )
    o.date = ""
    sc = scenario(spec([o]))
    sc.run(1)
    assert sc.conn.execute("SELECT count(*) AS n FROM court_directions").fetchone()["n"] == 0


# --------------------------------------------------------------------------------------- pleadings
def plaint(file, batch, date_text, amount, title="PLAINT", doc_type="PLAINT"):
    txt = f"# IN THE HIGH COURT OF DELHI\nT/1/2025\n{title}\n1. The Plaintiff claims Rs. {amount} as the price of goods supplied.\n"
    return Doc(
        file,
        batch,
        doc_type,
        title.title(),
        date_text,
        txt,
        author="a",
        items=[
            I(
                "CLAIM",
                "principal",
                "amount",
                f"Rs. {amount}",
                f"The Plaintiff claims Rs. {amount} as the price of goods supplied",
            )
        ],
    )


def test_an_amended_pleading_supersedes_the_partys_own_earlier_claim(scenario):
    sc = scenario(
        spec(
            [
                plaint("p1.pdf", 1, "3 March 2025", "10,00,000"),
                plaint(
                    "p2.pdf",
                    2,
                    "1 September 2025",
                    "12,00,000",
                    title="AMENDED PLAINT",
                    doc_type="AMENDED_PLEADING",
                ),
            ]
        )
    )
    sc.run(1)
    report = sc.run(2)
    rows = sc.facts("claim/principal/amount")
    assert {(r["value_amount"], r["state"]) for r in rows} == {
        (Decimal("1000000.00"), "SUPERSEDED"),
        (Decimal("1200000.00"), "ACTIVE"),
    }
    assert any(c["rule_id"] == "R4" and c["change_type"] == "SUPERSEDED" for c in report["changes"])


def test_an_unamended_change_of_position_is_disputed_and_flagged(scenario):
    sc = scenario(
        spec(
            [
                plaint("p1.pdf", 1, "3 March 2025", "10,00,000"),
                plaint(
                    "p2.pdf", 2, "1 September 2025", "12,00,000", title="REPLICATION", doc_type="REPLICATION"
                ),
            ]
        )
    )
    sc.run(1)
    sc.run(2)
    rows = sc.facts("claim/principal/amount")
    assert {r["state"] for r in rows} == {"DISPUTED"} and all(r["needs_review"] for r in rows)


# ---------------------------------------------------------------------------------- review actions
def disputed_pair(scenario):
    inv1 = Doc(
        "i1.pdf",
        1,
        "INVOICE",
        "Tax Invoice INV-7",
        "1 March 2024",
        "# TAX INVOICE\nInvoice No. INV-7\nInvoice amount: Rs. 1,00,000\n",
        suit_roles=False,
        items=[I("INVOICE", "INV-7", "invoice_amount", "Rs. 1,00,000", "Invoice amount: Rs. 1,00,000")],
    )
    inv2 = Doc(
        "i2.pdf",
        1,
        "INVOICE",
        "Tax Invoice INV-7 (re-issued)",
        "5 March 2024",
        "# TAX INVOICE\nInvoice No. INV-7\nInvoice amount: Rs. 2,00,000\n",
        suit_roles=False,
        items=[I("INVOICE", "INV-7", "invoice_amount", "Rs. 2,00,000", "Invoice amount: Rs. 2,00,000")],
    )
    sc = scenario(spec([inv1, inv2]))
    sc.run(1)
    rows = sc.facts("invoice/inv-7/invoice_amount")
    return sc, str(rows[0]["assertion_id"]), str(rows[1]["assertion_id"])


def test_review_supersede_others_picks_a_winner_and_writes_a_manual_ledger_row(scenario):
    sc, first, second = disputed_pair(scenario)
    out = review.resolve_fact(
        sc.conn,
        sc.mid,
        second,
        action="SUPERSEDE_OTHERS",
        reviewer="meera",
        reason="re-issued invoice is the valid one",
    )
    assert out["state"] == "ACTIVE"
    rows = {str(r["assertion_id"]): r for r in sc.facts("invoice/inv-7/invoice_amount")}
    assert (
        rows[first]["state"] == "SUPERSEDED"
        and rows[second]["state"] == "ACTIVE"
        and not rows[second]["needs_review"]
    )
    manual = sc.conn.execute(
        "SELECT * FROM fact_change_log WHERE rule_id = 'MANUAL' ORDER BY change_id"
    ).fetchall()
    assert [m["reviewer"] for m in manual] == ["meera", "meera"] and "re-issued" in manual[-1]["reason"]


def test_review_dispute_evidence_only_withdraw_confirm_and_correct(scenario):
    sc, first, second = disputed_pair(scenario)

    def r(a, **kw):
        return review.resolve_fact(
            sc.conn, sc.mid, second, action=a, reviewer="meera", reason="checked", **kw
        )

    assert r("CONFIRM")["state"] == "DISPUTED"
    assert r("EVIDENCE_ONLY")["action"] == "EVIDENCE_ONLY"
    assert sc.conn.execute(
        "SELECT evidence_only FROM matter_fact_assertions WHERE assertion_id = %s", (second,)
    ).fetchone()["evidence_only"]
    r("CORRECT_VALUE", value="Rs. 1,50,000")
    assert sc.conn.execute(
        "SELECT value_amount FROM matter_fact_assertions WHERE assertion_id = %s", (second,)
    ).fetchone()["value_amount"] == Decimal("150000.00")
    assert r("WITHDRAW")["state"] == "WITHDRAWN"
    row = sc.conn.execute(
        "SELECT state, ended_in_batch_seq FROM matter_fact_assertions WHERE assertion_id = %s", (second,)
    ).fetchone()
    assert row == {"state": "WITHDRAWN", "ended_in_batch_seq": 1}
    with pytest.raises(Conflict):
        r("DISPUTE")  # an ended fact cannot be changed


def test_review_rejects_bad_requests(scenario):
    sc, first, second = disputed_pair(scenario)
    good = dict(reviewer="meera", reason="r")
    with pytest.raises(BadRequest):
        review.resolve_fact(sc.conn, sc.mid, first, action="DELETE_EVERYTHING", **good)
    with pytest.raises(ValidationFailed):
        review.resolve_fact(sc.conn, sc.mid, first, action="CONFIRM", reviewer="", reason="r")
    with pytest.raises(ValidationFailed):
        review.resolve_fact(sc.conn, sc.mid, first, action="CONFIRM", reviewer="m", reason="  ")
    with pytest.raises(ValidationFailed):
        review.resolve_fact(sc.conn, sc.mid, first, action="CORRECT_VALUE", value="not a number", **good)
    with pytest.raises(ValidationFailed):
        review.resolve_fact(sc.conn, sc.mid, first, action="CORRECT_VALUE", value=None, **good)
    with pytest.raises(NotFound):
        review.resolve_fact(sc.conn, sc.mid, "00000000-0000-0000-0000-000000000000", action="CONFIRM", **good)
    sc.conn.rollback()
    with pytest.raises(NotFound):
        review.resolve_fact(sc.conn, sc.mid, "not-a-uuid", action="CONFIRM", **good)
    sc.conn.rollback()
    other = matter_repo.create_matter(sc.conn, matter_number="OTHER/1", title="x", matter_type="BREACH")
    with pytest.raises(NotFound):
        review.resolve_fact(
            sc.conn, str(other["matter_id"]), first, action="CONFIRM", **good
        )  # a fact of another matter


def test_review_before_any_committed_batch_is_refused(conn):
    m = matter_repo.create_matter(conn, matter_number="N/1", title="t", matter_type="BREACH")
    with pytest.raises(NotFound):
        review.resolve_fact(
            conn,
            str(m["matter_id"]),
            "00000000-0000-0000-0000-000000000000",
            action="CONFIRM",
            reviewer="a",
            reason="b",
        )


def test_confirm_document_clears_the_flag_and_rejects_foreign_documents(scenario):
    a = amendment("a1.pdf", 1, "1 July 2024", "30 September 2024", title="SUPPLEMENTAL TERMS")
    a.confidence = 0.4
    sc = scenario(spec([contract(), a]))
    sc.run(1)
    doc = sc.conn.execute("SELECT document_id FROM documents WHERE needs_review").fetchone()
    review.confirm_document(sc.conn, sc.mid, str(doc["document_id"]))
    assert not sc.conn.execute(
        "SELECT needs_review FROM documents WHERE document_id = %s", (doc["document_id"],)
    ).fetchone()["needs_review"]
    other = matter_repo.create_matter(sc.conn, matter_number="OTHER/2", title="x", matter_type="BREACH")
    with pytest.raises(NotFound):
        review.confirm_document(sc.conn, str(other["matter_id"]), str(doc["document_id"]))
