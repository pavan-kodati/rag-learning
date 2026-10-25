"""M3: Termination / injunction. Sunrise Beverages Private Limited v Coastal Brands Limited (all invented).

Planted: a conflict on the date a notice was received (R9 before the parties' roles are known, R6 once they are), a scanned
termination letter (OCR), R1 (WS restates the arbitration clause), R3 (a later order extends the interim relief), R8 (a
hearing note that disagrees with the order), a direction whose period runs 'from receipt of a copy' (no due date), a duplicate.
"""

from __future__ import annotations

from ..spec import Doc, I, Matter, Party, Planted, Probe, Question

AGREEMENT = """# EXCLUSIVE DISTRIBUTION AGREEMENT
This Agreement is made on 1 July 2022 between Coastal Brands Limited (the Principal) and Sunrise Beverages Private Limited (the Distributor).
1. APPOINTMENT AND TARGETS
1.1 The Principal appoints the Distributor as its exclusive distributor for the State of Rajasthan for five years from 1 July 2022.
1.2 The Distributor shall purchase a minimum of 50,000 cases in every quarter.
2. TERMINATION
2.1 Either party may terminate this Agreement for convenience by giving 90 days written notice.
2.2 A party in breach shall have 30 days from receipt of written notice to cure the breach, failing which the other party may terminate.
3. DISPUTES
3.1 Any dispute shall be referred to arbitration seated at Delhi under the Arbitration and Conciliation Act, 1996.
3.2 Nothing in this clause prevents either party from seeking interim relief from the courts at Delhi.
Signed by Coastal Brands Limited (Authorised Signatory: M. Iyer)
Signed by Sunrise Beverages Private Limited (Authorised Signatory: R. Kapoor)
"""

CURE = """# NOTICE OF BREACH
Dated: 2 February 2025
Delivered by courier on 3 February 2025
To: Sunrise Beverages Private Limited
Under instructions from Coastal Brands Limited, I give you this notice.
1. You purchased only 31,000 cases in the quarter ended 31 December 2024 against the minimum of 50,000 cases.
2. You are called upon to cure the breach within 30 days of receipt of this notice.
Advocate for Coastal Brands Limited
"""

REPLY = """# REPLY TO NOTICE OF BREACH
Dated: 20 February 2025
To: Coastal Brands Limited
1. My client received your notice dated 2 February 2025 only on 10 February 2025.
2. The shortfall in purchases was caused by repeated failures of supply by your company.
3. The alleged breach is denied.
Advocate for Sunrise Beverages Private Limited
"""

TERMINATION = """# NOTICE OF TERMINATION
Dated: 10 March 2025
Sent by courier
To: Sunrise Beverages Private Limited
1. The breach was not cured within 30 days.
2. The Exclusive Distribution Agreement stands terminated with effect from 10 March 2025.
Advocate for Coastal Brands Limited
"""

PLAINT = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 77/2025
Sunrise Beverages Private Limited v Coastal Brands Limited
PLAINT for declaration and permanent injunction
1. The Plaintiff, Sunrise Beverages Private Limited, is the exclusive distributor of the Defendant, Coastal Brands Limited, for the State of Rajasthan.
2. By an Exclusive Distribution Agreement dated 1 July 2022 the Plaintiff was appointed for five years and is allowed 30 days to cure any breach.
3. The Defendant's notice of breach dated 2 February 2025 was received by the Plaintiff on 10 February 2025.
4. The Defendant terminated the agreement on 10 March 2025, before the 30 days to cure had expired.
5. The termination is wrongful and the Plaintiff has suffered irreparable injury to its business and goodwill.
PRAYER
The Plaintiff therefore prays for:
(a) a declaration that the termination dated 10 March 2025 is invalid;
(b) a permanent injunction restraining the Defendant from appointing any other distributor in Rajasthan;
(c) costs of the suit.
Dated this 25 March 2025
Advocate for the Plaintiff
"""

APPLICATION = """# APPLICATION UNDER ORDER XXXIX RULES 1 AND 2 OF THE CODE OF CIVIL PROCEDURE, 1908
CS(COMM) 77/2025
Sunrise Beverages Private Limited v Coastal Brands Limited
1. The Plaintiff has a prima facie case because the termination was issued before the cure period expired.
2. The balance of convenience favours the Plaintiff, whose distribution network will collapse if the Defendant appoints another distributor.
3. The Plaintiff will suffer irreparable injury if no interim injunction is granted.
PRAYER
The Plaintiff prays for an interim injunction restraining the Defendant from appointing any other distributor in Rajasthan.
Dated this 25 March 2025
Advocate for the Plaintiff
"""

AFFIDAVIT = """# AFFIDAVIT OF MR R. KAPOOR
CS(COMM) 77/2025
I, R. Kapoor, director of Sunrise Beverages Private Limited, solemnly affirm as follows.
1. I am authorised to swear this affidavit on behalf of the Plaintiff.
2. The notice of breach dated 2 February 2025 was received at our office on 10 February 2025.
3. The contents of the plaint and the application are true to my knowledge.
Deponent
Verified at New Delhi on 25 March 2025
"""

ORDER1 = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 77/2025
Sunrise Beverages Private Limited v Coastal Brands Limited
ORDER
Date of order: 28 March 2025
1. Notice is issued on the application.
2. The Defendant shall maintain status quo until the next date of hearing.
3. The Defendant shall file its reply to the application within three weeks from receipt of a copy of this order.
4. The matter shall be listed on 30 April 2025.
"""

