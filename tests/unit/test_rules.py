"""One table-driven test per authority rule R0-R9 (blueprint §8.3), plus precedence and edge cases."""

from datetime import date
from decimal import Decimal

import pytest

from legal_workspace.domain.rules import decide
from legal_workspace.domain.types import (
    Action,
    Authority,
    ChangeType,
    CurrentFact,
    DocType,
    FactState,
    FactValue,
    LinkType,
    NewFact,
    PartyRole,
)

PLAINTIFF, DEFENDANT = "p-vardhan", "p-kestrel"
KEY = "contract/msa-2023/delivery_date"


def val(d: date) -> FactValue:
    return FactValue(text=d.isoformat(), date=d)


def new_fact(
    *,
    authority,
    doc_type,
    value,
    doc_date,
    party=None,
    role=None,
    signed=False,
    slot="delivery_date",
    subject="CONTRACT",
    derived=False,
) -> NewFact:
    return NewFact(
        fact_key=KEY,
        slot=slot,
        value=value,
        party_id=party,
        party_role=role,
        authority=authority,
        doc_type=doc_type,
        doc_date=doc_date,
        signed_by_all=signed,
        document_id="doc-new",
        page=1,
        quote="q",
        assertion_text="t",
        category="TERM",
        subject_type=subject,
        derived=derived,
    )


def cur(
    *,
    authority,
    doc_type,
    value,
    doc_date,
    party=None,
    role=None,
    subject="CONTRACT",
    aid="a1",
    state=FactState.ACTIVE,
    evidence_only=False,
) -> CurrentFact:
    return CurrentFact(
        assertion_id=aid,
        fact_key=KEY,
        slot="delivery_date",
        value=value,
        party_id=party,
        party_role=role,
        authority=authority,
        doc_type=doc_type,
        doc_date=doc_date,
        state=state,
        evidence_only=evidence_only,
        subject_type=subject,
    )


MSA_TERM = cur(
    authority=Authority.BILATERAL,
    doc_type=DocType.CONTRACT,
    value=val(date(2024, 6, 30)),
    doc_date=date(2023, 1, 12),
)


def eff(decision, aid="a1"):
    return next(e for e in decision.effects if e.assertion_id == aid)


# ---------------------------------------------------------------------------------------------- R0
def test_r0_no_current_fact_is_new_active():
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.CONTRACT,
            value=val(date(2024, 6, 30)),
            doc_date=date(2023, 1, 12),
            signed=True,
        ),
        [],
    )
    assert (d.rule_id, d.change_type, d.new_state, d.new_evidence_only) == (
        "R0",
        ChangeType.NEW,
        FactState.ACTIVE,
        False,
    )
    assert d.effects == [] and not d.needs_review


def test_r0_ignores_evidence_only_and_ended_facts():
    ev = cur(
        authority=Authority.CORRESPONDENCE,
        doc_type=DocType.EMAIL,
        value=val(date(2024, 8, 1)),
        doc_date=date(2024, 4, 1),
        evidence_only=True,
    )
    old = cur(
        authority=Authority.BILATERAL,
        doc_type=DocType.CONTRACT,
        value=val(date(2024, 5, 1)),
        doc_date=date(2023, 1, 1),
        aid="a2",
        state=FactState.SUPERSEDED,
    )
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.AMENDMENT,
            value=val(date(2024, 7, 31)),
            doc_date=date(2024, 5, 10),
            signed=True,
        ),
        [ev, old],
    )
    assert d.rule_id == "R0"


# ---------------------------------------------------------------------------------------------- R1
def test_r1_same_value_is_corroboration_and_evidence_only():
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.PLAINT,
            value=val(date(2024, 6, 30)),
            doc_date=date(2025, 3, 3),
            party=PLAINTIFF,
            role=PartyRole.PLAINTIFF,
        ),
        [MSA_TERM],
    )
    assert (d.rule_id, d.change_type, d.new_evidence_only) == ("R1", ChangeType.CORROBORATED, True)
    e = eff(d)
    assert e.link == LinkType.SUPPORTS and e.reverse is True and e.action == Action.KEEP


def test_r1_amount_equality_ignores_text_format():
    a = cur(
        authority=Authority.RECORD,
        doc_type=DocType.INVOICE,
        value=FactValue("Rs 18,40,000", amount=Decimal("1840000.00")),
        doc_date=date(2025, 1, 10),
        subject="INVOICE",
    )
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.PLAINT,
            value=FactValue("₹18.4 lakh", amount=Decimal("1840000")),
            doc_date=date(2025, 3, 3),
            party=PLAINTIFF,
            role=PartyRole.PLAINTIFF,
            subject="INVOICE",
        ),
        [a],
    )
    assert d.rule_id == "R1"


