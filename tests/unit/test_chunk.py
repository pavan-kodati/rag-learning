"""S04: structure-aware chunking, coordinates and edge cases."""

from __future__ import annotations

from legal_workspace.domain.types import DocType
from legal_workspace.ingestion.chunk import MAX_CHILD_TOKENS, chunk_document, est_tokens
from tests.helpers import pages_of

MSA = """# MASTER SERVICES AGREEMENT
This Agreement is made on 12 January 2023 between Vardhan Infotech Private Limited (the Supplier) and Kestrel Limited (the Customer).
1. DEFINITIONS
1.1 "Go-Live Date" means the date on which the Deliverables are accepted by the Customer.
1.2 "Fees" means the charges set out in Schedule 1.
2. DELIVERY
2.1 Time is of the essence.
2.2 Completion of the Deliverables shall occur on or before 30 June 2024, failing which liquidated damages apply.
2.3 The Supplier shall notify the Customer of any anticipated delay in writing; provided that notice shall not
extend the date unless the Customer agrees in writing.
3. PAYMENT
The Customer shall pay each invoice within 30 days of receipt.
7 a stray line starting with an out-of-sequence number should stay in clause 3
"""

PLAINT = """# PLAINT
IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 123/2025
Vardhan Infotech Private Limited v Kestrel Limited
1. The Plaintiff is a company incorporated in India.
2. The Defendant failed to pay invoice INV-014 for Rs. 18,40,000.
3. A legal notice dated 5 February 2025 was served on the Defendant.
4. The Plaintiff therefore prays for:
(a) a decree for Rs. 18,40,000;
(b) interest at 12% per annum.
Dated this 3 March 2025
Advocate for the Plaintiff
"""

ORDER = """# ORDER
IN THE HIGH COURT OF DELHI
CS(COMM) 123/2025   Date of order: 12 September 2025
Coram: Hon'ble Mr Justice A
1. The Plaintiff shall file a replication within four weeks.
2. The matter shall be listed on 14 November 2025.
"""

THREAD = """From: rao@vardhan.example
Date: 1 May 2024
Subject: Delay
We expect to deliver by 31 July 2024.
From: mehta@kestrel.example
Date: 2 May 2024
Subject: Re: Delay
Please confirm in writing.
"""

STATEMENT = """# BANK STATEMENT
Account: Vardhan Infotech Private Limited   Period: 1 March 2025 to 31 March 2025
Date        Narration                          Amount
14 Mar 2025 NEFT from Kestrel Limited          6,00,000.00
20 Mar 2025 Bank charges                       118.00
"""


def children(drafts):
    return [d for d in drafts if d.level == "CHILD"]


def refs(drafts):
    return [d.ref for d in children(drafts)]


def test_contract_clauses_become_children_with_parents():
    ch = chunk_document(DocType.CONTRACT, pages_of(MSA))
    assert refs(ch) == ["Preamble", "cl. 1.1", "cl. 1.2", "cl. 2.1", "cl. 2.2", "cl. 2.3", "cl. 3"]
    parents = [d for d in ch if d.level == "PARENT"]
    assert [p.ref for p in parents] == ["cl. 1", "cl. 2"]
    c22 = next(d for d in ch if d.ref == "cl. 2.2")
    assert "30 June 2024" in c22.text and ch[c22.parent].ref == "cl. 2"
    assert (
        "stray line" in next(d for d in ch if d.ref == "cl. 3").text
    )  # wrong sequence number is not a new clause


def test_proviso_stays_with_its_clause():
    ch = chunk_document(DocType.CONTRACT, pages_of(MSA))
    c23 = next(d for d in ch if d.ref == "cl. 2.3")
    assert "provided that" in c23.text and "agrees in writing" in c23.text


def test_plaint_paragraphs_header_and_closing():
    ch = chunk_document(DocType.PLAINT, pages_of(PLAINT))
    assert refs(ch) == ["Header", "¶1", "¶2", "¶3", "¶4", "Closing"]
    p4 = next(d for d in ch if d.ref == "¶4")
    assert "(a) a decree" in p4.text and "(b) interest" in p4.text  # prayer stays inside the paragraph
    assert "Advocate" in next(d for d in ch if d.ref == "Closing").text
    assert all(d.parent is not None and ch[d.parent].level == "PARENT" for d in children(ch))


def test_order_directions():
    ch = chunk_document(DocType.ORDER, pages_of(ORDER))
    assert refs(ch) == ["Header", "Direction 1", "Direction 2"]
    assert "replication within four weeks" in ch[-2].text or "replication within four weeks" in ch[-1].text


def test_email_thread_split_per_message():
    ch = chunk_document(DocType.EMAIL, pages_of(THREAD))
    assert refs(ch) == ["Email 1", "Email 2"]
    assert "31 July 2024" in ch[0].text and "31 July 2024" not in ch[1].text


def test_single_email_is_one_chunk():
    ch = chunk_document(
        DocType.EMAIL, pages_of("From: a@b.c\nSubject: hi\nPlease pay Rs. 5,000 by 1 May 2025.\nRegards")
    )
    assert len(children(ch)) == 1


