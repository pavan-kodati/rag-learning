"""M2: Payment / recovery. Vardhan Infotech Private Limited v Kestrel Limited (the blueprint's worked example).

All names, numbers and documents are invented. Planted changes: R1 (plaint restates the delivery date), R8 (e-mail
proposals), R2 (signed amendment supersedes the delivery date), R5 (part-payment narrows the outstanding amount),
R6 (the notice is served vs never received), R0 directions with computed deadlines, and a duplicate upload.
"""

from __future__ import annotations

from ..spec import Doc, I, Matter, Party, Planted, Probe, Question

MSA = """# MASTER SERVICES AGREEMENT
This Agreement is made on 12 January 2023 between Vardhan Infotech Private Limited, New Delhi (the Supplier) and Kestrel Limited, Gurugram (the Customer).
1. SERVICES AND CONTRACT VALUE
1.1 The Supplier shall design, build and deploy a procurement platform for the Customer (the Deliverables).
1.2 The total contract value is Rs. 48,00,000 exclusive of taxes.
2. DELIVERY
2.1 Time is of the essence of this Agreement.
2.2 Completion of the Deliverables (the Go-Live Date) shall occur on or before 30 June 2024.
2.3 If the Supplier fails to meet the Go-Live Date, liquidated damages of 0.5% of the contract value per week of delay shall be payable, capped at 10% of the contract value.
3. PAYMENT
3.1 The Customer shall pay each invoice within 30 days of receipt.
3.2 Delayed payments carry interest at 12% per annum.
4. TERMINATION
4.1 Either party may terminate this Agreement by giving 60 days written notice.
4.2 A party in breach shall have 30 days from written notice to cure the breach.
5. GOVERNING LAW AND JURISDICTION
5.1 This Agreement is governed by the laws of India.
5.2 The courts at New Delhi shall have exclusive jurisdiction.
Signed by Vardhan Infotech Private Limited (Authorised Signatory: R. Rao)
Signed by Kestrel Limited (Authorised Signatory: A. Mehta)
"""

EMAILS = """From: A. Mehta <mehta@kestrel.example>
To: R. Rao <rao@vardhan.example>
Date: 25 April 2024
Subject: Go-live date
We are not able to complete user acceptance testing by 30 June 2024. We propose to move the go-live to 15 August 2024.
From: R. Rao <rao@vardhan.example>
To: A. Mehta <mehta@kestrel.example>
Date: 28 April 2024
Subject: Re: Go-live date
We cannot agree to 15 August 2024. We can go live on 31 July 2024 if the amendment is signed this month.
"""

INVOICE = """# TAX INVOICE
Invoice No. INV-014
Invoice date: 15 September 2024
Supplier: Vardhan Infotech Private Limited, New Delhi
Customer: Kestrel Limited, Gurugram
Description: Final milestone, platform go-live and acceptance under the Master Services Agreement dated 12 January 2023
Invoice amount: Rs. 18,40,000
Payment due date: 15 October 2024
Payment terms: 30 days from receipt of invoice
"""

NOTICE = """# LEGAL NOTICE
Dated: 5 February 2025
Sent by speed post and e-mail
To: Kestrel Limited, Gurugram
Under instructions from Vardhan Infotech Private Limited, I serve the following notice.
1. My client and your company entered into a Master Services Agreement dated 12 January 2023.
2. My client raised invoice INV-014 dated 15 September 2024 for Rs. 18,40,000, payable within 30 days.
3. You have failed to pay invoice INV-014 despite repeated reminders.
4. You are called upon to pay Rs. 18,40,000 within 15 days of this notice, failing which my client will initiate legal proceedings.
Advocate for Vardhan Infotech Private Limited
"""