# ---------------------------------------------------------------------------------------------- R2
def test_r2_signed_amendment_supersedes_contract_term():
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.AMENDMENT,
            value=val(date(2024, 7, 31)),
            doc_date=date(2024, 5, 10),
            signed=True,
        ),
        [MSA_TERM],
    )
    assert (d.rule_id, d.new_state, d.new_evidence_only) == ("R2", FactState.ACTIVE, False)
    e = eff(d)
    assert (e.action, e.link, e.change_type, e.reverse) == (
        Action.END,
        LinkType.SUPERSEDES,
        ChangeType.SUPERSEDED,
        False,
    )


def test_r2_unsigned_amendment_is_evidence_only_not_supersession():
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.AMENDMENT,
            value=val(date(2024, 7, 31)),
            doc_date=date(2024, 5, 10),
            signed=False,
        ),
        [MSA_TERM],
    )
    assert d.rule_id == "R8" and d.new_evidence_only and eff(d).action == Action.KEEP


def test_r2_late_arriving_older_amendment_is_born_superseded():
    newer = cur(
        authority=Authority.BILATERAL,
        doc_type=DocType.AMENDMENT,
        value=val(date(2024, 9, 30)),
        doc_date=date(2024, 7, 1),
    )
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.AMENDMENT,
            value=val(date(2024, 7, 31)),
            doc_date=date(2024, 5, 10),
            signed=True,
        ),
        [newer],
    )
    assert d.rule_id == "R2" and d.new_state == FactState.SUPERSEDED
    e = eff(d)
    assert e.action == Action.KEEP and e.reverse is True and e.link == LinkType.SUPERSEDES


@pytest.mark.parametrize("new_date", [date(2023, 1, 12), None])
def test_r2_same_or_missing_date_cannot_be_ranked_goes_to_review(new_date):
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.AMENDMENT,
            value=val(date(2024, 7, 31)),
            doc_date=new_date,
            signed=True,
        ),
        [MSA_TERM],
    )
    assert d.rule_id == "R9" and d.needs_review and d.new_state == FactState.DISPUTED


# ---------------------------------------------------------------------------------------------- R3
def _direction(value, doc_date, aid="d1"):
    return cur(
        authority=Authority.COURT,
        doc_type=DocType.ORDER,
        value=value,
        doc_date=doc_date,
        subject="DIRECTION",
        aid=aid,
    )


def test_r3_later_order_supersedes_earlier_direction():
    old = _direction(val(date(2025, 10, 10)), date(2025, 9, 12))
    d = decide(
        new_fact(
            authority=Authority.COURT,
            doc_type=DocType.ORDER,
            value=val(date(2025, 11, 7)),
            doc_date=date(2025, 10, 8),
            subject="DIRECTION",
            slot="due_date",
        ),
        [old],
    )
    assert d.rule_id == "R3" and d.new_state == FactState.ACTIVE
    assert eff(d, "d1").action == Action.END


def test_r3_earlier_order_arriving_late_is_born_superseded():
    newer = _direction(val(date(2025, 11, 7)), date(2025, 10, 8))
    d = decide(
        new_fact(
            authority=Authority.COURT,
            doc_type=DocType.ORDER,
            value=val(date(2025, 10, 10)),
            doc_date=date(2025, 9, 12),
            subject="DIRECTION",
            slot="due_date",
        ),
        [newer],
    )
    assert d.rule_id == "R3" and d.new_state == FactState.SUPERSEDED


def test_r3_same_date_orders_need_review():
    old = _direction(val(date(2025, 10, 10)), date(2025, 9, 12))
    d = decide(
        new_fact(
            authority=Authority.COURT,
            doc_type=DocType.ORDER,
            value=val(date(2025, 11, 7)),
            doc_date=date(2025, 9, 12),
            subject="DIRECTION",
            slot="due_date",
        ),
        [old],
    )
    assert d.rule_id == "R9" and d.needs_review


# ---------------------------------------------------------------------------------------------- R4
def _own_pleaded(value):
    return cur(
        authority=Authority.PLEADING,
        doc_type=DocType.PLAINT,
        value=value,
        doc_date=date(2025, 3, 3),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="CLAIM",
    )


