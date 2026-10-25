"""M4: held-out style matter (all invented): different drafting conventions from M1-M3 (dd/mm/yyyy dates, un-numbered
headings, a rate card, letters). It carries NO recorded model output: it only works with a real model, which makes it a
fair test of extraction on documents the system has not been tuned to. (It was written by the same author as M1-M3; for a
truly independent test, have someone else write a matter in this folder format.)"""

from __future__ import annotations

from ..spec import Doc, Matter, Party, Planted, Probe, Question

CONTRACT = """LOGISTICS SERVICES CONTRACT
Contract dated 02/05/2023 between Orbit Logistics LLP ("Orbit") and Pinnacle Foods Private Limited ("Pinnacle").

Clause 1 - Services
Orbit shall transport finished goods of Pinnacle from its Pune plant to its depots in western India.

Clause 2 - Rates
The rate is Rs. 42 per km per truck. Fuel surcharge is included in the rate.

Clause 3 - Invoicing and payment
Orbit shall invoice monthly. Pinnacle shall pay each invoice within 45 days of the invoice date. Delayed amounts carry interest at 18% per annum.

Clause 4 - Term
This contract runs for two years from 02/05/2023.

Clause 5 - Disputes
Courts at Mumbai shall have exclusive jurisdiction.

For Orbit Logistics LLP: A. Deshmukh (Partner)
For Pinnacle Foods Private Limited: V. Rao (Director)
"""

INVOICE = """INVOICE NO. OL/2024/0087
Date: 28/02/2025
Billed to: Pinnacle Foods Private Limited
For: transport services for February 2025
Amount payable: Rs. 9,36,000
Due date: 14/04/2025
"""

EMAIL = """From: V. Rao <rao@pinnacle.example>
To: A. Deshmukh <deshmukh@orbit.example>
Date: 10/03/2025
Subject: Invoice OL/2024/0087
We dispute Rs. 1,20,000 of this invoice because of damaged goods on two trips. We will pay the balance of Rs. 8,16,000 by 31/03/2025.
"""

NOTICE = """LEGAL NOTICE
Date: 20/05/2025
To: Pinnacle Foods Private Limited
Under instructions from Orbit Logistics LLP we call upon you to pay Rs. 1,20,000 outstanding against invoice OL/2024/0087 together with interest at 18% per annum within 15 days of this notice, failing which our client will sue you.
Advocate for Orbit Logistics LLP
"""

BANK = """STATEMENT OF ACCOUNT
Account holder: Orbit Logistics LLP
Period: 01/04/2025 to 30/04/2025
02/04/2025 RTGS credit Pinnacle Foods Private Limited against OL/2024/0087 Rs. 8,16,000.00
15/04/2025 Fuel purchase debit 2,10,000.00
"""

PLAINT = """IN THE HIGH COURT OF BOMBAY
COMMERCIAL SUIT NO. 301 OF 2025
Orbit Logistics LLP versus Pinnacle Foods Private Limited
PLAINT

1. The Plaintiff is a transporter. The Defendant is a food manufacturer.
2. Under the contract dated 02/05/2023 the Plaintiff transported goods for the Defendant at Rs. 42 per km per truck.
3. The Plaintiff raised invoice OL/2024/0087 dated 28/02/2025 for Rs. 9,36,000, due on 14/04/2025.
4. The Defendant paid Rs. 8,16,000 on 02/04/2025 and has not paid the balance of Rs. 1,20,000.
5. The Plaintiff claims Rs. 1,20,000 with interest at 18% per annum from 14/04/2025.

The Plaintiff prays for a decree for Rs. 1,20,000 with interest and costs.
Dated 15/07/2025
"""

WS = """IN THE HIGH COURT OF BOMBAY
COMMERCIAL SUIT NO. 301 OF 2025
Orbit Logistics LLP versus Pinnacle Foods Private Limited
WRITTEN STATEMENT OF THE DEFENDANT

1. The Defendant admits that invoice OL/2024/0087 was raised and that it paid Rs. 8,16,000 on 02/04/2025.
2. The Defendant denies owing Rs. 1,20,000 because goods on two trips were damaged in transit and the Plaintiff is liable for the loss.
3. The Defendant denies that any interest is payable.
Dated 20/09/2025
"""

ORDER = """IN THE HIGH COURT OF BOMBAY
COMMERCIAL SUIT NO. 301 OF 2025
ORDER
Date: 03/10/2025
The written statement is taken on record. The Defendant shall file an affidavit of documents within two weeks from today. The suit is adjourned to 12/12/2025 for framing of issues.
"""