PLAINT = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 412/2025
Vardhan Infotech Private Limited v Kestrel Limited
PLAINT under Order VII Rule 1 of the Code of Civil Procedure, 1908
1. The Plaintiff, Vardhan Infotech Private Limited, is a company registered in India that supplies software services. The Defendant, Kestrel Limited, is a company that procured those services.
2. By a Master Services Agreement dated 12 January 2023 (the MSA), the Plaintiff agreed to build a procurement platform for the Defendant for a contract value of Rs. 48,00,000.
3. Under clause 2.2 of the MSA, the Deliverables were to be completed on or before 30 June 2024.
4. The Plaintiff completed the Deliverables and the platform went live on 12 July 2024.
5. On 15 September 2024 the Plaintiff raised invoice INV-014 for Rs. 18,40,000, payable within 30 days.
6. The Defendant has not paid invoice INV-014. The sum of Rs. 18,40,000 remains due and unpaid.
7. On 5 February 2025 the Plaintiff served a legal notice on the Defendant by speed post and e-mail demanding payment. The Defendant did not reply.
8. The Plaintiff is entitled to interest at 12% per annum under clause 3.2 of the MSA.
9. The Plaintiff has complied with Section 12A of the Commercial Courts Act, 2015 and a non-starter report was issued on 20 February 2025.
10. The cause of action arose on 15 October 2024 when invoice INV-014 fell due.
PRAYER
The Plaintiff therefore prays for:
(a) a decree for Rs. 18,40,000 against the Defendant;
(b) interest at 12% per annum from 15 October 2024 until realisation;
(c) costs of the suit.
Dated this 3 March 2025
Advocate for the Plaintiff
"""

AMENDMENT = """# AMENDMENT NO. 1 TO MASTER SERVICES AGREEMENT
This Amendment is made on 10 May 2024 between Vardhan Infotech Private Limited (the Supplier) and Kestrel Limited (the Customer) and amends the Master Services Agreement dated 12 January 2023 (the Agreement).
1. Clause 2.2 of the Agreement stands substituted as follows: The Go-Live Date shall be 31 July 2024.
2. All other terms of the Agreement remain unchanged.
Signed by Vardhan Infotech Private Limited (Authorised Signatory: R. Rao)
Signed by Kestrel Limited (Authorised Signatory: A. Mehta)
"""

BANK = """# BANK STATEMENT
Account holder: Vardhan Infotech Private Limited
Account number: XXXXXX7890
Statement period: 1 March 2025 to 31 March 2025
Date Narration Amount (Rs.)
14 Mar 2025 NEFT credit from Kestrel Limited towards INV-014 part payment 6,00,000.00
20 Mar 2025 Bank charges 118.00
"""

WS = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 412/2025
Vardhan Infotech Private Limited v Kestrel Limited
WRITTEN STATEMENT on behalf of the Defendant
1. The suit is liable to be dismissed as the Defendant disputes the claim in the manner set out below.
2. It is denied that any legal notice dated 5 February 2025 was received by the Defendant. No such notice was ever received at its registered office.
3. The Master Services Agreement dated 12 January 2023 was amended by Amendment No. 1 dated 10 May 2024, under which the Go-Live Date was extended to 31 July 2024.
4. The platform went live on 12 July 2024, before the extended Go-Live Date. There was no delay on the part of the Plaintiff.
5. The Defendant admits receipt of invoice INV-014 dated 15 September 2024 for Rs. 18,40,000.
6. It is denied that the Defendant has not paid. The Defendant paid Rs. 6,00,000 on 14 March 2025 towards invoice INV-014.
7. The Defendant is entitled to withhold Rs. 3,00,000 on account of defects in the delivered modules.
8. The claim for interest is denied.
Dated this 2 June 2025
Advocate for the Defendant
"""

