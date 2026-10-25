"""M1: Breach / non-performance. Orion Retail Limited v Brightwave Systems Private Limited (all invented).

Planted: R2 (signed change request moves a milestone), R1 (plaint restates it), R7 (a pleading contradicts the plaintiff's own
earlier e-mail), R6 (the two sides plead different acceptance dates), R9 (an un-amended replication changes the claim),
R4 (an amended plaint supersedes it), R3 (a later order moves a deadline), COMPLIED (replication filed in time), R0 directions.
"""

from __future__ import annotations

from ..spec import Doc, I, Matter, Party, Planted, Probe, Question

SOW = """# STATEMENT OF WORK
This Statement of Work is made on 3 April 2023 between Brightwave Systems Private Limited (the Supplier) and Orion Retail Limited (the Customer).
1. SCOPE AND FEES
1.1 The Supplier shall design, supply and commission a warehouse automation system for the Customer (the System).
1.2 The total fees are Rs. 2,10,00,000 exclusive of taxes.
2. MILESTONES
2.1 Milestone 1 (go-live of the System) is due on 15 December 2023.
2.2 Milestone 2 (stabilisation and handover) is due 90 days after Milestone 1.
3. LIQUIDATED DAMAGES
3.1 For each week of delay in Milestone 1 the Supplier shall pay liquidated damages of 1% of the fees, capped at 10% of the fees.
4. ACCEPTANCE
4.1 The Customer shall confirm acceptance in writing within 7 days of a successful user acceptance test.
5. GOVERNING LAW
5.1 This Statement of Work is governed by the laws of India and the courts at Delhi have exclusive jurisdiction.
Signed by Brightwave Systems Private Limited (Authorised Signatory: P. Nair)
Signed by Orion Retail Limited (Authorised Signatory: S. Bhatia)
"""

CR1 = """# CHANGE REQUEST NO. 1 TO STATEMENT OF WORK
This Change Request is made on 20 October 2023 between Brightwave Systems Private Limited and Orion Retail Limited and varies the Statement of Work dated 3 April 2023.
1. The due date of Milestone 1 under the Statement of Work is changed from 15 December 2023 to 31 January 2024.
2. All other terms of the Statement of Work remain unchanged.
Signed by Brightwave Systems Private Limited (Authorised Signatory: P. Nair)
Signed by Orion Retail Limited (Authorised Signatory: S. Bhatia)
"""

EMAILS = """From: S. Bhatia <bhatia@orion.example>
To: P. Nair <nair@brightwave.example>
Date: 5 January 2024
Subject: Status of the warehouse system
The user acceptance test has failed twice. We reserve our right to claim liquidated damages if go-live slips beyond 31 January 2024.
From: S. Bhatia <bhatia@orion.example>
To: P. Nair <nair@brightwave.example>
Date: 16 February 2024
Subject: Go-live confirmed
We confirm that Milestone 1 under the Statement of Work was accepted on 15 February 2024 after the user acceptance test.
"""

NOTICE = """# LEGAL NOTICE
Dated: 10 March 2024
Sent by speed post and e-mail
To: Brightwave Systems Private Limited
Under instructions from Orion Retail Limited, I serve the following notice.
1. The Statement of Work dated 3 April 2023 required Milestone 1 to be completed by 31 January 2024.
2. The System went live late and my client is entitled to liquidated damages under clause 3.1.
3. You are called upon to pay Rs. 16,80,000 within 15 days of this notice.
Advocate for Orion Retail Limited
"""

