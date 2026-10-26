import pytest
from onboarding import annual_fixtures as fixture
from onboarding.annual_demo import setup
from onboarding.financial_demo import financial_send
from onboarding.reporting import freeze, oracle_snapshot, approve_policy
from onboarding.engine import Refused


def test_annual_sources_are_deterministic_and_independent_document_grains():
    rows = fixture.records()
    assert rows == fixture.records() and len(rows) == 333
    assert len(fixture.PERIODS) == 12 and sum(fixture.WEIGHTS) == 100
    assert len({(r["company"], r["event_id"]) for r in rows}) == len(rows)
    controls = fixture.source_controls(rows)
    for company, profile in fixture.PROFILES.items():
        assert 500000000 <= profile <= 2000000000
        extra = 16000000 if company == "cedar" else 0
        assert controls[company]["gross_invoice_minor"] == profile + extra
        assert controls[company]["net_invoice_minor"] != controls[company]["bookings_minor"]
        assert controls[company]["payments_minor"] == controls[company]["allocated_cash_minor"]
        assert {r["transaction_date"][:7] for r in rows if r["company"] == company} == {
            p[:7] for p in fixture.PERIODS
        }


def test_annual_admission_exclusions_and_source_controls(stack):
    rows = setup(stack)
    freeze(stack.reviewer_dsn, "original", 1, fixture.ORIGINAL_CUTOFF)
    result = oracle_snapshot(stack, "original")
    included = [
        r
        for r in rows
        if r["company"] == "cedar"
        or (r["company"] == "meridian" and r["transaction_date"] >= "2026-02-01")
    ]

    def sums(kind):
        return sum(r["amount_minor"] for r in included if r["kind"] == kind)

    def total(key):
        return sum(r[key] for r in result["portfolio_totals"])

    assert total("bookings_minor") == sums("booking")
    assert total("consolidated_invoice_minor") == sums("invoice") - sums("credit") - 12000000
    assert total("consolidated_erp_minor") == sums("erp_posting") - 12000000
    assert total("allocated_cash_minor") == sums("allocation")
    assert len(result["portfolio_totals"]) == 12
    assert not any(r["company"] == "summit" for r in result["fct_invoices"])
    assert {(r["code"], r["amount_minor"]) for r in result["reconciliation_variances"]} == {
        ("erp_posting_difference", 2500000),
        ("intercompany_unresolved", 4000000),
    }


def test_annual_duplicate_conflict_and_cross_company_identity(stack):
    rows = setup(stack)
    event = rows[1]
    assert financial_send(stack, event)["duplicate"]
    with stack.client(company="cedar", source="quickbooks") as c:
        assert (
            c.post(
                "/v1/financial", json={**event, "amount_minor": event["amount_minor"] + 1}
            ).status_code
            == 409
        )
    with stack.client(company="meridian", source="netsuite") as c:
        assert c.post("/v1/financial", json=event).status_code == 403


def test_annual_inventory_cannot_silently_drop_a_source(stack):
    rows = setup(stack)
    policy = fixture.policy(rows)
    policy["inventory"]["cedar"]["invoice"].pop()
    approve_policy(stack.reviewer_dsn, 2, policy)
    with pytest.raises(Refused, match="financial_inventory_incomplete_or_unreviewed"):
        freeze(stack.reviewer_dsn, "incomplete", 2, fixture.ORIGINAL_CUTOFF)


def test_annual_late_correction_preserves_earlier_source_cutoff(stack):
    rows = setup(stack)
    freeze(stack.reviewer_dsn, "original", 1, fixture.ORIGINAL_CUTOFF)
    before = oracle_snapshot(stack, "original")
    for row in fixture.corrections(rows):
        assert financial_send(stack, row)["status"] == "accepted"
    freeze(stack.reviewer_dsn, "replay", 1, fixture.ORIGINAL_CUTOFF)
    assert oracle_snapshot(stack, "replay") == before
    assert [
        r for r in fixture.records() if not (r["company"] == "summit" and r["kind"] == "booking")
    ] == rows


def test_correctness_fixture_stays_distinct():
    from onboarding.financial_fixtures import records, PERIODS

    assert PERIODS == ["2026-01-01", "2026-02-01", "2026-10-01"]
    assert not set(r["event_id"] for r in records()) & set(r["event_id"] for r in fixture.records())
