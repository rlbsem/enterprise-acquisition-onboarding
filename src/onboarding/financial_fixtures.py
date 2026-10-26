"""Finite USD source economics; observation cutoffs are synthetic knowledge dates."""

import copy
from .fixtures import COMPANIES, mapping
from .finance import Financial

PERIODS = ["2026-01-01", "2026-02-01", "2026-10-01"]
ORIGINAL_CUTOFF = "2026-10-20T00:00:00+00:00"
REVISED_CUTOFF = "2026-10-23T00:00:00+00:00"


def records():
    rows = []

    def add(company, kind, key, amount, day, **refs):
        entity, style = next((x[2], x[4]) for x in COMPANIES if x[0] == company)
        domain = "crm" if kind == "booking" else "finance"
        source = next(s for s, r in mapping(style)["sources"].items() if r["domain"] == domain)
        b = dict(
            company=company,
            legal_entity=entity,
            source=source,
            owner=domain,
            event_id=kind + ":" + key + ":1",
            kind=kind,
            source_id=key,
            revision=1,
            mapping_version=1,
            currency="USD",
            amount_minor=amount,
            transaction_date=day,
            observed_at="2026-10-10T12:00:00+00:00",
            **refs,
        )
        if day.startswith("2026-10"):
            b["observed_at"] = "2026-10-15T12:00:00+00:00"
        rows.append(Financial.model_validate(b).model_dump())

    add("cedar", "booking", "B1", 25000000, "2026-01-03")
    add("cedar", "invoice", "I1", 12000000, "2026-01-10", booking_id="B1")
    add("cedar", "invoice_line", "I1-L1", 8000000, "2026-01-10", invoice_id="I1")
    add("cedar", "invoice_line", "I1-L2", 4000000, "2026-01-10", invoice_id="I1")
    add("cedar", "credit", "CR1", 1000000, "2026-01-12", invoice_id="I1")
    add("cedar", "erp_posting", "P1", 12000000, "2026-01-10", invoice_id="I1")
    add("cedar", "erp_posting", "PCR1", -1000000, "2026-01-12", invoice_id="I1")
    add("cedar", "invoice", "I2", 5000000, "2026-01-15")
    add("cedar", "invoice_line", "I2-L1", 5000000, "2026-01-15", invoice_id="I2")
    add("cedar", "erp_posting", "P2", 4500000, "2026-01-15", invoice_id="I2")
    add("cedar", "payment", "PAY1", 8000000, "2026-01-20")
    add("cedar", "allocation", "A1", 7000000, "2026-01-20", invoice_id="I1", payment_id="PAY1")
    add("cedar", "allocation", "A2", 1000000, "2026-01-20", invoice_id="I2", payment_id="PAY1")
    # Meridian's January invoice is outside its acquisition-effective perimeter.
    add("meridian", "invoice", "I1", 9000000, "2026-01-10")
    add("meridian", "invoice_line", "I1-L1", 9000000, "2026-01-10", invoice_id="I1")
    add("meridian", "erp_posting", "P1", 9000000, "2026-01-10", invoice_id="I1")
    add("meridian", "booking", "B1", 30000000, "2026-02-02")
    add("meridian", "invoice", "I2", 20000000, "2026-02-10", booking_id="B1")
    add("meridian", "invoice_line", "I2-L1", 12000000, "2026-02-10", invoice_id="I2")
    add("meridian", "invoice_line", "I2-L2", 8000000, "2026-02-10", invoice_id="I2")
    add("meridian", "erp_posting", "P2", 20000000, "2026-02-10", invoice_id="I2")
    add("meridian", "payment", "PAY1", 15000000, "2026-02-20")
    add("meridian", "allocation", "A1", 15000000, "2026-02-20", invoice_id="I2", payment_id="PAY1")
    for key, amount in [("IC1", 2000000), ("IC2", 800000)]:
        refs = dict(counterparty_company="meridian", counterparty_entity="LE-US-02")
        add("cedar", "invoice", key, amount, "2026-02-12", **refs)
        add("cedar", "invoice_line", key + "-L1", amount, "2026-02-12", invoice_id=key)
        add("cedar", "erp_posting", "P-" + key, amount, "2026-02-12", invoice_id=key)
        add(
            "cedar",
            "intercompany_charge",
            "CH-" + key,
            amount,
            "2026-02-12",
            invoice_id=key,
            link_id="shared-service:" + key,
            **refs,
        )
    add(
        "meridian",
        "intercompany_acceptance",
        "AC1",
        2000000,
        "2026-02-12",
        invoice_id="IC1",
        link_id="shared-service:IC1",
        counterparty_company="cedar",
        counterparty_entity="LE-CA-01",
    )
    add("summit", "invoice", "I1", 10000000, "2026-10-10")
    add("summit", "invoice_line", "I1-L1", 10000000, "2026-10-10", invoice_id="I1")
    add("summit", "erp_posting", "P1", 10000000, "2026-10-10", invoice_id="I1")
    return rows


def corrections(original):
    result = []
    for key, amount in [("I1", 14000000), ("I1-L1", 10000000), ("P1", 14000000)]:
        b = copy.deepcopy(
            next(r for r in original if r["company"] == "cedar" and r["source_id"] == key)
        )
        b.update(
            revision=2,
            event_id=b["kind"] + ":" + key + ":2",
            amount_minor=amount,
            observed_at="2026-10-22T12:00:00+00:00",
        )
        result.append(b)
    return result


def policy(original):
    inventory = {c: {} for c, *_ in COMPANIES}
    for row in original:
        inventory[row["company"]].setdefault(row["kind"], []).append(row["source_id"])
    return {
        "schema_version": "portfolio-financial-policy.v1",
        "currency": "USD",
        "periods": PERIODS,
        "perimeter": {
            c: {"legal_entity": entity, "acquired_on": day, "reporting_unit": c}
            for c, _, entity, day, _ in COMPANIES
        },
        "inventory": inventory,
        "elimination": "one_exact_charge_and_independent_counterparty_acceptance.v1",
        "basis": "document_and_allocation_dates; no_preacquisition_carryforward; no_recognized_revenue",
        "actor": "synthetic-finance-reviewer",
        "reason": "Reviewed finite reporting perimeter, USD minor units, source IDs and linked elimination rule.",
    }
