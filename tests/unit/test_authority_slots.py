import pytest

from legal_workspace.domain.authority import AUTHORITY_OF, authority_for, looks_signed_by_all, rule_classify
from legal_workspace.domain.slots import (
    ALL_SLOTS,
    SUBJECT_SLOTS,
    allowed_subjects,
    category_for,
    slot_def,
)
from legal_workspace.domain.types import Authority, DocType, PartyRole, VType, opposing


def test_every_doc_type_has_an_authority_class():
    assert set(AUTHORITY_OF) == set(DocType)


@pytest.mark.parametrize(
    "heading, expected",
    [
        ("AMENDMENT NO. 1 TO THE MASTER SERVICES AGREEMENT", DocType.AMENDMENT),
        ("MASTER SERVICES AGREEMENT dated 12 January 2023", DocType.CONTRACT),
        (
            "IN THE HIGH COURT OF DELHI\nWRITTEN STATEMENT on behalf of the Defendant",
            DocType.WRITTEN_STATEMENT,
        ),
        ("PLAINT under Order VII Rule 1 CPC", DocType.PLAINT),
        ("LEGAL NOTICE under Section 80", DocType.LEGAL_NOTICE),
        ("TAX INVOICE\nInvoice No. INV-014", DocType.INVOICE),
        ("Bank Statement for the period", DocType.BANK_STATEMENT),
        ("AFFIDAVIT of Mr Rao", DocType.AFFIDAVIT),
        ("From: a@x.com\nSubject: delivery", DocType.EMAIL),
        ("STATEMENT OF WORK No. 2", DocType.SOW),
        ("REPLICATION to the written statement", DocType.WRITTEN_STATEMENT),  # both fire -> see below
    ],
)
def test_rule_classify_expected_type_is_among_hits(heading, expected):
    assert expected in rule_classify(heading)


def test_rule_classify_unknown_text_fires_nothing():
    assert rule_classify("Lorem ipsum dolor sit amet") == set()
    assert rule_classify("") == set()
    assert rule_classify(None) == set()  # type: ignore[arg-type]


def test_specific_title_beats_generic_agreement_rule():
    assert rule_classify("AMENDMENT to the Agreement") == {DocType.AMENDMENT}


def test_signature_heuristic():
    assert looks_signed_by_all("Signed by A\nSigned by B")
    assert looks_signed_by_all("For and on behalf of X ... For and on behalf of Y")
    assert not looks_signed_by_all("Signed by A only")
    assert not looks_signed_by_all("")


def test_low_confidence_classification_falls_back_to_correspondence_with_review():
    assert authority_for(DocType.AMENDMENT, 0.69, 0.7) == (Authority.CORRESPONDENCE, True)
    assert authority_for(DocType.AMENDMENT, 0.7, 0.7) == (Authority.BILATERAL, False)
    assert authority_for(DocType.ORDER, 0.99, 0.7) == (Authority.COURT, False)


def test_slot_registry_is_consistent():
    for st, slots in SUBJECT_SLOTS.items():
        assert "other" in slots, st
        for name, sd in slots.items():
            assert sd.name == name and isinstance(sd.vtype, VType)
    assert slot_def("contract", "delivery_date").vtype == VType.DATE
    assert slot_def("INVOICE", "amount_outstanding").vtype == VType.AMOUNT
    assert slot_def("INVOICE", "nonsense") is None
    assert slot_def("NOPE", "other") is None
    assert "delivery_date" in ALL_SLOTS


def test_allowed_subjects_are_narrow_per_document_type():
    assert allowed_subjects(DocType.ORDER) == ("DIRECTION", "HEARING")
    assert "DIRECTION" not in allowed_subjects(DocType.PLAINT)
    assert set(allowed_subjects(DocType.INVOICE)) >= {"INVOICE"}
    assert allowed_subjects(DocType.HEARING_NOTE)  # all types have a list