ORDER = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 412/2025
Vardhan Infotech Private Limited v Kestrel Limited
ORDER
Date of order: 12 September 2025
Coram: Hon'ble Mr Justice S. Verma
Present: Counsel for the Plaintiff and counsel for the Defendant.
1. The written statement filed by the Defendant is taken on record.
2. The Plaintiff shall file a replication within four weeks from today.
3. The Defendant shall file an affidavit of admission and denial of documents within six weeks from today.
4. The matter shall be listed on 14 November 2025 for framing of issues.
"""

MSA_REF = "the Master Services Agreement dated 12 January 2023"
NOTICE_REF = "legal notice dated 5 February 2025"

DOCS = [
    # ------------------------------------------------------------------------------------------ batch 1
    Doc(
        "01_Master_Services_Agreement.pdf",
        1,
        "CONTRACT",
        "Master Services Agreement",
        "12 January 2023",
        MSA,
        signed=True,
        suit_roles=False,
        terms=[("the Supplier", "vardhan"), ("the Customer", "kestrel")],
        items=[
            I(
                "CONTRACT",
                "Master Services Agreement",
                "effective_date",
                "12 January 2023",
                "This Agreement is made on 12 January 2023",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "contract_value",
                "Rs. 48,00,000",
                "The total contract value is Rs. 48,00,000 exclusive of taxes",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "delivery_date",
                "30 June 2024",
                "Completion of the Deliverables (the Go-Live Date) shall occur on or before 30 June 2024",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "ld_rate",
                "0.5% of the contract value per week of delay",
                "liquidated damages of 0.5% of the contract value per week of delay shall be payable",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "ld_cap",
                "10% of the contract value",
                "capped at 10% of the contract value",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "payment_terms_days",
                "30 days",
                "The Customer shall pay each invoice within 30 days of receipt",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "termination_notice_days",
                "60 days",
                "Either party may terminate this Agreement by giving 60 days written notice",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "cure_period_days",
                "30 days",
                "A party in breach shall have 30 days from written notice to cure the breach",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "governing_law",
                "laws of India",
                "This Agreement is governed by the laws of India",
            ),
            I(
                "CONTRACT",
                "Master Services Agreement",
                "jurisdiction",
                "courts at New Delhi",
                "The courts at New Delhi shall have exclusive jurisdiction",
            ),
        ],
    ),
    Doc(
        "02_Email_thread_go_live_date.pdf",
        1,
        "EMAIL",
        "Go-live date (e-mail thread)",
        "28 April 2024",
        EMAILS,
        suit_roles=False,
        items=[
            I(
                "CONTRACT",
                MSA_REF,
                "delivery_date",
                "15 August 2024",
                "We propose to move the go-live to 15 August 2024",
            ),
            I(
                "CONTRACT",
                MSA_REF,
                "delivery_date",
                "31 July 2024",
                "We can go live on 31 July 2024 if the amendment is signed this month",
            ),
        ],
    ),
    Doc(
        "03_Invoice_INV-014.pdf",
        1,
        "INVOICE",
        "Tax Invoice INV-014",
        "15 September 2024",
        INVOICE,
        suit_roles=False,
        author="vardhan",
        items=[
            I("INVOICE", "INV-014", "invoice_amount", "Rs. 18,40,000", "Invoice amount: Rs. 18,40,000"),
            I("INVOICE", "INV-014", "invoice_date", "15 September 2024", "Invoice date: 15 September 2024"),
            I("INVOICE", "INV-014", "due_date", "15 October 2024", "Payment due date: 15 October 2024"),
        ],
    ),
    Doc(
        "04_Legal_Notice_5_Feb_2025.pdf",
        1,
        "LEGAL_NOTICE",
        "Legal Notice",
        "5 February 2025",
        NOTICE,
        author="vardhan",
        suit_roles=False,
        items=[
            I("NOTICE", "this notice", "sent_date", "5 February 2025", "Dated: 5 February 2025"),
            I(
                "NOTICE",
                "this notice",
                "mode_of_service",
                "speed post and e-mail",
                "Sent by speed post and e-mail",
            ),
            I(
                "NOTICE",
                "this notice",
                "demand_amount",
                "Rs. 18,40,000",
                "You are called upon to pay Rs. 18,40,000 within 15 days of this notice",
            ),
            I(
                "CLAIM",
                "principal",
                "amount",
                "Rs. 18,40,000",
                "You are called upon to pay Rs. 18,40,000 within 15 days of this notice",
            ),
            I(
                "INVOICE",
                "INV-014",
                "invoice_amount",
                "Rs. 18,40,000",
                "My client raised invoice INV-014 dated 15 September 2024 for Rs. 18,40,000",
            ),
            I(
                "ALLEGATION",
                "non_payment",
                "asserted",
                "true",
                "You have failed to pay invoice INV-014 despite repeated reminders",
            ),
        ],
    ),
    Doc(
        "05_Plaint.pdf",
        1,
        "PLAINT",
        "Plaint",
        "3 March 2025",
        PLAINT,
        author="vardhan",
        items=[
            I(
                "CONTRACT",
                MSA_REF,
                "contract_value",
                "Rs. 48,00,000",
                "for a contract value of Rs. 48,00,000",
            ),
            I(
                "CONTRACT",
                MSA_REF,
                "delivery_date",
                "30 June 2024",
                "the Deliverables were to be completed on or before 30 June 2024",
            ),
            I(
                "MILESTONE",
                "Milestone 1 (go-live) under the MSA",
                "acceptance_date",
                "12 July 2024",
                "the platform went live on 12 July 2024",
            ),
            I(
                "INVOICE",
                "INV-014",
                "invoice_amount",
                "Rs. 18,40,000",
                "the Plaintiff raised invoice INV-014 for Rs. 18,40,000",
            ),
            I(
                "INVOICE",
                "INV-014",
                "invoice_date",
                "15 September 2024",
                "On 15 September 2024 the Plaintiff raised invoice INV-014",
            ),
            I(
                "INVOICE",
                "INV-014",
                "amount_outstanding",
                "Rs. 18,40,000",
                "The sum of Rs. 18,40,000 remains due and unpaid",
            ),
            I("ALLEGATION", "non_payment", "asserted", "true", "The Defendant has not paid invoice INV-014"),
            I(
                "NOTICE",
                NOTICE_REF,
                "received",
                "true",
                "the Plaintiff served a legal notice on the Defendant by speed post and e-mail",
                date="5 February 2025",
                party="the Plaintiff",
            ),
            I(
                "NOTICE",
                NOTICE_REF,
                "sent_date",
                "5 February 2025",
                "On 5 February 2025 the Plaintiff served a legal notice",
                date="5 February 2025",
                party="the Plaintiff",
            ),
            I(
                "CLAIM",
                "interest",
                "interest_rate",
                "12% per annum",
                "entitled to interest at 12% per annum under clause 3.2 of the MSA",
            ),
            I(
                "CLAIM",
                "principal",
                "amount",
                "Rs. 18,40,000",
                "a decree for Rs. 18,40,000 against the Defendant",
            ),
            I("RELIEF", "recovery", "sought", "true", "a decree for Rs. 18,40,000 against the Defendant"),
            I(
                "RELIEF",
                "recovery",
                "amount",
                "Rs. 18,40,000",
                "a decree for Rs. 18,40,000 against the Defendant",
            ),
            I("RELIEF", "costs", "sought", "true", "costs of the suit"),
        ],
    ),
    # ------------------------------------------------------------------------------------------ batch 2
    Doc(
        "06_Amendment_No_1.pdf",
        2,
        "AMENDMENT",
        "Amendment No. 1 to Master Services Agreement",
        "10 May 2024",
        AMENDMENT,
        signed=True,
        suit_roles=False,
        amends=MSA_REF,
        terms=[("the Supplier", "vardhan"), ("the Customer", "kestrel")],
        items=[
            I("CONTRACT", MSA_REF, "delivery_date", "31 July 2024", "The Go-Live Date shall be 31 July 2024"),
        ],
    ),
    Doc(
        "07_Bank_statement_March_2025.pdf",
        2,
        "BANK_STATEMENT",
        "Bank Statement March 2025",
        "31 March 2025",
        BANK,
        suit_roles=False,
        items=[
            I(
                "PAYMENT",
                "NEFT credit from Kestrel Limited",
                "amount",
                "6,00,000.00",
                "14 Mar 2025 NEFT credit from Kestrel Limited towards INV-014 part payment 6,00,000.00",
                date="14 March 2025",
            ),
            I(
                "PAYMENT",
                "NEFT credit from Kestrel Limited",
                "date",
                "14 Mar 2025",
                "14 Mar 2025 NEFT credit from Kestrel Limited towards INV-014 part payment 6,00,000.00",
                date="14 March 2025",
            ),
            I(
                "PAYMENT",
                "NEFT credit from Kestrel Limited",
                "against_invoice",
                "INV-014",
                "14 Mar 2025 NEFT credit from Kestrel Limited towards INV-014 part payment 6,00,000.00",
                date="14 March 2025",
            ),
        ],
    ),
    Doc(
        "07b_Bank_statement_duplicate.pdf",
        2,
        "BANK_STATEMENT",
        "Bank Statement March 2025",
        "31 March 2025",
        BANK,
        suit_roles=False,
        is_duplicate_of="07_Bank_statement_March_2025.pdf",
    ),
    Doc(
        "08_Written_Statement.pdf",
        2,
        "WRITTEN_STATEMENT",
        "Written Statement",
        "2 June 2025",
        WS,
        author="kestrel",
        items=[
            I(
                "NOTICE",
                NOTICE_REF,
                "received",
                "false",
                "It is denied that any legal notice dated 5 February 2025 was received by the Defendant",
                date="5 February 2025",
                party="the Plaintiff",
            ),
            I(
                "CONTRACT",
                MSA_REF,
                "delivery_date",
                "31 July 2024",
                "the Go-Live Date was extended to 31 July 2024",
            ),
            I(
                "MILESTONE",
                "Milestone 1 (go-live) under the Master Services Agreement",
                "acceptance_date",
                "12 July 2024",
                "The platform went live on 12 July 2024",
            ),
            I("ALLEGATION", "delay", "denied", "true", "There was no delay on the part of the Plaintiff"),
            I(
                "INVOICE",
                "INV-014",
                "invoice_amount",
                "Rs. 18,40,000",
                "receipt of invoice INV-014 dated 15 September 2024 for Rs. 18,40,000",
            ),
            I("ALLEGATION", "non_payment", "denied", "true", "It is denied that the Defendant has not paid"),
            I(
                "PAYMENT",
                "payment of 14 March 2025",
                "amount",
                "Rs. 6,00,000",
                "The Defendant paid Rs. 6,00,000 on 14 March 2025 towards invoice INV-014",
                date="14 March 2025",
            ),
            I(
                "PAYMENT",
                "payment of 14 March 2025",
                "date",
                "14 March 2025",
                "The Defendant paid Rs. 6,00,000 on 14 March 2025 towards invoice INV-014",
                date="14 March 2025",
            ),
            I(
                "PAYMENT",
                "payment of 14 March 2025",
                "against_invoice",
                "INV-014",
                "The Defendant paid Rs. 6,00,000 on 14 March 2025 towards invoice INV-014",
                date="14 March 2025",
            ),
            I(
                "INVOICE",
                "INV-014",
                "deduction",
                "Rs. 3,00,000",
                "entitled to withhold Rs. 3,00,000 on account of defects",
            ),
            I(
                "ALLEGATION",
                "defective_work",
                "asserted",
                "true",
                "on account of defects in the delivered modules",
            ),
        ],
    ),
    Doc(
        "09_Order_12_September_2025.pdf",
        2,
        "ORDER",
        "Order dated 12 September 2025",
        "12 September 2025",
        ORDER,
        items=[
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
                kind="DIRECTION",
            ),
            I(
                "DIRECTION",
                "admission_denial_of_documents",
                "due_date",
                "within six weeks from today",
                "The Defendant shall file an affidavit of admission and denial of documents within six weeks from today",
                kind="DIRECTION",
            ),
            I(
                "DIRECTION",
                "admission_denial_of_documents",
                "responsible_party",
                "the Defendant",
                "The Defendant shall file an affidavit of admission and denial of documents within six weeks from today",
                kind="DIRECTION",
            ),
            I(
                "HEARING",
                "next hearing",
                "next_date",
                "14 November 2025",
                "The matter shall be listed on 14 November 2025 for framing of issues",
            ),
            I(
                "HEARING",
                "next hearing",
                "purpose",
                "framing of issues",
                "The matter shall be listed on 14 November 2025 for framing of issues",
            ),
        ],
    ),
]

QUESTIONS = [
    Question(
        "M2-B1-Q01",
        1,
        "What is the contract value under the Master Services Agreement?",
        ["contract/msa-2023/contract_value = 4800000"],
        ["48,00,000"],
        [{"document": "Master Services Agreement", "page": 1}],
    ),
    Question(
        "M2-B1-Q02",
        1,
        "When was delivery due under the contract?",
        ["contract/msa-2023/delivery_date = 2024-06-30"],
        ["30 Jun 2024"],
        [{"document": "Master Services Agreement", "page": 1}],
        must_not_say=["15 Aug 2024"],
    ),
    Question(
        "M2-B1-Q03",
        1,
        "How much is unpaid on INV-014?",
        ["invoice/inv-014/amount_outstanding = 1840000"],
        ["18,40,000"],
        [{"document": "Plaint", "page": 1}],
    ),
    Question(
        "M2-B1-Q04",
        1,
        "Was the legal notice of 5 February 2025 served on the defendant?",
        ["notice/2025-02-05-vardhan/received = true"],
        ["served"],
        [{"document": "Plaint", "page": 1}],
    ),
    Question(
        "M2-B1-Q05",
        1,
        "What relief does the plaintiff seek?",
        [],
        ["Recovery", "18,40,000"],
        [{"document": "Plaint", "page": 1}],
        intent="CLAIMS",
    ),
    Question("M2-B1-Q06", 1, "Who is the Defendant's lead counsel?", [], [], not_found=True),
    Question(
        "M2-B1-Q07",
        1,
        "What does the law say about liquidated damages and penalty clauses?",
        [],
        [],
        intent="LEGAL_RESEARCH",
    ),
    Question(
        "M2-B1-Q08",
        1,
        "Give me the chronology of the matter.",
        [],
        ["12 Jan 2023", "5 Feb 2025"],
        intent="CHRONOLOGY",
    ),
    Question(
        "M2-B2-Q09",
        2,
        "What changed since the last batch?",
        [],
        ["31 Jul 2024", "12,40,000"],
        intent="WHAT_CHANGED",
    ),
    Question(
        "M2-B2-Q10",
        2,
        "When is delivery due now?",
        ["contract/msa-2023/delivery_date = 2024-07-31"],
        ["31 Jul 2024"],
        [{"document": "Amendment No. 1", "page": 1}],
        must_not_say=["due 30 Jun 2024", "Delivery / completion date (MSA-2023): 30 Jun 2024"],
    ),
    Question(
        "M2-B2-Q11",
        2,
        "How much is still unpaid on INV-014?",
        ["invoice/inv-014/amount_outstanding = 1240000"],
        ["12,40,000"],
        [{"document": "Bank Statement", "page": 1}],
        must_not_say=["Outstanding on INV-014: ₹18,40,000", "Amount outstanding (INV-014): ₹18,40,000"],
    ),
    Question(
        "M2-B2-Q12",
        2,
        "Was the legal notice received by the defendant?",
        [],
        ["not received"],
        [{"document": "Written Statement", "page": 1}],
    ),
    Question(
        "M2-B2-Q13",
        2,
        "What has the court directed and by when?",
        [],
        ["10 Oct 2025", "24 Oct 2025"],
        [{"document": "Order dated 12 September 2025", "page": 1}],
        intent="DIRECTIONS",
    ),
    Question(
        "M2-B2-Q14",
        2,
        "What is the next hearing date?",
        ["hearing/2025-09-12/next_date = 2025-11-14"],
        ["14 Nov 2025"],
        [{"document": "Order dated 12 September 2025", "page": 1}],
    ),
]

PLANTED = [
    Planted(1, "CORROBORATED", "R1", "contract/msa-2023/delivery_date"),
    Planted(1, "NEW", "R8", "contract/msa-2023/delivery_date"),
    Planted(2, "SUPERSEDED", "R2", "contract/msa-2023/delivery_date"),
    Planted(2, "NARROWED", "R5", "invoice/inv-014/amount_outstanding"),
    Planted(2, "DISPUTED", "R6", "notice/2025-02-05-vardhan/received"),
    Planted(2, "NEW", "R0", "direction/replication/due_date"),
    Planted(2, "CORROBORATED", "R1", "payment/2025-03-14/amount"),
]

PROBES = [
    Probe("liquidated damages per week of delay", "Master Services Agreement"),
    Probe("which courts have jurisdiction", "Master Services Agreement"),
    Probe("interest on delayed payments", "Master Services Agreement"),
    Probe("invoice INV-014 payment due date", "Tax Invoice INV-014"),
    Probe("NEFT credit from Kestrel", "Bank Statement"),
    Probe("defects in the delivered modules", "Written Statement"),
    Probe("listed for framing of issues", "Order dated 12 September 2025"),
    Probe("Go-Live Date substituted", "Amendment No. 1"),
]

MATTER = Matter(
    id="M2",
    number="CS(COMM) 412/2025",
    title="Vardhan Infotech Private Limited v Kestrel Limited",
    matter_type="PAYMENT_RECOVERY",
    forum="High Court of Delhi, Commercial Division",
    parties=[
        Party("vardhan", "Vardhan Infotech Private Limited", "PLAINTIFF", ["Vardhan", "the Supplier"]),
        Party("kestrel", "Kestrel Limited", "DEFENDANT", ["Kestrel", "the Customer"]),
    ],
    docs=DOCS,
    questions=QUESTIONS,
    planted=PLANTED,
    probes=PROBES,
    description="Unpaid milestone invoice; delivery date moved by a signed amendment; part-payment; notice served vs never received.",
    authorities_expected=["indian-contract-act-1872-s74", "commercial-courts-act-2015-s12a"],
)