def test_r4_amended_pleading_supersedes_own_earlier_position():
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.AMENDED_PLEADING,
            value=FactValue("12", amount=Decimal(1200000)),
            doc_date=date(2025, 6, 1),
            party=PLAINTIFF,
            role=PartyRole.PLAINTIFF,
            subject="CLAIM",
            slot="amount",
        ),
        [_own_pleaded(FactValue("18", amount=Decimal(1840000)))],
    )
    assert d.rule_id == "R4" and eff(d).action == Action.END


def test_r4_pleading_after_own_notice_supersedes_notice_position():
    notice = cur(
        authority=Authority.NOTICE,
        doc_type=DocType.LEGAL_NOTICE,
        value=FactValue("17", amount=Decimal(1700000)),
        doc_date=date(2025, 2, 5),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="CLAIM",
    )
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.PLAINT,
            value=FactValue("18", amount=Decimal(1840000)),
            doc_date=date(2025, 3, 3),
            party=PLAINTIFF,
            role=PartyRole.PLAINTIFF,
            subject="CLAIM",
            slot="amount",
        ),
        [notice],
    )
    assert d.rule_id == "R4"


def test_r4_unamended_change_of_own_pleaded_position_is_flagged():
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.REPLICATION,
            value=FactValue("12", amount=Decimal(1200000)),
            doc_date=date(2025, 6, 1),
            party=PLAINTIFF,
            role=PartyRole.PLAINTIFF,
            subject="CLAIM",
            slot="amount",
        ),
        [_own_pleaded(FactValue("18", amount=Decimal(1840000)))],
    )
    assert d.rule_id == "R9" and d.needs_review


# ---------------------------------------------------------------------------------------------- R5
def test_r5_derived_outstanding_ends_pleaded_figure_as_narrowed():
    pleaded = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.PLAINT,
        value=FactValue("18,40,000", amount=Decimal(1840000)),
        doc_date=date(2025, 3, 3),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="INVOICE",
        aid="f3",
    )
    d = decide(
        new_fact(
            authority=Authority.RECORD,
            doc_type=DocType.BANK_STATEMENT,
            value=FactValue("12,40,000", amount=Decimal(1240000)),
            doc_date=date(2025, 3, 14),
            subject="INVOICE",
            slot="amount_outstanding",
            derived=True,
        ),
        [pleaded],
    )
    assert d.rule_id == "R5" and d.new_state == FactState.ACTIVE
    e = eff(d, "f3")
    assert (e.action, e.change_type) == (Action.END, ChangeType.NARROWED)


# ---------------------------------------------------------------------------------------------- R6
def test_r6_opposing_pleadings_are_both_disputed():
    plaint = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.PLAINT,
        value=FactValue("true", boolean=True),
        doc_date=date(2025, 3, 3),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="NOTICE",
        aid="f5",
    )
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.WRITTEN_STATEMENT,
            value=FactValue("false", boolean=False),
            doc_date=date(2025, 6, 2),
            party=DEFENDANT,
            role=PartyRole.DEFENDANT,
            subject="NOTICE",
            slot="received",
        ),
        [plaint],
    )
    assert d.rule_id == "R6" and d.new_state == FactState.DISPUTED and not d.needs_review
    e = eff(d, "f5")
    assert (e.action, e.change_type, e.link) == (
        Action.MARK_DISPUTED,
        ChangeType.DISPUTED,
        LinkType.CONTRADICTS,
    )


def test_r6_why_newest_does_not_win():
    """The written statement is newer than the plaint, yet the plaint's version is not overwritten."""
    plaint = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.PLAINT,
        value=FactValue("true", boolean=True),
        doc_date=date(2025, 3, 3),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="NOTICE",
        aid="f5",
    )
    d = decide(
        new_fact(
            authority=Authority.SWORN,
            doc_type=DocType.AFFIDAVIT,
            value=FactValue("false", boolean=False),
            doc_date=date(2026, 1, 1),
            party=DEFENDANT,
            role=PartyRole.DEFENDANT,
            subject="NOTICE",
            slot="received",
        ),
        [plaint],
    )
    assert eff(d, "f5").action != Action.END


def test_r6_same_side_parties_do_not_dispute_each_other():
    other = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.WRITTEN_STATEMENT,
        value=FactValue("true", boolean=True),
        doc_date=date(2025, 6, 1),
        party="d1",
        role=PartyRole.DEFENDANT,
        subject="NOTICE",
    )
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.WRITTEN_STATEMENT,
            value=FactValue("false", boolean=False),
            doc_date=date(2025, 6, 2),
            party="d2",
            role=PartyRole.DEFENDANT,
            subject="NOTICE",
            slot="received",
        ),
        [other],
    )
    assert d.rule_id == "R9"  # not R6: flagged for review instead


