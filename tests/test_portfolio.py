"""New workload properties and adversarial checks against a real ten-company execution."""

import copy
import pytest
from onboarding.portfolio_fixtures import Portfolio, ORIGINAL, RESTATED, PERIODS
from onboarding.portfolio_oracle import calculate, verify
from onboarding.portfolio_demo import execute
from onboarding.portfolio_sources import Sources
from onboarding.sandbox import Sandbox


@pytest.mark.parametrize("count", [3, 10, 25, 50])
def test_deterministic_company_scoped_workload(count):
    a, b = Portfolio(count), Portfolio(count)
    assert a.financial() == b.financial() and a.companies == b.companies
    assert len({c[2] for c in a.companies}) == count
    assert len({c[4] for c in a.companies}) == 3
    assert {
        m["data"][a.contract(i)["sources"][m["source"]]["id"]]
        for i in range(count)
        for m in a.messages(i)
    } >= {"100", "101"}
    rows = a.financial()
    assert len({(r["company"], r["kind"], r["source_id"]) for r in rows}) == len(rows)
    assert len({r["event_id"] for r in rows}) < len(rows)
    assert all(r["currency"] == "USD" and type(r["amount_minor"]) is int for r in rows)


@pytest.mark.parametrize("count", [0, 2, 101, True])
def test_configuration_is_bounded(count):
    with pytest.raises(ValueError):
        Portfolio(count)


def test_oracle_has_independently_calculated_selected_invoice_arithmetic():
    p = Portfolio(3)
    result = calculate(
        [{"body": r} for r in p.financial()],
        ORIGINAL,
        p.companies,
        {c[0]: i == 2 for i, c in enumerate(p.companies)},
        PERIODS,
    )
    amounts = [3_000_000 + 2 * 91_000 + j * 37_000 + 10 * 11_000 for j in range(4)]
    net = sum(g - g // 52 for g in amounts)
    october = next(r for r in result["totals"] if r["period"] == "2026-10-01")
    assert october["net_invoice_minor"] == net
    assert october["erp_posted_minor"] == net - 4 * 12_500
    assert october["allocated_cash_minor"] == sum((g - g // 52) * 57 // 100 for g in amounts)
    assert (
        next(r for r in result["totals"] if r["period"] == "2026-01-01")["net_invoice_minor"] == 0
    )


@pytest.fixture(scope="module")
def executed_portfolio(tmp_path_factory):
    work = tmp_path_factory.mktemp("multi-company")
    spec = Portfolio(10)
    with Sandbox(work / "runtime", scenario=spec) as stack:
        with Sources(stack, spec) as sources:
            result = execute(stack, sources, spec, work / "builds", keep_sources=True)
            yield stack, sources, spec, result


def test_real_multi_company_execution_and_recovery(executed_portfolio):
    _, _, _, result = executed_portfolio
    assert result["contention_probe"]["healthy_admission_completed_while_other_lock_held"]
    assert result["delivery"]["exhausted_queues"] == 1
    assert result["delivery"]["healthy_confirmed"] >= 1
    assert result["source_service_down_during_healthy_progress"]
    assert result["restated_oracle"]["supported_eliminations"] > 0
    assert (
        result["original_publication_unchanged"] and result["original_input_membership_unchanged"]
    )


@pytest.mark.parametrize("damage", ["amount", "lineage", "unproved_elimination", "held_company"])
def test_independent_observer_rejects_plausible_but_wrong_reports(executed_portfolio, damage):
    stack, sources, spec, result = executed_portfolio
    candidate = copy.deepcopy(result["restated"])
    if damage == "amount":
        candidate["results"]["portfolio_totals"][0]["bookings_minor"] += 1
    elif damage == "lineage":
        candidate["results"]["fct_invoices"][0]["source_event_ids"][0] = -1
    elif damage == "unproved_elimination":
        row = next(
            r
            for r in candidate["results"]["intercompany_eliminations"]
            if r["elimination_minor"] == 0
        )
        row["elimination_minor"] = row["net_minor"]
    else:
        row = copy.deepcopy(candidate["results"]["fct_invoices"][0])
        row["company"] = spec.companies[1][0]
        candidate["results"]["fct_invoices"].append(row)
    with pytest.raises(AssertionError):
        verify(stack, sources, spec, candidate, RESTATED, recovered=True)
