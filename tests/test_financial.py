import copy
import psycopg
import pytest
from onboarding.db import connect
from onboarding.engine import Refused
from onboarding.financial_demo import setup, financial_send
from onboarding.financial_fixtures import policy, ORIGINAL_CUTOFF
from onboarding.reporting import freeze, oracle_snapshot, compare, warehouse, approve_policy


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"legal_entity": "LE-US-02"}, "financial_entity_mismatch"),
        ({"currency": "CAD"}, "financial_currency_policy_mismatch"),
        ({"source": "hubspot", "owner": "crm"}, "financial_source_authority_denied"),
        ({"mapping_version": 2}, "financial_mapping_stale"),
    ],
)
def test_source_owned_financial_rejections(stack, change, reason):
    original = setup(stack)
    b = {**original[1], **change, "event_id": "invalid-financial"}
    r = financial_send(stack, b)
    assert r["status"] == "rejected" and r["reason"] == reason
    freeze(stack.reviewer_dsn, "unchanged", 1, ORIGINAL_CUTOFF)
    result = oracle_snapshot(stack, "unchanged")
    assert sum(r["consolidated_invoice_minor"] for r in result["portfolio_totals"]) == 36800000


def test_duplicate_content_identity_and_exact_money(stack):
    original = setup(stack)
    assert financial_send(stack, original[1])["duplicate"]
    with stack.client(company="cedar", source="quickbooks") as c:
        assert c.post("/v1/financial", json={**original[1], "amount_minor": 1}).status_code == 409
        assert (
            c.post(
                "/v1/financial", json={**original[1], "event_id": "float", "amount_minor": 1.5}
            ).status_code
            == 422
        )
    with stack.client(company="meridian", source="netsuite") as c:
        assert c.post("/v1/financial", json=original[1]).status_code == 403
    with connect(stack.dsn) as c:
        assert (
            c.execute(
                "SELECT count(*) n FROM financial_events WHERE company='cedar' AND body->>'kind'='invoice' AND body->>'source_id'='I1'"
            ).fetchone()["n"]
            == 1
        )


def test_financial_coverage_unknown_is_not_zero(stack):
    setup(stack)
    with connect(stack.reviewer_dsn) as c:
        original = c.execute("SELECT body FROM financial_policies WHERE version=1").fetchone()[
            "body"
        ]
    original["inventory"]["cedar"]["invoice"].append("not-delivered")
    approve_policy(stack.reviewer_dsn, 2, original)
    with pytest.raises(Refused, match="financial_inventory_incomplete"):
        freeze(stack.reviewer_dsn, "missing", 2, ORIGINAL_CUTOFF)
    with connect(stack.reviewer_dsn) as c:
        assert c.execute("SELECT count(*) n FROM financial_snapshots").fetchone()["n"] == 0


def test_independent_oracle_grains_periods_and_variances(stack):
    setup(stack)
    freeze(stack.reviewer_dsn, "report", 1, ORIGINAL_CUTOFF)
    r = oracle_snapshot(stack, "report")
    assert len(r["fct_invoices"]) == 5 and len(r["fct_allocations"]) == 3
    jan = next(x for x in r["portfolio_totals"] if x["period"] == "2026-01-01")
    assert jan["consolidated_invoice_minor"] == 16000000
    assert jan["allocated_cash_minor"] == 8000000
    assert not any(
        i["company"] == "summit" or (i["company"] == "meridian" and i["invoice_id"] == "I1")
        for i in r["fct_invoices"]
    )
    assert {(v["code"], v["amount_minor"]) for v in r["reconciliation_variances"]} == {
        ("erp_posting_difference", 500000),
        ("intercompany_unresolved", 800000),
    }
    changed = copy.deepcopy(r)
    changed["portfolio_totals"][0]["consolidated_invoice_minor"] += 1
    with pytest.raises(Refused, match="financial_oracle_mismatch"):
        compare(r, changed)


def test_ambiguous_intercompany_relationship_cannot_eliminate(stack):
    original = setup(stack)
    accept = next(b for b in original if b["kind"] == "intercompany_acceptance")
    duplicate = {**accept, "source_id": "AC2", "event_id": "accept-second"}
    assert financial_send(stack, duplicate)["status"] == "accepted"
    with pytest.raises(Refused, match="inventory"):
        freeze(stack.reviewer_dsn, "unreviewed-link", 1, ORIGINAL_CUTOFF)
    revised = policy(original + [duplicate])
    approve_policy(stack.reviewer_dsn, 2, revised)
    freeze(stack.reviewer_dsn, "ambiguous", 2, ORIGINAL_CUTOFF)
    row = next(
        r
        for r in oracle_snapshot(stack, "ambiguous")["intercompany_eliminations"]
        if r["invoice_id"] == "IC1"
    )
    assert row["acceptance_count"] == 2 and row["elimination_minor"] == 0


def test_immutable_snapshots_and_restricted_warehouse(stack):
    setup(stack)
    freeze(stack.reviewer_dsn, "frozen", 1, ORIGINAL_CUTOFF)
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with connect(stack.admin_dsn) as c:
            c.execute("UPDATE financial_snapshots SET input_hash='changed'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect(stack.dsn) as c:
            c.execute("INSERT INTO financial_publications VALUES('frozen','{}','{}','{}',now())")
    dsn = warehouse(stack)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect(dsn) as c:
            c.execute("SELECT * FROM financial_events")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect(dsn) as c:
            c.execute("UPDATE companies SET status='portfolio_ready'")


def test_new_source_revision_changes_candidate_not_frozen_inputs(stack):
    original = setup(stack)
    freeze(stack.reviewer_dsn, "asof", 1, ORIGINAL_CUTOFF)
    old = oracle_snapshot(stack, "asof")
    header = {
        **original[1],
        "event_id": "higher",
        "revision": 2,
        "amount_minor": 13000000,
        "observed_at": "2026-10-19T12:00:00+00:00",
    }
    assert financial_send(stack, header)["status"] == "accepted"
    assert oracle_snapshot(stack, "asof") == old
    late = {**header, "event_id": "stale", "revision": 1, "amount_minor": 1}
    assert financial_send(stack, late)["reason"] == "financial_revision_not_consecutive"