PLAINT = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 188/2025
Orion Retail Limited v Brightwave Systems Private Limited
PLAINT under Order VII Rule 1 of the Code of Civil Procedure, 1908
1. The Plaintiff, Orion Retail Limited, is a retailer. The Defendant, Brightwave Systems Private Limited, supplies warehouse automation systems.
2. By a Statement of Work dated 3 April 2023 (the SOW) the Defendant agreed to supply a warehouse automation system for fees of Rs. 2,10,00,000.
3. By Change Request No. 1 dated 20 October 2023 the due date of Milestone 1 under the SOW was changed to 31 January 2024.
4. The Defendant failed to deliver by that date. The Plaintiff accepted Milestone 1 only on 28 March 2024 after repeated failures.
5. The delay is eight weeks. Under clause 3.1 of the SOW the Plaintiff is entitled to liquidated damages of Rs. 16,80,000.
6. The Plaintiff served a legal notice on 10 March 2024 but the Defendant did not pay.
PRAYER
The Plaintiff therefore prays for:
(a) a decree for Rs. 16,80,000 against the Defendant;
(b) interest at 9% per annum;
(c) costs of the suit.
Dated this 10 April 2025
Advocate for the Plaintiff
"""

WS = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 188/2025
Orion Retail Limited v Brightwave Systems Private Limited
WRITTEN STATEMENT on behalf of the Defendant
1. The suit is denied. The Defendant answers the Plaint as set out below.
2. Milestone 1 under the SOW was accepted on 15 February 2024, as the Plaintiff itself confirmed by its e-mail dated 16 February 2024.
3. There was no delay beyond the extended due date of 31 January 2024 that is attributable to the Defendant.
4. It is denied that the Plaintiff is entitled to liquidated damages.
Dated this 20 June 2025
Advocate for the Defendant
"""

ORDER1 = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 188/2025
Orion Retail Limited v Brightwave Systems Private Limited
ORDER
Date of order: 15 July 2025
1. The written statement is taken on record.
2. The Plaintiff shall file a replication within three weeks from today.
3. The Defendant shall file an affidavit of admission and denial of documents within four weeks from today.
4. The matter shall be listed on 10 September 2025 for framing of issues.
"""

REPLICATION = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 188/2025
Orion Retail Limited v Brightwave Systems Private Limited
REPLICATION to the written statement of the Defendant
1. The averments in the written statement are denied and the plaint is reiterated.
2. The delay was nine weeks, so the liquidated damages claimable are Rs. 18,90,000.
Dated this 25 July 2025
Advocate for the Plaintiff
"""

AMENDED = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 188/2025
Orion Retail Limited v Brightwave Systems Private Limited
AMENDED PLAINT (amended under Order VI Rule 17 of the Code of Civil Procedure, 1908)
1. The Plaintiff amends paragraph 5 of the plaint. The liquidated damages claimed are Rs. 21,00,000, being the maximum of 10% of the fees under clause 3.1 of the SOW.
2. The Plaintiff also prays for costs of the suit.
Dated this 5 September 2025
Advocate for the Plaintiff
"""

ORDER2 = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 188/2025
Orion Retail Limited v Brightwave Systems Private Limited
ORDER
Date of order: 10 September 2025
1. The amended plaint is taken on record.
2. The time for the Defendant to file the affidavit of admission and denial of documents is extended to 30 September 2025.
3. The matter shall be listed on 12 November 2025 for framing of issues.
"""

SOW_REF = "the Statement of Work dated 3 April 2023"
M1_REF = "Milestone 1 under the Statement of Work"