def test_bank_statement_rows_become_children():
    ch = chunk_document(DocType.BANK_STATEMENT, pages_of(STATEMENT))
    rows = [d for d in children(ch) if d.ref and d.ref.startswith("Row")]
    assert len(rows) == 2 and "6,00,000.00" in rows[0].text and "14 Mar 2025" in rows[0].text
    assert any(d.ref == "Header" for d in children(ch))


def test_invoice_is_one_chunk_per_page():
    ch = chunk_document(
        DocType.INVOICE, pages_of("# INVOICE\nInvoice No. INV-014\nAmount Rs. 18,40,000\nDue 30 April 2025")
    )
    assert len(children(ch)) == 1 and ch[0].ref == "p.1"


def test_unstructured_text_falls_back_to_windows():
    text = "\n".join(
        f"This is sentence number {i} of an unstructured letter about the dispute." for i in range(120)
    )
    ch = chunk_document(DocType.LETTER, pages_of(text))
    cs = children(ch)
    assert len(cs) >= 2 and all(c.ref.startswith("Part") for c in cs)
    assert all(c.tokens <= MAX_CHILD_TOKENS for c in cs)
    # windows overlap by one line so a fact on a boundary is never lost
    assert cs[0].text.split("\n")[-1] == cs[1].text.split("\n")[0]


def test_numbered_paragraphs_in_a_letter_are_used_when_present():
    ch = chunk_document(
        DocType.LETTER,
        pages_of("Dear Sir,\n1. We refer to the contract.\n2. Payment is due.\nYours faithfully"),
    )
    assert refs(ch)[1:3] == ["¶1", "¶2"]


def test_oversized_paragraph_is_split_at_sentence_boundaries():
    long_para = "1. " + " ".join(
        f"Sentence {i} states a fact about the dispute that matters." for i in range(160)
    )
    ch = chunk_document(DocType.PLAINT, pages_of("# PLAINT\n" + long_para + "\n2. Short."))
    parts = [d for d in children(ch) if d.ref and d.ref.startswith("¶1")]
    assert len(parts) >= 2 and all("(part" in d.ref for d in parts)
    assert all(d.tokens <= MAX_CHILD_TOKENS for d in parts)
    assert parts[0].text.rstrip().endswith(".")  # cut at a sentence end, not mid-sentence


def test_footers_and_running_headers_are_excluded():
    body = "\n".join(
        f"{i}. Paragraph {i} contains operative text about delivery and payment obligations."
        for i in range(1, 60)
    )
    pages = pages_of("# PLAINT\n" + body)
    assert len(pages) >= 2
    ch = chunk_document(DocType.PLAINT, pages)
    assert not any("Page 1" in d.text or "Page 2" in d.text for d in ch)


def test_unit_spanning_pages_keeps_both_page_coordinates():
    filler = "\n".join(
        f"{i}. Filler paragraph {i} with enough words to occupy a line of the page." for i in range(1, 44)
    )
    text = "# PLAINT\n" + filler + "\n44. " + " ".join(f"word{i}" for i in range(200)) + "\n45. Last."
    pages = pages_of(text)
    ch = chunk_document(DocType.PLAINT, pages)
    spanning = [d for d in children(ch) if d.page_end > d.page_start]
    assert spanning, "expected a paragraph that crosses a page break"
    d = spanning[0]
    assert pages[d.page_start - 1].text[d.char_start :].strip() and d.char_end <= len(
        pages[d.page_end - 1].text
    )
    assert {b["page"] for b in d.bboxes} == {d.page_start, d.page_end}


def test_chunk_text_is_a_verbatim_slice_of_the_page_and_has_bboxes():
    pages = pages_of(MSA)
    for d in chunk_document(DocType.CONTRACT, pages):
        if d.page_start == d.page_end:
            assert pages[d.page_start - 1].text[d.char_start : d.char_end] == d.text
        assert d.bboxes, f"{d.ref} has no bounding boxes"
        for b in d.bboxes:
            assert 0 <= b["x0"] < b["x1"] <= 600 and 0 <= b["y0"] < b["y1"] <= 850


def test_ordinals_are_sequential_over_children_only():
    ch = chunk_document(DocType.CONTRACT, pages_of(MSA))
    assert [d.ordinal for d in children(ch)] == list(range(len(children(ch))))


def test_empty_or_noise_only_documents_yield_no_chunks():
    assert chunk_document(DocType.CONTRACT, pages_of("")) == []
    assert chunk_document(DocType.PLAINT, []) == []


def test_single_numbered_paragraph_falls_back_gracefully():
    ch = chunk_document(
        DocType.PLAINT, pages_of("# PLAINT\n1. Only one paragraph here, nothing else follows.")
    )
    assert children(ch)  # window fallback, not a crash


def test_est_tokens_monotonic():
    assert est_tokens("a b c") < est_tokens("a b c d e f g")