@pytest.mark.parametrize(
    "authority, doc_type, subject, slot, role, expected",
    [
        (Authority.BILATERAL, DocType.CONTRACT, "CONTRACT", "delivery_date", None, "TERM"),
        (Authority.COURT, DocType.ORDER, "DIRECTION", "due_date", None, "DIRECTION"),
        (Authority.COURT, DocType.ORDER, "HEARING", "next_date", None, "DIRECTION"),
        (Authority.RECORD, DocType.BANK_STATEMENT, "PAYMENT", "amount", None, "PAYMENT"),
        (Authority.PLEADING, DocType.PLAINT, "CLAIM", "amount", PartyRole.PLAINTIFF, "CLAIM"),
        (Authority.PLEADING, DocType.COUNTERCLAIM, "CLAIM", "amount", PartyRole.DEFENDANT, "COUNTERCLAIM"),
        (Authority.PLEADING, DocType.PLAINT, "RELIEF", "sought", PartyRole.PLAINTIFF, "RELIEF_SOUGHT"),
        (
            Authority.PLEADING,
            DocType.WRITTEN_STATEMENT,
            "ALLEGATION",
            "denied",
            PartyRole.DEFENDANT,
            "DENIAL",
        ),
        (
            Authority.PLEADING,
            DocType.WRITTEN_STATEMENT,
            "ALLEGATION",
            "admitted",
            PartyRole.DEFENDANT,
            "ADMISSION",
        ),
        (
            Authority.PLEADING,
            DocType.WRITTEN_STATEMENT,
            "ALLEGATION",
            "asserted",
            PartyRole.DEFENDANT,
            "DEFENCE",
        ),
        (Authority.PLEADING, DocType.PLAINT, "ALLEGATION", "asserted", PartyRole.PLAINTIFF, "CLAIM"),
        (Authority.RECORD, DocType.INVOICE, "INVOICE", "invoice_amount", None, "EVENT_FACT"),
        (Authority.CORRESPONDENCE, DocType.EMAIL, "CONTRACT", "delivery_date", None, "EVENT_FACT"),
    ],
)
def test_category_for(authority, doc_type, subject, slot, role, expected):
    assert category_for(authority, doc_type, subject, slot, role) == expected


def test_opposing_roles():
    assert opposing(PartyRole.PLAINTIFF, PartyRole.DEFENDANT)
    assert opposing(PartyRole.RESPONDENT, PartyRole.PETITIONER)
    assert not opposing(PartyRole.DEFENDANT, PartyRole.DEFENDANT)
    assert not opposing(PartyRole.OTHER, PartyRole.DEFENDANT)
    assert not opposing(None, PartyRole.DEFENDANT)


def test_body_text_never_decides_the_document_type():
    body = (
        "MASTER SERVICES AGREEMENT\nThis Agreement is made on 12 January 2023 between A and B.\n"
        "2.1 Each invoice is payable within 30 days of receipt of the notice and the order."
    )
    assert rule_classify(body) == {DocType.CONTRACT}


def test_amended_pleading_wins_over_plain_pleading_words():
    assert rule_classify("AMENDED WRITTEN STATEMENT") == {DocType.AMENDED_PLEADING}


def test_court_header_alone_does_not_make_a_plaint_an_order():
    assert rule_classify("IN THE HIGH COURT OF DELHI\nPLAINT under Order VII Rule 1") == {DocType.PLAINT}
    assert rule_classify("IN THE HIGH COURT OF DELHI\nORDER") == {DocType.ORDER}


def test_titles_must_be_short_lines_not_sentences():
    long_sentence = "Please treat this email as a legal notice for the purposes of the agreement between us and also a reminder."
    assert DocType.LEGAL_NOTICE not in rule_classify(long_sentence + "\nRegards")


def test_wrapped_sentence_fragments_are_not_titles():
    wrapped = "SUPPLEMENTAL TERMS\nThis Amendment is made on 1 July 2024 between Alpha Traders Private Limited and Beta\nIndustries Limited."
    assert rule_classify(wrapped) == set()
    assert rule_classify("Under instructions from my client, I serve this legal notice upon you") == set()