WS = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 77/2025
Sunrise Beverages Private Limited v Coastal Brands Limited
WRITTEN STATEMENT on behalf of the Defendant
1. The suit is not maintainable. Clause 3.1 of the agreement requires every dispute to be referred to arbitration.
2. It is denied that the notice of breach was received on 10 February 2025. It was delivered on 3 February 2025 and the courier proof is on record.
3. The cure period of 30 days therefore expired on 5 March 2025 and the termination on 10 March 2025 is valid.
4. It is denied that the termination is wrongful.
Dated this 5 May 2025
Advocate for the Defendant
"""

ORDER2 = """# IN THE HIGH COURT OF DELHI AT NEW DELHI
CS(COMM) 77/2025
Sunrise Beverages Private Limited v Coastal Brands Limited
ORDER
Date of order: 12 May 2025
1. The written statement is taken on record.
2. The interim order of status quo is extended until 15 December 2025.
3. The matter shall be listed on 12 November 2025.
"""

NOTE = """# HEARING NOTE
CS(COMM) 77/2025
Hearing of 12 May 2025: internal note by junior counsel
1. The court has extended the status quo only until 30 June 2025.
2. The matter is to be listed on 20 November 2025.
"""

AGR_REF = "the Exclusive Distribution Agreement dated 1 July 2022"
NOTICE_REF = "the notice of breach dated 2 February 2025"

DOCS = [
    Doc(
        "01_Exclusive_Distribution_Agreement.pdf",
        1,
        "CONTRACT",
        "Exclusive Distribution Agreement",
        "1 July 2022",
        AGREEMENT,
        signed=True,
        suit_roles=False,
        terms=[("the Principal", "coastal"), ("the Distributor", "sunrise")],
        items=[
            I(
                "CONTRACT",
                "Exclusive Distribution Agreement",
                "effective_date",
                "1 July 2022",
                "This Agreement is made on 1 July 2022",
            ),
            I(
                "CONTRACT",
                "Exclusive Distribution Agreement",
                "scope",
                "exclusive distributor for the State of Rajasthan",
                "exclusive distributor for the State of Rajasthan",
            ),
            I(
                "CONTRACT",
                "Exclusive Distribution Agreement",
                "termination_for_convenience",
                "true",
                "Either party may terminate this Agreement for convenience by giving 90 days written notice",
            ),
            I(
                "CONTRACT",
                "Exclusive Distribution Agreement",
                "termination_notice_days",
                "90 days",
                "for convenience by giving 90 days written notice",
            ),
            I(
                "CONTRACT",
                "Exclusive Distribution Agreement",
                "cure_period_days",
                "30 days",
                "A party in breach shall have 30 days from receipt of written notice to cure the breach",
            ),
            I(
                "CONTRACT",
                "Exclusive Distribution Agreement",
                "arbitration_clause",
                "true",
                "Any dispute shall be referred to arbitration seated at Delhi",
            ),
            I(
                "CONTRACT",
                "Exclusive Distribution Agreement",
                "jurisdiction",
                "arbitration seated at Delhi; courts at Delhi for interim relief",
                "arbitration seated at Delhi",
            ),
        ],
    ),
    Doc(
        "02_Notice_of_Breach_2_Feb_2025.pdf",
        1,
        "LEGAL_NOTICE",
        "Notice of Breach",
        "2 February 2025",
        CURE,
        author="coastal",
        suit_roles=False,
        items=[
            I("NOTICE", "this notice", "sent_date", "2 February 2025", "Dated: 2 February 2025"),
            I(
                "NOTICE",
                "this notice",
                "received_date",
                "3 February 2025",
                "Delivered by courier on 3 February 2025",
            ),
            I(
                "NOTICE",
                "this notice",
                "mode_of_service",
                "courier",
                "Delivered by courier on 3 February 2025",
            ),
            I(
                "NOTICE",
                "this notice",
                "cure_demanded",
                "cure the breach within 30 days of receipt of this notice",
                "You are called upon to cure the breach within 30 days of receipt of this notice",
            ),
            I(
                "ALLEGATION",
                "minimum purchase shortfall",
                "asserted",
                "true",
                "You purchased only 31,000 cases in the quarter ended 31 December 2024 against the minimum of 50,000 cases",
            ),
        ],
    ),
    Doc(
        "03_Reply_to_Notice_20_Feb_2025.pdf",
        1,
        "REPLY_NOTICE",
        "Reply to Notice of Breach",
        "20 February 2025",
        REPLY,
        author="sunrise",
        suit_roles=False,
        items=[
            I(
                "NOTICE",
                NOTICE_REF,
                "received_date",
                "10 February 2025",
                "received your notice dated 2 February 2025 only on 10 February 2025",
                date="2 February 2025",
                party="Coastal Brands Limited",
            ),
            I("ALLEGATION", "minimum purchase shortfall", "denied", "true", "The alleged breach is denied"),
        ],
    ),
    Doc(
        "04_Notice_of_Termination_scanned.pdf",
        1,
        "LEGAL_NOTICE",
        "Notice of Termination",
        "10 March 2025",
        TERMINATION,
        author="coastal",
        suit_roles=False,
        scanned=True,
        items=[
            I("NOTICE", "this notice", "sent_date", "10 March 2025", "Dated: 10 March 2025"),
            I("NOTICE", "this notice", "mode_of_service", "courier", "Sent by courier"),
        ],
    ),
    Doc(
        "05_Plaint.pdf",
        2,
        "PLAINT",
        "Plaint",
        "25 March 2025",
        PLAINT,
        author="sunrise",
        items=[
            I("CONTRACT", AGR_REF, "cure_period_days", "30 days", "allowed 30 days to cure any breach"),
            I(
                "NOTICE",
                NOTICE_REF,
                "received_date",
                "10 February 2025",
                "was received by the Plaintiff on 10 February 2025",
                date="2 February 2025",
                party="the Defendant",
            ),
            I("ALLEGATION", "wrongful_termination", "asserted", "true", "The termination is wrongful"),
            I(
                "RELIEF",
                "declaration",
                "sought",
                "true",
                "a declaration that the termination dated 10 March 2025 is invalid",
            ),
            I(
                "RELIEF",
                "injunction",
                "sought",
                "true",
                "a permanent injunction restraining the Defendant from appointing any other distributor in Rajasthan",
            ),
            I("RELIEF", "costs", "sought", "true", "costs of the suit"),
        ],
    ),
    Doc(
        "06_Application_Order_39.pdf",
        2,
        "APPLICATION",
        "Application under Order XXXIX Rules 1 and 2",
        "25 March 2025",
        APPLICATION,
        author="sunrise",
        items=[
            I(
                "RELIEF",
                "injunction",
                "sought",
                "true",
                "an interim injunction restraining the Defendant from appointing any other distributor in Rajasthan",
            ),
        ],
    ),
    Doc(
        "07_Affidavit_of_R_Kapoor.pdf",
        2,
        "AFFIDAVIT",
        "Affidavit of Mr R. Kapoor",
        "25 March 2025",
        AFFIDAVIT,
        author="sunrise",
        items=[
            I(
                "NOTICE",
                NOTICE_REF,
                "received_date",
                "10 February 2025",
                "was received at our office on 10 February 2025",
                date="2 February 2025",
                party="the Defendant",
            ),
        ],
    ),
    Doc(
        "08_Order_28_March_2025.pdf",
        2,
        "ORDER",
        "Order dated 28 March 2025",
        "28 March 2025",
        ORDER1,
        items=[
            I(
                "DIRECTION",
                "interim_relief",
                "due_date",
                "unspecified",
                "The Defendant shall maintain status quo until the next date of hearing",
                kind="INTERIM_RELIEF",
            ),
            I(
                "DIRECTION",
                "interim_relief",
                "responsible_party",
                "the Defendant",
                "The Defendant shall maintain status quo until the next date of hearing",
                kind="INTERIM_RELIEF",
            ),
            I(
                "DIRECTION",
                "reply to the application",
                "due_date",
                "within three weeks from receipt of a copy of this order",
                "within three weeks from receipt of a copy of this order",
                kind="DIRECTION",
            ),
            I(
                "DIRECTION",
                "reply to the application",
                "responsible_party",
                "the Defendant",
                "The Defendant shall file its reply to the application within three weeks",
                kind="DIRECTION",
            ),
            I(
                "HEARING",
                "next hearing",
                "next_date",
                "30 April 2025",
                "The matter shall be listed on 30 April 2025",
            ),
        ],
    ),
    Doc(
        "08b_Order_28_March_2025_copy.pdf",
        2,
        "ORDER",
        "Order dated 28 March 2025",
        "28 March 2025",
        ORDER1,
        is_duplicate_of="08_Order_28_March_2025.pdf",
    ),
    Doc(
        "09_Written_Statement.pdf",
        3,
        "WRITTEN_STATEMENT",
        "Written Statement",
        "5 May 2025",
        WS,
        author="coastal",
        items=[
            I(
                "CONTRACT",
                AGR_REF,
                "arbitration_clause",
                "true",
                "Clause 3.1 of the agreement requires every dispute to be referred to arbitration",
            ),
            I(
                "NOTICE",
                NOTICE_REF,
                "received_date",
                "3 February 2025",
                "It was delivered on 3 February 2025",
                date="2 February 2025",
                party="the Defendant",
            ),
            I(
                "ALLEGATION",
                "wrongful_termination",
                "denied",
                "true",
                "It is denied that the termination is wrongful",
            ),
        ],
    ),
    Doc(
        "10_Order_12_May_2025.pdf",
        3,
        "ORDER",
        "Order dated 12 May 2025",
        "12 May 2025",
        ORDER2,
        items=[
            I(
                "DIRECTION",
                "interim_relief",
                "due_date",
                "15 December 2025",
                "The interim order of status quo is extended until 15 December 2025",
                kind="INTERIM_RELIEF",
            ),
            I(
                "DIRECTION",
                "interim_relief",
                "responsible_party",
                "the Defendant",
                "The interim order of status quo is extended until 15 December 2025",
                kind="INTERIM_RELIEF",
            ),
            I(
                "HEARING",
                "next hearing",
                "next_date",
                "12 November 2025",
                "The matter shall be listed on 12 November 2025",
            ),
        ],
    ),
    Doc(
        "11_Hearing_note_12_May_2025.pdf",
        3,
        "HEARING_NOTE",
        "Hearing note, 12 May 2025",
        "12 May 2025",
        NOTE,
        suit_roles=True,
        items=[
            I(
                "DIRECTION",
                "interim_relief",
                "due_date",
                "30 June 2025",
                "The court has extended the status quo only until 30 June 2025",
                kind="INTERIM_RELIEF",
            ),
            I(
                "HEARING",
                "next hearing",
                "next_date",
                "20 November 2025",
                "The matter is to be listed on 20 November 2025",
            ),
        ],
    ),
]

QUESTIONS = [
    Question(
        "M3-B1-Q01",
        1,
        "What is the notice period for termination for convenience?",
        ["contract/eda-2022/termination_notice_days = 90"],
        ["90 days"],
        [{"document": "Exclusive Distribution Agreement", "page": 1}],
    ),
    Question(
        "M3-B1-Q02",
        1,
        "How long is the cure period?",
        ["contract/eda-2022/cure_period_days = 30"],
        ["30 days"],
    ),
    Question(
        "M3-B1-Q03",
        1,
        "Is there an arbitration clause?",
        ["contract/eda-2022/arbitration_clause = true"],
        [],
        [{"document": "Exclusive Distribution Agreement", "page": 1}],
    ),
    Question("M3-B1-Q04", 1, "When was the notice of breach received?", [], ["3 Feb 2025", "10 Feb 2025"]),
    Question("M3-B1-Q05", 1, "What is the Distributor's annual turnover?", [], [], not_found=True),
    Question(
        "M3-B2-Q06",
        2,
        "What relief does the plaintiff seek?",
        [],
        ["Declaration", "Injunction"],
        [{"document": "Plaint", "page": 1}],
        intent="CLAIMS",
    ),
    Question(
        "M3-B2-Q07",
        2,
        "What has the court directed?",
        [],
        ["30 Apr 2025"],
        [{"document": "Order dated 28 March 2025", "page": 1}],
        intent="DIRECTIONS",
    ),
    Question(
        "M3-B2-Q08",
        2,
        "What does the law say about interim injunctions and temporary injunction tests?",
        [],
        ["Order XXXIX"],
        intent="LEGAL_RESEARCH",
    ),
    Question(
        "M3-B3-Q09",
        3,
        "Until when does the status quo run?",
        ["direction/interim-relief/due_date = 2025-12-15"],
        ["15 Dec 2025"],
        [{"document": "Order dated 12 May 2025", "page": 1}],
        must_not_say=["30 Jun 2025"],
    ),
    Question(
        "M3-B3-Q10",
        3,
        "What is the next hearing date?",
        ["hearing/2025-05-12/next_date = 2025-11-12"],
        ["12 Nov 2025"],
        must_not_say=["20 Nov 2025"],
    ),
    Question(
        "M3-B3-Q11", 3, "What changed since the last batch?", [], ["15 Dec 2025"], intent="WHAT_CHANGED"
    ),
]

PLANTED = [
    Planted(1, "DISPUTED", "R9", "notice/2025-02-02-coastal/received_date"),
    Planted(2, "NEW", "R6", "notice/2025-02-02-coastal/received_date"),
    Planted(2, "CORROBORATED", "R1", "contract/eda-2022/cure_period_days"),
    Planted(2, "NEW", "R0", "direction/interim-relief/due_date"),
    Planted(3, "CORROBORATED", "R1", "contract/eda-2022/arbitration_clause"),
    Planted(3, "SUPERSEDED", "R3", "direction/interim-relief/due_date"),
    Planted(3, "NEW", "R8", "hearing/2025-05-12/next_date"),
]

PROBES = [
    Probe("minimum of 50,000 cases every quarter", "Exclusive Distribution Agreement"),
    Probe("terminated with effect from 10 March 2025", "Notice of Termination"),
    Probe("shortfall in purchases caused by failures of supply", "Reply to Notice of Breach"),
    Probe("balance of convenience irreparable injury", "Application under Order XXXIX"),
    Probe("status quo extended until", "Order dated 12 May 2025"),
    Probe("suit not maintainable arbitration", "Written Statement"),
]

MATTER = Matter(
    id="M3",
    number="CS(COMM) 77/2025",
    title="Sunrise Beverages Private Limited v Coastal Brands Limited",
    matter_type="TERMINATION_INJUNCTION",
    forum="High Court of Delhi, Commercial Division",
    parties=[
        Party("sunrise", "Sunrise Beverages Private Limited", "PLAINTIFF", ["Sunrise", "the Distributor"]),
        Party("coastal", "Coastal Brands Limited", "DEFENDANT", ["Coastal", "the Principal"]),
    ],
    docs=DOCS,
    questions=QUESTIONS,
    planted=PLANTED,
    probes=PROBES,
    description="Distributor terminated after a cure notice; the sides disagree on when the notice was received; interim status quo is extended; arbitration clause raised.",
    authorities_expected=[
        "code-of-civil-procedure-1908",
        "dalpat-kumar-v-prahlad-singh",
        "indian-oil-corp-v-amritsar-gas-service",
    ],
)