DOCS = [
    Doc(
        "01_Statement_of_Work.pdf",
        1,
        "SOW",
        "Statement of Work",
        "3 April 2023",
        SOW,
        signed=True,
        suit_roles=False,
        terms=[("the Supplier", "brightwave"), ("the Customer", "orion")],
        items=[
            I(
                "CONTRACT",
                "Statement of Work",
                "effective_date",
                "3 April 2023",
                "This Statement of Work is made on 3 April 2023",
            ),
            I(
                "CONTRACT",
                "Statement of Work",
                "contract_value",
                "Rs. 2,10,00,000",
                "The total fees are Rs. 2,10,00,000 exclusive of taxes",
            ),
            I(
                "MILESTONE",
                "Milestone 1 under the Statement of Work",
                "due_date",
                "15 December 2023",
                "Milestone 1 (go-live of the System) is due on 15 December 2023",
            ),
            I(
                "CONTRACT",
                "Statement of Work",
                "ld_rate",
                "1% of the fees per week of delay",
                "liquidated damages of 1% of the fees",
            ),
            I("CONTRACT", "Statement of Work", "ld_cap", "10% of the fees", "capped at 10% of the fees"),
            I(
                "CONTRACT",
                "Statement of Work",
                "governing_law",
                "laws of India",
                "This Statement of Work is governed by the laws of India",
            ),
            I(
                "CONTRACT",
                "Statement of Work",
                "jurisdiction",
                "courts at Delhi",
                "the courts at Delhi have exclusive jurisdiction",
            ),
        ],
    ),
    Doc(
        "02_Change_Request_No_1.pdf",
        1,
        "CHANGE_REQUEST",
        "Change Request No. 1 to Statement of Work",
        "20 October 2023",
        CR1,
        signed=True,
        suit_roles=False,
        amends=SOW_REF,
        terms=[],
        items=[
            I(
                "MILESTONE",
                M1_REF,
                "due_date",
                "31 January 2024",
                "changed from 15 December 2023 to 31 January 2024",
            ),
        ],
    ),
    Doc(
        "03_Emails_status_and_go_live.pdf",
        1,
        "EMAIL",
        "Status and go-live (e-mail thread)",
        "16 February 2024",
        EMAILS,
        suit_roles=False,
        items=[
            I(
                "MILESTONE",
                M1_REF,
                "acceptance_date",
                "15 February 2024",
                "Milestone 1 under the Statement of Work was accepted on 15 February 2024",
            ),
        ],
    ),
    Doc(
        "04_Legal_Notice_LD.pdf",
        1,
        "LEGAL_NOTICE",
        "Legal Notice",
        "10 March 2024",
        NOTICE,
        author="orion",
        suit_roles=False,
        items=[
            I("NOTICE", "this notice", "sent_date", "10 March 2024", "Dated: 10 March 2024"),
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
                "Rs. 16,80,000",
                "You are called upon to pay Rs. 16,80,000 within 15 days of this notice",
            ),
        ],
    ),
    Doc(
        "05_Plaint.pdf",
        2,
        "PLAINT",
        "Plaint",
        "10 April 2025",
        PLAINT,
        author="orion",
        items=[
            I("CONTRACT", "the SOW", "contract_value", "Rs. 2,10,00,000", "for fees of Rs. 2,10,00,000"),
            I(
                "MILESTONE",
                "Milestone 1 under the SOW",
                "due_date",
                "31 January 2024",
                "the due date of Milestone 1 under the SOW was changed to 31 January 2024",
            ),
            I(
                "MILESTONE",
                "Milestone 1 under the SOW",
                "acceptance_date",
                "28 March 2024",
                "The Plaintiff accepted Milestone 1 only on 28 March 2024",
            ),
            I(
                "CLAIM",
                "damages",
                "amount",
                "Rs. 16,80,000",
                "entitled to liquidated damages of Rs. 16,80,000",
            ),
            I("RELIEF", "recovery", "sought", "true", "a decree for Rs. 16,80,000 against the Defendant"),
            I(
                "RELIEF",
                "recovery",
                "amount",
                "Rs. 16,80,000",
                "a decree for Rs. 16,80,000 against the Defendant",
            ),
            I("ALLEGATION", "delay", "asserted", "true", "The Defendant failed to deliver by that date"),
        ],
    ),
    Doc(
        "06_Written_Statement.pdf",
        2,
        "WRITTEN_STATEMENT",
        "Written Statement",
        "20 June 2025",
        WS,
        author="brightwave",
        items=[
            I(
                "MILESTONE",
                "Milestone 1 under the SOW",
                "acceptance_date",
                "15 February 2024",
                "Milestone 1 under the SOW was accepted on 15 February 2024",
            ),
            I(
                "ALLEGATION",
                "delay",
                "denied",
                "true",
                "There was no delay beyond the extended due date of 31 January 2024",
            ),
        ],
    ),
    Doc(
        "07_Order_15_July_2025.pdf",
        2,
        "ORDER",
        "Order dated 15 July 2025",
        "15 July 2025",
        ORDER1,
        items=[
            I(
                "DIRECTION",
                "replication",
                "due_date",
                "within three weeks from today",
                "The Plaintiff shall file a replication within three weeks from today",
                kind="DIRECTION",
            ),
            I(
                "DIRECTION",
                "replication",
                "responsible_party",
                "the Plaintiff",
                "The Plaintiff shall file a replication within three weeks from today",
            ),
            I(
                "DIRECTION",
                "admission_denial_of_documents",
                "due_date",
                "within four weeks from today",
                "The Defendant shall file an affidavit of admission and denial of documents within four weeks from today",
                kind="DIRECTION",
            ),
            I(
                "DIRECTION",
                "admission_denial_of_documents",
                "responsible_party",
                "the Defendant",
                "The Defendant shall file an affidavit of admission and denial of documents within four weeks from today",
            ),
            I(
                "HEARING",
                "next hearing",
                "next_date",
                "10 September 2025",
                "The matter shall be listed on 10 September 2025 for framing of issues",
            ),
        ],
    ),
    Doc(
        "08_Replication.pdf",
        3,
        "REPLICATION",
        "Replication",
        "25 July 2025",
        REPLICATION,
        author="orion",
        items=[
            I(
                "CLAIM",
                "damages",
                "amount",
                "Rs. 18,90,000",
                "the liquidated damages claimable are Rs. 18,90,000",
            ),
        ],
    ),
    Doc(
        "09_Amended_Plaint.pdf",
        3,
        "AMENDED_PLEADING",
        "Amended Plaint",
        "5 September 2025",
        AMENDED,
        author="orion",
        items=[
            I(
                "CLAIM",
                "damages",
                "amount",
                "Rs. 21,00,000",
                "The liquidated damages claimed are Rs. 21,00,000",
            ),
        ],
    ),
    Doc(
        "10_Order_10_September_2025.pdf",
        3,
        "ORDER",
        "Order dated 10 September 2025",
        "10 September 2025",
        ORDER2,
        items=[
            I(
                "DIRECTION",
                "admission_denial_of_documents",
                "due_date",
                "30 September 2025",
                "is extended to 30 September 2025",
                kind="DIRECTION",
            ),
            I(
                "DIRECTION",
                "admission_denial_of_documents",
                "responsible_party",
                "the Defendant",
                "The time for the Defendant to file the affidavit of admission and denial of documents is extended",
            ),
            I(
                "HEARING",
                "next hearing",
                "next_date",
                "12 November 2025",
                "The matter shall be listed on 12 November 2025 for framing of issues",
            ),
        ],
    ),
]

