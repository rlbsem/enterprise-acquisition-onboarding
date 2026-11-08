"""Independent source-database arithmetic/membership; no application reconciliation imports."""

from collections import defaultdict
import hashlib
import json
from datetime import date, datetime
from uuid import NAMESPACE_URL, uuid5
from .db import connect


def calculate(source_documents, cutoff, specs, admitted, periods):
    latest = {}
    for document in source_documents:
        b = document["body"]
        if datetime.fromisoformat(b["observed_at"]) > datetime.fromisoformat(cutoff):
            continue
        key = (b["company"], b["kind"], b["source_id"])
        if key not in latest or b["revision"] > latest[key]["revision"]:
            latest[key] = b
    registry = {c: (entity, acquired) for c, _, entity, acquired, _ in specs}
    eligible = {}
    for key, b in latest.items():
        entity, acquired = registry[b["company"]]
        assert b["legal_entity"] == entity and b["currency"] == "USD"
        eligible[key] = (
            admitted[b["company"]]
            and b["transaction_date"] >= acquired
            and b["transaction_date"][:7] + "-01" in periods
        )
    base = eligible.copy()
    for key, b in latest.items():
        issuer = (
            b["counterparty_company"] if b["kind"] == "intercompany_acceptance" else b["company"]
        )
        if b["invoice_id"]:
            eligible[key] &= base.get((issuer, "invoice", b["invoice_id"]), False)
        if b["payment_id"]:
            eligible[key] &= base.get((b["company"], "payment", b["payment_id"]), False)
    included = {k: b for k, b in latest.items() if eligible[k]}
    measures = [
        "bookings_minor",
        "gross_invoice_minor",
        "credits_minor",
        "net_invoice_minor",
        "erp_posted_minor",
        "allocated_cash_minor",
        "elimination_minor",
        "consolidated_invoice_minor",
        "consolidated_erp_minor",
    ]
    legal = {
        (company, period): dict(
            company=company,
            legal_entity=entity,
            period=period,
            currency="USD",
            **{m: 0 for m in measures},
        )
        for company, _, entity, _, _ in specs
        for period in periods
    }
    invoices, allocations, eliminations, variances = [], [], [], []
    for key, invoice in included.items():
        company, kind, identifier = key
        period = invoice["transaction_date"][:7] + "-01"
        target = legal[(company, period)]
        if kind == "booking":
            target["bookings_minor"] += invoice["amount_minor"]
        if kind != "invoice":
            continue
        children = [
            b
            for b in included.values()
            if b["company"] == company
            and b["invoice_id"] == identifier
            and b["kind"] in ["invoice_line", "credit", "erp_posting"]
        ]
        lines = sum(b["amount_minor"] for b in children if b["kind"] == "invoice_line")
        credits = sum(b["amount_minor"] for b in children if b["kind"] == "credit")
        erp = sum(b["amount_minor"] for b in children if b["kind"] == "erp_posting")
        net = invoice["amount_minor"] - credits
        row = dict(
            company=company,
            legal_entity=invoice["legal_entity"],
            invoice_id=identifier,
            period=period,
            currency="USD",
            gross_minor=invoice["amount_minor"],
            lines_minor=lines,
            credits_minor=credits,
            net_minor=net,
            erp_minor=erp,
            erp_count=sum(b["kind"] == "erp_posting" for b in children),
        )
        invoices.append((row, [invoice, *children]))
        assert lines == invoice["amount_minor"], "independent_invoice_line_difference"
        for metric, value in [
            ("gross_invoice_minor", invoice["amount_minor"]),
            ("credits_minor", credits),
            ("net_invoice_minor", net),
        ]:
            target[metric] += value
        # Posting cashflows retain their own document dates, not header dates.
        for b in children:
            if b["kind"] == "erp_posting":
                legal[(company, b["transaction_date"][:7] + "-01")]["erp_posted_minor"] += b[
                    "amount_minor"
                ]
        if erp != net or row["erp_count"] == 0:
            variances.append(
                (
                    company,
                    identifier,
                    "erp_posting_difference" if row["erp_count"] else "erp_posting_missing",
                    net - erp,
                )
            )
        if invoice["counterparty_company"]:
            other = invoice["counterparty_company"]
            charges = [
                b
                for b in included.values()
                if b["company"] == company
                and b["kind"] == "intercompany_charge"
                and b["invoice_id"] == identifier
                and b["counterparty_company"] == other
                and b["counterparty_entity"] == invoice["counterparty_entity"]
            ]
            acceptances = [
                b
                for b in included.values()
                if b["company"] == other
                and b["kind"] == "intercompany_acceptance"
                and b["invoice_id"] == identifier
                and b["counterparty_company"] == company
                and b["counterparty_entity"] == invoice["legal_entity"]
                and any(b["link_id"] == c["link_id"] for c in charges)
            ]
            cash = [
                b
                for b in included.values()
                if b["company"] == company
                and b["kind"] == "allocation"
                and b["invoice_id"] == identifier
            ]
            matched = (
                len(charges) == len(acceptances) == 1
                and all(
                    b["amount_minor"] == net and b["currency"] == invoice["currency"]
                    for b in charges + acceptances
                )
                and erp == net
                and not cash
            )
            elimination = net if matched else 0
            target["elimination_minor"] += elimination
            eliminations.append((company, identifier, elimination, charges, acceptances))
            if not matched:
                variances.append((company, identifier, "intercompany_unresolved", net))
    for key, b in included.items():
        company, kind, _ = key
        if kind == "allocation":
            invoice = included[(company, "invoice", b["invoice_id"])]
            payment = included[(company, "payment", b["payment_id"])]
            allocations.append((b, payment, invoice))
            legal[(company, b["transaction_date"][:7] + "-01")]["allocated_cash_minor"] += b[
                "amount_minor"
            ]
        if kind == "payment":
            cash = sum(
                v["amount_minor"]
                for v in included.values()
                if v["company"] == company
                and v["kind"] == "allocation"
                and v["payment_id"] == b["source_id"]
            )
            assert cash <= b["amount_minor"], "independent_payment_overallocation"
            if cash != b["amount_minor"]:
                variances.append(
                    (company, b["source_id"], "unallocated_payment", b["amount_minor"] - cash)
                )
    for row in legal.values():
        row["consolidated_invoice_minor"] = row["net_invoice_minor"] - row["elimination_minor"]
        row["consolidated_erp_minor"] = row["erp_posted_minor"] - row["elimination_minor"]
    totals = [
        dict(
            period=p,
            currency="USD",
            **{m: sum(r[m] for (c, day), r in legal.items() if day == p) for m in measures},
        )
        for p in periods
    ]
    return dict(
        latest=latest,
        eligible=eligible,
        invoices=invoices,
        allocations=allocations,
        eliminations=eliminations,
        variances=variances,
        legal=list(legal.values()),
        totals=totals,
    )