# ---------------------------------------------------------------------------------------------- R7
def _pleaded_payment(value):
    return cur(
        authority=Authority.PLEADING,
        doc_type=DocType.WRITTEN_STATEMENT,
        value=value,
        doc_date=date(2025, 6, 1),
        party=DEFENDANT,
        role=PartyRole.DEFENDANT,
        subject="NOTICE",
        aid="w1",
    )


def test_r7_record_arriving_after_pleading_is_evidence_that_contradicts():
    d = decide(
        new_fact(
            authority=Authority.RECORD,
            doc_type=DocType.COURIER_PROOF,
            value=FactValue("true", boolean=True),
            doc_date=date(2025, 2, 6),
            subject="NOTICE",
            slot="received",
        ),
        [_pleaded_payment(FactValue("false", boolean=False))],
    )
    assert d.rule_id == "R7" and d.new_evidence_only and d.change_type == ChangeType.CONTRADICTED_BY_EVIDENCE
    e = eff(d, "w1")
    assert e.link == LinkType.CONTRADICTS and e.reverse is True and e.action == Action.KEEP


def test_r7_pleading_arriving_after_record_flips_record_to_evidence():
    record = cur(
        authority=Authority.RECORD,
        doc_type=DocType.COURIER_PROOF,
        value=FactValue("true", boolean=True),
        doc_date=date(2025, 2, 6),
        subject="NOTICE",
        aid="r1",
    )
    d = decide(
        new_fact(
            authority=Authority.PLEADING,
            doc_type=DocType.WRITTEN_STATEMENT,
            value=FactValue("false", boolean=False),
            doc_date=date(2025, 6, 2),
            party=DEFENDANT,
            role=PartyRole.DEFENDANT,
            subject="NOTICE",
            slot="received",
        ),
        [record],
    )
    assert d.rule_id == "R7" and not d.new_evidence_only and d.new_state == FactState.ACTIVE
    e = eff(d, "r1")
    assert e.action == Action.MARK_EVIDENCE_ONLY and e.reverse is False


def test_r7_email_contradicting_sworn_statement():
    sworn = cur(
        authority=Authority.SWORN,
        doc_type=DocType.AFFIDAVIT,
        value=val(date(2024, 7, 31)),
        doc_date=date(2025, 5, 1),
        party=DEFENDANT,
        role=PartyRole.DEFENDANT,
    )
    d = decide(
        new_fact(
            authority=Authority.CORRESPONDENCE,
            doc_type=DocType.EMAIL,
            value=val(date(2024, 6, 30)),
            doc_date=date(2024, 6, 1),
        ),
        [sworn],
    )
    assert d.rule_id == "R7"


# ---------------------------------------------------------------------------------------------- R8
@pytest.mark.parametrize(
    "authority, doc_type",
    [(Authority.CORRESPONDENCE, DocType.EMAIL), (Authority.INTERNAL, DocType.HEARING_NOTE)],
)
def test_r8_proposals_and_notes_never_change_current_position(authority, doc_type):
    d = decide(
        new_fact(
            authority=authority, doc_type=doc_type, value=val(date(2024, 8, 15)), doc_date=date(2024, 5, 20)
        ),
        [MSA_TERM],
    )
    assert d.rule_id == "R8" and d.new_evidence_only and d.new_state == FactState.ACTIVE
    assert eff(d).action == Action.KEEP and eff(d).link is None


def test_r8_hearing_note_conflicting_with_an_order():
    order = _direction(val(date(2025, 10, 10)), date(2025, 9, 12))
    d = decide(
        new_fact(
            authority=Authority.INTERNAL,
            doc_type=DocType.HEARING_NOTE,
            value=val(date(2025, 10, 24)),
            doc_date=date(2025, 9, 13),
            subject="DIRECTION",
            slot="due_date",
        ),
        [order],
    )
    assert d.rule_id == "R8" and d.new_evidence_only


def test_r8_application_by_same_party_not_yet_allowed():
    pleaded = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.PLAINT,
        value=FactValue("18", amount=Decimal(1840000)),
        doc_date=date(2025, 3, 3),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="CLAIM",
    )
    d = decide(
        new_fact(
            authority=Authority.SWORN,
            doc_type=DocType.APPLICATION,
            value=FactValue("12", amount=Decimal(1200000)),
            doc_date=date(2025, 6, 1),
            party=PLAINTIFF,
            role=PartyRole.PLAINTIFF,
            subject="CLAIM",
            slot="amount",
        ),
        [pleaded],
    )
    assert d.rule_id == "R8" and d.new_evidence_only