QUESTIONS = [
    Question(
        "M1-B1-Q01",
        1,
        "What is the contract value under the Statement of Work?",
        ["contract/sow-2023/contract_value = 21000000"],
        ["2,10,00,000"],
        [{"document": "Statement of Work", "page": 1}],
    ),
    Question(
        "M1-B1-Q02",
        1,
        "When is Milestone 1 due?",
        ["milestone/sow-2023-m1/due_date = 2024-01-31"],
        ["31 Jan 2024"],
        [{"document": "Change Request", "page": 1}],
        must_not_say=["due 15 Dec 2023"],
    ),
    Question(
        "M1-B1-Q03",
        1,
        "What are the liquidated damages for delay?",
        ["contract/sow-2023/ld_rate = 1% of the fees per week of delay"],
        ["1% of the fees"],
        [{"document": "Statement of Work", "page": 1}],
    ),
    Question(
        "M1-B1-Q04",
        1,
        "When was Milestone 1 accepted?",
        ["milestone/sow-2023-m1/acceptance_date = 2024-02-15"],
        ["15 Feb 2024"],
        [{"document": "e-mail thread", "page": 1}],
    ),
    Question("M1-B1-Q05", 1, "Who is the Plaintiff's advocate?", [], [], not_found=True),
    Question(
        "M1-B2-Q06",
        2,
        "When was Milestone 1 accepted?",
        [],
        ["28 Mar 2024", "15 Feb 2024"],
        [{"document": "Plaint", "page": 1}, {"document": "Written Statement", "page": 1}],
    ),
    Question(
        "M1-B2-Q07", 2, "What changed since the last batch?", [], ["28 Mar 2024"], intent="WHAT_CHANGED"
    ),
    Question(
        "M1-B2-Q08",
        2,
        "What has the court directed and by when?",
        [],
        ["5 Aug 2025", "12 Aug 2025"],
        [{"document": "Order dated 15 July 2025", "page": 1}],
        intent="DIRECTIONS",
    ),
    Question(
        "M1-B2-Q09",
        2,
        "What is the plaintiff's claim?",
        ["claim/damages/amount = 1680000"],
        ["16,80,000"],
        [{"document": "Plaint", "page": 1}],
    ),
    Question(
        "M1-B3-Q10",
        3,
        "What is the plaintiff's current claim for liquidated damages?",
        ["claim/damages/amount = 2100000"],
        ["21,00,000"],
        [{"document": "Amended Plaint", "page": 1}],
        must_not_say=["Claim for Damages: amount ₹16,80,000", "Claim for Damages: amount ₹18,90,000"],
    ),
    Question(
        "M1-B3-Q11",
        3,
        "What is the deadline for the affidavit of admission and denial of documents?",
        ["direction/admission-denial-of-documents/due_date = 2025-09-30"],
        ["30 Sep 2025"],
        [{"document": "Order dated 10 September 2025", "page": 1}],
        must_not_say=["due 12 Aug 2025"],
    ),
    Question(
        "M1-B3-Q12",
        3,
        "What is the next hearing date?",
        ["hearing/2025-09-10/next_date = 2025-11-12"],
        ["12 Nov 2025"],
    ),
]