def identity(stack, portfolio):
    with connect(stack.console["read_dsn"]) as c:
        customers = c.execute("SELECT company,id FROM customers").fetchall()
        records = c.execute(
            "SELECT company,source,source_id,canonical FROM source_records"
        ).fetchall()
    assert len(customers) == sum(portfolio.customer_count(i) for i in range(portfolio.count))
    assert len({str(r["id"]) for r in customers}) == len(customers)
    for row in customers:
        expected = {
            str(uuid5(NAMESPACE_URL, f"synthetic-admission:{row['company']}:{j + 1}"))
            for j in range(
                portfolio.customer_count(
                    next(i for i, c in enumerate(portfolio.companies) if c[0] == row["company"])
                )
            )
        }
        assert str(row["id"]) in expected
    for row in records:
        number = int(row["source_id"]) - 99
        assert str(row["canonical"]) == str(
            uuid5(NAMESPACE_URL, f"synthetic-admission:{row['company']}:{number}")
        )
    counts = defaultdict(set)
    for row in records:
        counts[row["source_id"]].add(row["company"])
    assert len(counts["100"]) == portfolio.count
    return dict(
        canonical_accounts=len(customers),
        source_projections=len(records),
        companies_reusing_local_100=len(counts["100"]),
        cross_company_collisions=0,
    )