DOCS = [
    Doc(
        "01_Logistics_Services_Contract.pdf",
        1,
        "CONTRACT",
        "Logistics Services Contract",
        "02/05/2023",
        CONTRACT,
        signed=True,
        suit_roles=False,
        no_fixture=True,
    ),
    Doc(
        "02_Invoice_OL_2024_0087.pdf",
        1,
        "INVOICE",
        "Invoice OL/2024/0087",
        "28/02/2025",
        INVOICE,
        suit_roles=False,
        author="orbit",
        no_fixture=True,
    ),
    Doc(
        "03_Email_dispute.pdf",
        1,
        "EMAIL",
        "Invoice OL/2024/0087 (e-mail)",
        "10/03/2025",
        EMAIL,
        suit_roles=False,
        no_fixture=True,
    ),
    Doc(
        "04_Legal_Notice.pdf",
        1,
        "LEGAL_NOTICE",
        "Legal Notice",
        "20/05/2025",
        NOTICE,
        author="orbit",
        suit_roles=False,
        no_fixture=True,
    ),
    Doc(
        "05_Bank_statement_April_2025.pdf",
        2,
        "BANK_STATEMENT",
        "Statement of Account April 2025",
        "30/04/2025",
        BANK,
        suit_roles=False,
        no_fixture=True,
    ),
    Doc("06_Plaint.pdf", 2, "PLAINT", "Plaint", "15/07/2025", PLAINT, author="orbit", no_fixture=True),
    Doc(
        "07_Written_Statement.pdf",
        2,
        "WRITTEN_STATEMENT",
        "Written Statement",
        "20/09/2025",
        WS,
        author="pinnacle",
        no_fixture=True,
    ),
    Doc(
        "08_Order_03_Oct_2025.pdf", 2, "ORDER", "Order dated 03/10/2025", "03/10/2025", ORDER, no_fixture=True
    ),
]

QUESTIONS = [
    Question(
        "M4-B1-Q01",
        1,
        "What is the transport rate under the contract?",
        [],
        ["42"],
        [{"document": "Logistics Services Contract", "page": 1}],
    ),
    Question(
        "M4-B1-Q02",
        1,
        "When is invoice OL/2024/0087 due?",
        [],
        ["14 Apr 2025"],
        [{"document": "Invoice", "page": 1}],
    ),
    Question("M4-B1-Q03", 1, "How much does Pinnacle dispute and why?", [], ["1,20,000"]),
    Question("M4-B1-Q04", 1, "Who represents Pinnacle?", [], [], not_found=True),
    Question(
        "M4-B2-Q05",
        2,
        "How much is still unpaid on invoice OL/2024/0087?",
        [],
        ["1,20,000"],
        must_not_say=["Outstanding on OL/2024/0087: ₹9,36,000"],
    ),
    Question("M4-B2-Q06", 2, "What changed since the last batch?", [], ["8,16,000"], intent="WHAT_CHANGED"),
    Question(
        "M4-B2-Q07", 2, "What has the court directed and by when?", [], ["17 Oct 2025"], intent="DIRECTIONS"
    ),
    Question("M4-B2-Q08", 2, "What is the next hearing date?", [], ["12 Dec 2025"]),
]

PROBES = [
    Probe("rate per km per truck", "Logistics Services Contract"),
    Probe("interest on delayed payment", "Logistics Services Contract"),
    Probe("damaged goods on two trips", "Written Statement"),
    Probe("affidavit of documents within two weeks", "Order dated 03/10/2025"),
]

MATTER = Matter(
    id="M4",
    number="COMM SUIT 301/2025",
    title="Orbit Logistics LLP v Pinnacle Foods Private Limited",
    matter_type="PAYMENT_RECOVERY",
    forum="High Court of Bombay",
    parties=[
        Party("orbit", "Orbit Logistics LLP", "PLAINTIFF", ["Orbit"]),
        Party("pinnacle", "Pinnacle Foods Private Limited", "DEFENDANT", ["Pinnacle"]),
    ],
    docs=DOCS,
    questions=QUESTIONS,
    planted=[Planted(2, "NARROWED", "R5", "invoice/ol-2024-0087/amount_outstanding")],
    probes=PROBES,
    description="Held-out style: a part-paid transport invoice written in different drafting conventions. Requires a real model.",
)