# ---------------------------------------------------------------------------------------------- R9
def test_r9_unmatched_conflict_is_disputed_and_flagged_never_overwritten():
    other_record = cur(
        authority=Authority.RECORD,
        doc_type=DocType.INVOICE,
        value=FactValue("a", amount=Decimal(100)),
        doc_date=date(2025, 1, 1),
        subject="INVOICE",
    )
    d = decide(
        new_fact(
            authority=Authority.RECORD,
            doc_type=DocType.INVOICE,
            value=FactValue("b", amount=Decimal(200)),
            doc_date=date(2025, 2, 1),
            subject="INVOICE",
            slot="invoice_amount",
        ),
        [other_record],
    )
    assert d.rule_id == "R9" and d.needs_review and d.new_state == FactState.DISPUTED
    assert eff(d).action == Action.MARK_DISPUTED


def test_r9_court_order_vs_pleaded_fact_is_flagged():
    pleaded = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.PLAINT,
        value=val(date(2025, 1, 1)),
        doc_date=date(2025, 3, 3),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="HEARING",
    )
    d = decide(
        new_fact(
            authority=Authority.COURT,
            doc_type=DocType.ORDER,
            value=val(date(2025, 2, 1)),
            doc_date=date(2025, 9, 1),
            subject="CONTRACT",
        ),
        [pleaded],
    )
    assert d.rule_id == "R9"


# ----------------------------------------------------------------------------------- combinations
def test_third_fact_agreeing_with_one_side_still_disputes_the_other():
    f5 = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.PLAINT,
        value=FactValue("true", boolean=True),
        doc_date=date(2025, 3, 3),
        party=PLAINTIFF,
        role=PartyRole.PLAINTIFF,
        subject="NOTICE",
        aid="f5",
        state=FactState.DISPUTED,
    )
    f6 = cur(
        authority=Authority.PLEADING,
        doc_type=DocType.WRITTEN_STATEMENT,
        value=FactValue("false", boolean=False),
        doc_date=date(2025, 6, 1),
        party=DEFENDANT,
        role=PartyRole.DEFENDANT,
        subject="NOTICE",
        aid="f6",
        state=FactState.DISPUTED,
    )
    d = decide(
        new_fact(
            authority=Authority.SWORN,
            doc_type=DocType.AFFIDAVIT,
            value=FactValue("true", boolean=True),
            doc_date=date(2025, 7, 1),
            party=PLAINTIFF,
            role=PartyRole.PLAINTIFF,
            subject="NOTICE",
            slot="received",
        ),
        [f5, f6],
    )
    assert d.rule_id == "R6" and d.new_state == FactState.DISPUTED
    kinds = {e.assertion_id: e.link for e in d.effects}
    assert kinds["f6"] == LinkType.CONTRADICTS and kinds["f5"] == LinkType.SUPPORTS


def test_headline_rule_is_the_most_significant():
    """Two conflicting facts, one superseded by R2 and one needing review (R9): R9 is the headline."""
    a = cur(
        authority=Authority.BILATERAL,
        doc_type=DocType.CONTRACT,
        value=val(date(2024, 6, 30)),
        doc_date=date(2023, 1, 12),
        aid="a",
    )
    b = cur(
        authority=Authority.BILATERAL,
        doc_type=DocType.CONTRACT,
        value=val(date(2024, 5, 30)),
        doc_date=date(2024, 5, 10),
        aid="b",
    )
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.AMENDMENT,
            value=val(date(2024, 7, 31)),
            doc_date=date(2024, 5, 10),
            signed=True,
        ),
        [a, b],
    )
    assert d.rule_id == "R9" and d.needs_review


def test_state_filter_only_current_position_facts_count():
    ended = cur(
        authority=Authority.BILATERAL,
        doc_type=DocType.CONTRACT,
        value=val(date(2024, 6, 30)),
        doc_date=date(2023, 1, 12),
        state=FactState.SUPERSEDED,
    )
    d = decide(
        new_fact(
            authority=Authority.BILATERAL,
            doc_type=DocType.AMENDMENT,
            value=val(date(2024, 7, 31)),
            doc_date=date(2024, 5, 10),
            signed=True,
        ),
        [ended],
    )
    assert d.rule_id == "R0"