def verify(stack, sources, portfolio, publication, cutoff, recovered=False):
    admitted = {
        c[0]: portfolio.expected_admitted(i, recovered) for i, c in enumerate(portfolio.companies)
    }
    documents = sources.financial()
    for document in documents:
        assert (
            hashlib.sha256(
                json.dumps(
                    document["body"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
            == document["hash"]
        ), "independent_source_hash_difference"
    expected = calculate(
        documents, cutoff, portfolio.companies, admitted, ["2026-01-01", "2026-10-01"]
    )
    with connect(stack.reviewer_dsn) as c:
        c.execute("SET TRANSACTION READ ONLY")
        rows = c.execute(
            "SELECT id,body,hash FROM financial_events WHERE status='accepted' AND (body->>'observed_at')::timestamptz<=%s",
            (cutoff,),
        ).fetchall()
        snapshot = c.execute(
            "SELECT control FROM financial_snapshots WHERE id=%s", (publication["report_id"],)
        ).fetchone()["control"]
    latest = {}
    for row in rows:
        b = row["body"]
        key = (b["company"], b["kind"], b["source_id"])
        if key not in latest or latest[key]["body"]["revision"] < b["revision"]:
            latest[key] = row
    assert {k: r["body"] for k, r in latest.items()} == expected["latest"], (
        "source_to_control_membership_difference"
    )
    assert {c: v["admitted"] for c, v in snapshot.items()} == admitted

    def ids(bodies):
        return sorted(latest[(b["company"], b["kind"], b["source_id"])]["id"] for b in bodies)

    actual = publication["results"]

    def normalize(rows):
        return sorted(
            [{k: str(v) if isinstance(v, date) else v for k, v in r.items()} for r in rows],
            key=lambda r: str(sorted(r.items())),
        )

    invoices = [{**row, "source_event_ids": ids(bodies)} for row, bodies in expected["invoices"]]
    assert normalize(invoices) == normalize(actual["fct_invoices"]), (
        "independent_invoice_content_or_lineage_difference"
    )
    assert normalize(expected["legal"]) == normalize(actual["legal_entity_totals"]), (
        "independent_company_amount_difference"
    )
    assert normalize(expected["totals"]) == normalize(actual["portfolio_totals"]), (
        "independent_portfolio_amount_difference"
    )
    for row in actual["fct_allocations"]:
        expected_allocation = next(
            v
            for v in expected["allocations"]
            if (v[0]["company"], v[0]["source_id"]) == (row["company"], row["allocation_id"])
        )
        a, p, i = expected_allocation
        assert all(
            row[field] == a[field]
            for field in [
                "company",
                "legal_entity",
                "currency",
                "invoice_id",
                "payment_id",
                "amount_minor",
            ]
        )
        assert str(row["period"]) == a["transaction_date"][:7] + "-01"
        assert (
            row["amount_minor"] == a["amount_minor"]
            and row["invoice_id"] == i["source_id"]
            and row["payment_id"] == p["source_id"]
        )
        assert row["source_event_ids"] == [ids([x])[0] for x in [a, p, i]]
    assert len(actual["fct_allocations"]) == len(expected["allocations"])
    assert {
        (r["company"], r["invoice_id"], r["elimination_minor"])
        for r in actual["intercompany_eliminations"]
    } == {(c, i, amount) for c, i, amount, _, _ in expected["eliminations"]}
    for row in actual["intercompany_eliminations"]:
        _, _, _, charges, acceptances = next(
            item
            for item in expected["eliminations"]
            if item[:2] == (row["company"], row["invoice_id"])
        )
        assert sorted(row["charge_event_ids"] or []) == ids(charges)
        assert sorted(row["acceptance_event_ids"] or []) == ids(acceptances)
        assert row["charge_count"] == len(charges) and row["acceptance_count"] == len(acceptances)
    assert {
        (r["company"], r["source_id"], r["code"], r["amount_minor"])
        for r in actual["reconciliation_variances"]
    } == set(expected["variances"])
    with connect(stack.warehouse_dsn) as c:
        included_ids = {
            r["event_id"]
            for r in c.execute("SELECT event_id FROM analytics.stg_financial WHERE eligible")
        }
    assert included_ids == {
        latest[k]["id"] for k, eligible in expected["eligible"].items() if eligible
    }, "independent_source_inclusion_difference"
    return dict(
        status="passed",
        compared_source_members=len(latest),
        included_source_members=len(included_ids),
        invoice_grains=len(invoices),
        allocation_grains=len(expected["allocations"]),
        company_periods=len(expected["legal"]),
        unresolved_variances=len(expected["variances"]),
        supported_eliminations=sum(amount > 0 for _, _, amount, _, _ in expected["eliminations"]),
        totals=expected["totals"],
        incorrect_amounts=0,
        incorrect_source_memberships=0,
    )