PLANTED = [
    Planted(1, "SUPERSEDED", "R2", "milestone/sow-2023-m1/due_date"),
    Planted(2, "CORROBORATED", "R1", "milestone/sow-2023-m1/due_date"),
    Planted(2, "CONTRADICTED_BY_EVIDENCE", "R7", "milestone/sow-2023-m1/acceptance_date"),
    Planted(2, "DISPUTED", "R6", "milestone/sow-2023-m1/acceptance_date"),
    Planted(2, "NEW", "R0", "direction/replication/due_date"),
    Planted(3, "DISPUTED", "R9", "claim/damages/amount"),
    Planted(3, "SUPERSEDED", "R4", "claim/damages/amount"),
    Planted(3, "SUPERSEDED", "R3", "direction/admission-denial-of-documents/due_date"),
    Planted(3, "COMPLIED", "COMPLY", "direction/replication/due_date"),
]

PROBES = [
    Probe("liquidated damages per week of delay capped", "Statement of Work"),
    Probe("due date of Milestone 1 changed", "Change Request"),
    Probe("user acceptance test confirmed go-live accepted", "e-mail thread"),
    Probe("delay of eight weeks liquidated damages claimed", "Plaint"),
    Probe("replication within three weeks from today", "Order dated 15 July 2025"),
    Probe("damages claimed maximum of 10% of the fees amended", "Amended Plaint"),
]

MATTER = Matter(
    id="M1",
    number="CS(COMM) 188/2025",
    title="Orion Retail Limited v Brightwave Systems Private Limited",
    matter_type="BREACH",
    forum="High Court of Delhi, Commercial Division",
    parties=[
        Party("orion", "Orion Retail Limited", "PLAINTIFF", ["Orion", "the Customer"]),
        Party(
            "brightwave", "Brightwave Systems Private Limited", "DEFENDANT", ["Brightwave", "the Supplier"]
        ),
    ],
    docs=DOCS,
    questions=QUESTIONS,
    planted=PLANTED,
    probes=PROBES,
    description="Delayed warehouse-automation go-live; a signed change request moves the milestone; the sides plead different acceptance dates; the claim is revised.",
    authorities_expected=[
        "indian-contract-act-1872-s55",
        "indian-contract-act-1872-s74",
        "kailash-nath-associates-v-dda",
    ],
)
