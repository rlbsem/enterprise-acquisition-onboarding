"""Exact portable SQL executed on SQLite against the existing independent oracle.

These are relational-contract tests, not native Spark acceptance.
"""

import copy
import sqlite3
from pathlib import Path

import pytest

from onboarding.portfolio_fixtures import Portfolio, RESTATED, PERIODS
from onboarding.portfolio_oracle import calculate


@pytest.mark.parametrize("extra", [None, "intercompany_charge", "intercompany_acceptance"])
def test_bilateral_sql_matches_full_portfolio_and_rejects_unmatched_additional_evidence(extra):
    p = Portfolio(50)
    bodies = p.financial() + p.corrections()
    if extra:
        seed = next(
            b
            for b in bodies
            if b["kind"] == extra
            and (
                b["company"] == p.companies[2][0]
                if extra == "intercompany_charge"
                else b["company"] == p.companies[3][0]
            )
        )
        added = copy.deepcopy(seed)
        added.update(
            source_id="unmatched-extra",
            event_id="unmatched-extra-event",
            amount_minor=seed["amount_minor"] + 1,
        )
        bodies.append(added)
    oracle = calculate(
        [dict(body=b) for b in bodies],
        RESTATED,
        p.companies,
        {c[0]: p.expected_admitted(i, recovered=True) for i, c in enumerate(p.companies)},
        PERIODS,
    )
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    columns = [
        "company",
        "kind",
        "source_id",
        "invoice_id",
        "counterparty_company",
        "counterparty_entity",
        "link_id",
        "amount_minor",
        "currency",
    ]
    c.execute("CREATE TABLE eligible(" + ",".join(columns) + ")")
    c.executemany(
        "INSERT INTO eligible VALUES(" + ",".join("?" for _ in columns) + ")",
        [
            tuple(b.get(k) for k in columns)
            for key, b in oracle["latest"].items()
            if oracle["eligible"][key]
        ],
    )
    inv_columns = [
        "company",
        "legal_entity",
        "invoice_id",
        "period",
        "currency",
        "net_minor",
        "erp_minor",
        "counterparty_company",
        "counterparty_entity",
    ]
    c.execute("CREATE TABLE invoices(" + ",".join(inv_columns) + ")")
    for row, _ in oracle["invoices"]:
        source = oracle["latest"][(row["company"], "invoice", row["invoice_id"])]
        combined = row | {k: source[k] for k in ["counterparty_company", "counterparty_entity"]}
        c.execute(
            "INSERT INTO invoices VALUES(" + ",".join("?" for _ in inv_columns) + ")",
            tuple(combined[k] for k in inv_columns),
        )
    query = Path("src/onboarding/lakehouse_eliminations.sql").read_text().replace("{ns}.", "")
    actual = sorted(
        (r["company"], r["invoice_id"], r["elimination_minor"]) for r in c.execute(query)
    )
    expected = sorted(
        (company, key, amount) for company, key, amount, _, _ in oracle["eliminations"]
    )
    assert actual == expected
    if extra:
        assert (
            next(
                amount
                for company, key, amount in actual
                if company == p.companies[2][0] and key == "IC1"
            )
            == 0
        )
    c.close()
