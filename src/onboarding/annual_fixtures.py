"""Annual source scenario v1: three illustrative operating profiles, not recognized revenue."""

import copy
from .fixtures import COMPANIES, mapping
from .finance import Financial
from .financial_fixtures import policy as original_policy

PERIODS = [f"2026-{m:02}-01" for m in range(1, 13)]
WEIGHTS = [6, 6, 7, 8, 10, 12, 12, 11, 9, 8, 6, 5]
PROFILES = {"cedar": 840000000, "meridian": 1260000000, "summit": 630000000}
ORIGINAL_CUTOFF = "2027-01-10T00:00:00+00:00"
REVISED_CUTOFF = "2027-01-15T00:00:00+00:00"


def records():
    rows = []

    def add(company, kind, key, amount, month, **refs):
        entity, style = next((c[2], c[4]) for c in COMPANIES if c[0] == company)
        domain = "crm" if kind == "booking" else "finance"
        source = next(s for s, d in mapping(style)["sources"].items() if d["domain"] == domain)
        rows.append(
            Financial.model_validate(
                dict(
                    company=company,
                    legal_entity=entity,
                    source=source,
                    owner=domain,
                    event_id=f"annual:{kind}:{key}:1",
                    kind=kind,
                    source_id=key,
                    revision=1,
                    mapping_version=1,
                    currency="USD",
                    amount_minor=amount,
                    transaction_date=f"2026-{month:02}-20",
                    observed_at=f"2026-{month:02}-28T12:00:00+00:00",
                    **refs,
                )
            ).model_dump()
        )

    for index, (company, profile) in enumerate(PROFILES.items()):
        for month, weight in enumerate(WEIGHTS, 1):
            gross = profile * weight // 100
            credit = gross * (2 if month % 3 == 0 else 1) // 100
            invoice, booking, payment = [f"{p}-2026-{month:02}" for p in ["I", "B", "PAY"]]
            net = gross - credit
            cash = net * (72 + month % 4 * 4) // 100
            # One compressed monthly anchor-contract bundle per company; not a customer census.
            add(company, "booking", booking, gross * (109 + index * 3) // 100, month)
            # Summit's CRM identity is intentionally unresolved. Its finance
            # documents cannot claim a link to an unaccepted CRM booking.
            add(
                company,
                "invoice",
                invoice,
                gross,
                month,
                **({"booking_id": booking} if company != "summit" else {}),
            )
            add(company, "invoice_line", invoice + "-L1", gross * 3 // 5, month, invoice_id=invoice)
            add(
                company,
                "invoice_line",
                invoice + "-L2",
                gross - gross * 3 // 5,
                month,
                invoice_id=invoice,
            )
            add(company, "credit", "CR-" + invoice, credit, month, invoice_id=invoice)
            gap = 2500000 if company == "cedar" and month == 3 else 0
            add(company, "erp_posting", "P-" + invoice, gross - gap, month, invoice_id=invoice)
            add(company, "erp_posting", "PCR-" + invoice, -credit, month, invoice_id=invoice)
            add(company, "payment", payment, cash, month)
            add(
                company,
                "allocation",
                "A-" + invoice,
                cash,
                month,
                invoice_id=invoice,
                payment_id=payment,
            )
    for month, key, amount in [(4, "IC-SUPPORTED", 12000000), (6, "IC-OPEN", 4000000)]:
        refs = dict(counterparty_company="meridian", counterparty_entity="LE-US-02")
        add("cedar", "invoice", key, amount, month, **refs)
        add("cedar", "invoice_line", key + "-L1", amount, month, invoice_id=key)
        add("cedar", "erp_posting", "P-" + key, amount, month, invoice_id=key)
        add(
            "cedar",
            "intercompany_charge",
            "CH-" + key,
            amount,
            month,
            invoice_id=key,
            link_id=key,
            **refs,
        )
        if key == "IC-SUPPORTED":
            add(
                "meridian",
                "intercompany_acceptance",
                "AC-" + key,
                amount,
                month,
                invoice_id=key,
                link_id=key,
                counterparty_company="cedar",
                counterparty_entity="LE-CA-01",
            )
    return rows


def corrections(rows):
    result = []
    for key in ["I-2026-05", "I-2026-05-L1", "P-I-2026-05"]:
        row = copy.deepcopy(
            next(r for r in rows if r["company"] == "cedar" and r["source_id"] == key)
        )
        row.update(
            revision=2,
            event_id=row["event_id"].rsplit(":", 1)[0] + ":2",
            amount_minor=row["amount_minor"] + 4500000,
            observed_at="2027-01-12T12:00:00+00:00",
        )
        result.append(row)
    return result


def policy(rows):
    body = original_policy(rows)
    body["periods"] = PERIODS
    # Existing reporting policy validation, financial basis and perimeter remain unchanged.
    body["scenario"] = {
        "schema_version": "annual-operating-profile.v1",
        "id": "annual-2026",
        "profiles": PROFILES,
        "profile_basis": "assumed annual gross operating billing profile; not recognized revenue",
        "record_basis": "one compressed monthly anchor-contract bundle per company",
    }
    body["reason"] = (
        "Reviewed twelve-month synthetic source inventory; preserve held and acquisition-effective exclusions."
    )
    return body


def source_controls(rows):
    """Separate document-grain arithmetic; never reads dbt or dashboard aggregates."""
    result = {}
    for company, *_ in COMPANIES:
        own = [r for r in rows if r["company"] == company]

        def amount(kind):
            return sum(r["amount_minor"] for r in own if r["kind"] == kind)

        result[company] = dict(
            bookings_minor=amount("booking"),
            gross_invoice_minor=amount("invoice"),
            credits_minor=amount("credit"),
            net_invoice_minor=amount("invoice") - amount("credit"),
            erp_posted_minor=amount("erp_posting"),
            payments_minor=amount("payment"),
            allocated_cash_minor=amount("allocation"),
            source_records=len(own),
        )
    return result
