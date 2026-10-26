"""Independent integer arithmetic from frozen original source bodies, not dbt relations."""

METRICS = [
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


def calculate(inputs, control, policy, previous=None):
    all_rows = [{**r["body"], "id": r["event_id"]} for r in inputs]
    active = []
    for b in all_rows:
        d = control[b["company"]]
        if (
            d["admitted"]
            and b["transaction_date"] >= d["acquired_on"]
            and b["transaction_date"][:7] + "-01" in policy["periods"]
        ):
            active.append(b)

    def related(company, kind, invoice=None):
        return [
            r
            for r in active
            if r["company"] == company
            and r["kind"] == kind
            and (invoice is None or r["invoice_id"] == invoice)
        ]

    invoices = []
    headers = {}
    for h in active:
        if h["kind"] != "invoice":
            continue
        company, key = h["company"], h["source_id"]
        headers[company, key] = h
        children = [
            b
            for b in active
            if b["company"] == company
            and b["invoice_id"] == key
            and b["kind"] in ["invoice_line", "credit", "erp_posting"]
        ]
        sums = {
            k: sum(b["amount_minor"] for b in children if b["kind"] == k)
            for k in ["invoice_line", "credit", "erp_posting"]
        }
        invoices.append(
            dict(
                company=company,
                legal_entity=h["legal_entity"],
                invoice_id=key,
                period=h["transaction_date"][:7] + "-01",
                currency=h["currency"],
                gross_minor=h["amount_minor"],
                lines_minor=sums["invoice_line"],
                credits_minor=sums["credit"],
                net_minor=h["amount_minor"] - sums["credit"],
                erp_minor=sums["erp_posting"],
                erp_count=sum(b["kind"] == "erp_posting" for b in children),
                source_event_ids=sorted([h["id"], *(b["id"] for b in children)]),
            )
        )
    allocations = []
    for a in active:
        if a["kind"] != "allocation" or (a["company"], a["invoice_id"]) not in headers:
            continue
        payments = [
            p
            for p in active
            if p["company"] == a["company"]
            and p["kind"] == "payment"
            and p["source_id"] == a["payment_id"]
        ]
        if len(payments) != 1:
            continue
        allocations.append(
            dict(
                company=a["company"],
                legal_entity=a["legal_entity"],
                allocation_id=a["source_id"],
                invoice_id=a["invoice_id"],
                payment_id=a["payment_id"],
                period=a["transaction_date"][:7] + "-01",
                currency=a["currency"],
                amount_minor=a["amount_minor"],
                source_event_ids=[
                    a["id"],
                    payments[0]["id"],
                    headers[a["company"], a["invoice_id"]]["id"],
                ],
            )
        )
    eliminations = []
    for i in invoices:
        h = headers[i["company"], i["invoice_id"]]
        if not h["counterparty_company"]:
            continue
        charges = [
            c
            for c in related(h["company"], "intercompany_charge", h["source_id"])
            if c["counterparty_company"] == h["counterparty_company"]
            and c["counterparty_entity"] == h["counterparty_entity"]
        ]
        pairs = []
        for c in charges:
            for a in related(h["counterparty_company"], "intercompany_acceptance", h["source_id"]):
                if (
                    a["counterparty_company"] == h["company"]
                    and a["counterparty_entity"] == h["legal_entity"]
                    and a["link_id"] == c["link_id"]
                ):
                    pairs.append((c, a))
        accepts = {a["id"] for _, a in pairs}
        matches = bool(pairs) and all(
            c["amount_minor"] == a["amount_minor"] == i["net_minor"]
            and c["currency"] == a["currency"] == i["currency"]
            for c, a in pairs
        )
        paid = any(
            a["company"] == i["company"] and a["invoice_id"] == i["invoice_id"] for a in allocations
        )
        amount = (
            i["net_minor"]
            if len(charges) == len(accepts) == 1
            and matches
            and i["erp_minor"] == i["net_minor"]
            and not paid
            else 0
        )
        eliminations.append(
            {k: i[k] for k in ["company", "legal_entity", "invoice_id", "period", "net_minor"]}
            | dict(
                charge_count=len(charges),
                acceptance_count=len(accepts),
                content_matches=matches,
                charge_event_ids=sorted(c["id"] for c in charges) or None,
                acceptance_event_ids=sorted(accepts) or None,
                elimination_minor=amount,
            )
        )
    variances = []

    def variance(row, key, code, amount):
        variances.append(
            {k: row[k] for k in ["company", "legal_entity", "period"]}
            | dict(source_id=key, code=code, amount_minor=amount)
        )

    for i in invoices:
        if i["net_minor"] != i["erp_minor"] or not i["erp_count"]:
            variance(
                i,
                i["invoice_id"],
                "erp_posting_difference" if i["erp_count"] else "erp_posting_missing",
                i["net_minor"] - i["erp_minor"],
            )
        if i["gross_minor"] != i["lines_minor"]:
            variance(
                i, i["invoice_id"], "invoice_line_difference", i["gross_minor"] - i["lines_minor"]
            )
    for x in eliminations:
        if not x["elimination_minor"]:
            variance(x, x["invoice_id"], "intercompany_unresolved", x["net_minor"])
    for p in active:
        if p["kind"] != "payment":
            continue
        left = p["amount_minor"] - sum(
            a["amount_minor"]
            for a in allocations
            if a["company"] == p["company"] and a["payment_id"] == p["source_id"]
        )
        if left:
            variance(
                {**p, "period": p["transaction_date"][:7] + "-01"},
                p["source_id"],
                "unallocated_payment",
                left,
            )
    legal = []
    for company, entity in control.items():
        for period in policy["periods"]:
            m = {k: 0 for k in METRICS}
            for b in active:
                if b["company"] != company or b["transaction_date"][:7] + "-01" != period:
                    continue
                if b["kind"] == "booking":
                    m["bookings_minor"] += b["amount_minor"]
                if b["kind"] == "erp_posting" and (company, b["invoice_id"]) in headers:
                    m["erp_posted_minor"] += b["amount_minor"]
            for i in invoices:
                if i["company"] == company and i["period"] == period:
                    for target, key in [
                        ("gross_invoice_minor", "gross_minor"),
                        ("credits_minor", "credits_minor"),
                        ("net_invoice_minor", "net_minor"),
                    ]:
                        m[target] += i[key]
            m["allocated_cash_minor"] = sum(
                a["amount_minor"]
                for a in allocations
                if a["company"] == company and a["period"] == period
            )
            m["elimination_minor"] = sum(
                x["elimination_minor"]
                for x in eliminations
                if x["company"] == company and x["period"] == period
            )
            m["consolidated_invoice_minor"] = m["net_invoice_minor"] - m["elimination_minor"]
            m["consolidated_erp_minor"] = m["erp_posted_minor"] - m["elimination_minor"]
            legal.append(
                dict(
                    company=company,
                    legal_entity=entity["legal_entity"],
                    period=period,
                    currency=policy["currency"],
                    **m,
                )
            )
    parent = []
    for period in policy["periods"]:
        parent.append(
            dict(
                period=period,
                currency=policy["currency"],
                **{k: sum(r[k] for r in legal if r["period"] == period) for k in METRICS},
            )
        )
    bridge = []
    if previous is not None:
        before = {r["period"]: r for r in previous}
        for r in parent:
            for key in METRICS:
                old = before[r["period"]][key]
                bridge.append(
                    dict(
                        period=r["period"],
                        metric=key,
                        before_minor=old,
                        after_minor=r[key],
                        delta_minor=r[key] - old,
                    )
                )
    return dict(
        fct_invoices=invoices,
        fct_allocations=allocations,
        intercompany_eliminations=eliminations,
        reconciliation_variances=variances,
        legal_entity_totals=legal,
        portfolio_totals=parent,
        restatement_bridge=bridge,
    )
