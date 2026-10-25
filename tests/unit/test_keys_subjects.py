from datetime import date

import pytest

from legal_workspace.domain.keys import KeyError_, build_key, split_key, subject_of
from legal_workspace.domain.subjects import (
    NoticeRef,
    contract_id_for,
    make_contract_ref,
    notice_id,
    party_slug,
    resolve_contract,
    resolve_invoice,
    resolve_milestone,
    resolve_notice,
    resolve_payment,
)
from legal_workspace.domain.types import DocType


def test_build_key_blueprint_examples():
    assert build_key("CONTRACT", "msa-2023", "delivery_date") == "contract/msa-2023/delivery_date"
    assert build_key("INVOICE", "INV-014", "amount_outstanding") == "invoice/inv-014/amount_outstanding"
    assert build_key("NOTICE", "2025-02-05-vardhan", "received") == "notice/2025-02-05-vardhan/received"
    assert build_key("DIRECTION", "replication", "due_date") == "direction/replication/due_date"


@pytest.mark.parametrize(
    "st, ref, slot",
    [
        ("WIDGET", "x", "other"),
        ("CONTRACT", "msa", "not_a_slot"),
        ("CONTRACT", "", "other"),
        ("CONTRACT", "!!!", "other"),
        ("", "x", "other"),
        ("INVOICE", "inv-1", "delivery_date"),
    ],
)
def test_build_key_rejects_invalid(st, ref, slot):
    with pytest.raises(KeyError_):
        build_key(st, ref, slot)


def test_split_key_roundtrip_and_malformed():
    assert split_key("contract/msa-2023/delivery_date") == ("contract", "msa-2023", "delivery_date")
    assert subject_of("contract/msa-2023/delivery_date") == "contract/msa-2023"
    for bad in ["", "a/b", "a/b/c/d", "a//c"]:
        with pytest.raises(KeyError_):
            split_key(bad)


def test_contract_ids():
    assert contract_id_for("Master Services Agreement", DocType.CONTRACT, date(2023, 1, 12)) == "msa-2023"
    assert contract_id_for("Statement of Work", DocType.SOW, date(2023, 2, 1)) == "sow-2023"
    assert (
        contract_id_for("Distribution Agreement", DocType.CONTRACT, date(2022, 6, 1))
        == "distribution-agreement-2022"
    )
    assert (
        contract_id_for("Purchase Order No. PO-4471", DocType.PURCHASE_ORDER, date(2024, 1, 1)) == "po-4471"
    )
    assert contract_id_for("Master Services Agreement", DocType.CONTRACT, None) == "msa"


@pytest.fixture
def registry():
    return [
        make_contract_ref("Master Services Agreement", DocType.CONTRACT, date(2023, 1, 12)),
        make_contract_ref("Statement of Work", DocType.SOW, date(2023, 3, 1)),
    ]


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("MSA", "msa-2023"),
        ("the Master Services Agreement", "msa-2023"),
        ("the Agreement dated 12.01.2023", "msa-2023"),
        ("SOW", "sow-2023"),
        ("Statement of Work dated 1 March 2023", "sow-2023"),
        ("the agreement dated 1st March 2023", "sow-2023"),
    ],
)
def test_resolve_contract(ref, expected, registry):
    res = resolve_contract(ref, registry)
    assert res.ok and res.ref == expected


def test_resolve_contract_self_reference_uses_default(registry):
    assert resolve_contract("this Agreement", registry, default_id="sow-2023").ref == "sow-2023"
    assert resolve_contract("", registry, default_id="msa-2023").ref == "msa-2023"


def test_resolve_contract_single_registry_fallback():
    only = [make_contract_ref("Distribution Agreement", DocType.CONTRACT, date(2022, 6, 1))]
    assert resolve_contract("the Agreement", only).ref == "distribution-agreement-2022"


def test_resolve_contract_ambiguous_goes_to_review(registry):
    res = resolve_contract("the Agreement", registry)
    assert not res.ok and res.ambiguous and res.ref is None
    res = resolve_contract("some unknown contract", registry)
    assert res.ambiguous


def test_resolve_contract_empty_registry():
    assert resolve_contract("MSA", []).ambiguous


def test_resolve_milestone(registry):
    assert resolve_milestone("Milestone 3 under the MSA", registry, None).ref == "msa-2023-m3"
    assert resolve_milestone("M2 of SOW", registry, None).ref == "sow-2023-m2"
    assert resolve_milestone("the final milestone under the MSA", registry, None).ambiguous  # no number


def test_resolve_invoice_and_payment():
    assert resolve_invoice("Invoice No. INV-014").ref == "inv-014"
    assert resolve_invoice("INV/2024/014").ref == "inv-2024-014"
    assert resolve_invoice("").ambiguous
    assert resolve_payment("UTR 4251678901", None).ref == "4251678901"
    assert resolve_payment("part payment on 14 March 2025", None).ref == "2025-03-14"
    assert resolve_payment("part payment", date(2025, 3, 14)).ref == "2025-03-14"
    assert resolve_payment("part payment", None).ambiguous


def test_party_slug():
    assert party_slug("Vardhan Infotech Private Limited") == "vardhan"
    assert party_slug("M/s. Kestrel Ltd.") == "kestrel"
    assert party_slug("") == ""


def test_resolve_notice_cases():
    known = [NoticeRef("2025-02-05-vardhan", date(2025, 2, 5), "vardhan")]
    # date + sender known
    assert (
        resolve_notice("legal notice dated 5 February 2025", None, "vardhan", known).ref
        == "2025-02-05-vardhan"
    )
    # only the date known; one candidate on that date
    assert resolve_notice("the notice dated 5.2.2025", None, None, known).ref == "2025-02-05-vardhan"
    # nothing but "the notice": single known notice
    assert resolve_notice("the legal notice", None, None, known).ref == "2025-02-05-vardhan"
    # a new notice not yet known
    assert resolve_notice("", date(2025, 4, 1), "kestrel", known).ref == notice_id(
        date(2025, 4, 1), "kestrel"
    )
    # ambiguity
    two = [*known, NoticeRef("2025-03-01-vardhan", date(2025, 3, 1), "vardhan")]
    assert resolve_notice("the notice", None, "vardhan", two).ambiguous
    assert resolve_notice("the notice", None, None, []).ambiguous
    # date known but sender unknown and not in the registry
    assert resolve_notice("notice dated 9 June 2025", None, None, known).ambiguous
    # self reference
    own = NoticeRef("2025-02-05-vardhan", date(2025, 2, 5), "vardhan")
    assert resolve_notice("this notice", None, None, [], own).ref == "2025-02-05-vardhan"
