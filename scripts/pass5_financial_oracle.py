"""Independent finite-scenario recalculation from exported source events, without dbt/oracle imports."""

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def audit(data):
    evidence = {}
    snapshots = {s["id"]: s for s in data["records"]["financial_snapshots"]}
    policies = {p["version"]: p for p in data["records"]["financial_policies"]}
    for version in ["original", "restated"]:
        snapshot = snapshots[version]
        policy = policies[snapshot["policy_version"]]
        assert sha(policy["body"]) == policy["hash"]
        selected = {}
        for event in data["source_events"]:
            b = event["body"]
            assert sha(b) == event["hash"]
            if event["status"] != "accepted" or datetime.fromisoformat(
                b["observed_at"]
            ) > datetime.fromisoformat(snapshot["cutoff"]):
                continue
            key = b["company"], b["kind"], b["source_id"]
            if key not in selected or b["revision"] > selected[key]["body"]["revision"]:
                selected[key] = event
        frozen = {
            r["event_id"]: r
            for r in data["records"]["financial_inputs"]
            if r["report_id"] == version
        }
        assert set(frozen) == {r["id"] for r in selected.values()}
        for event in selected.values():
            assert frozen[event["id"]]["body"] == event["body"]
            assert frozen[event["id"]]["hash"] == event["hash"]
        active, excluded = {}, []
        for key, event in selected.items():
            b = event["body"]
            entity = snapshot["control"][b["company"]]
            reason = (
                "admission_held"
                if not entity["admitted"]
                else "pre_acquisition"
                if b["transaction_date"] < entity["acquired_on"]
                else "outside_period"
                if b["transaction_date"][:7] + "-01" not in policy["body"]["periods"]
                else None
            )
            if reason:
                if b["kind"] == "invoice":
                    excluded.append(
                        {
                            "company": b["company"],
                            "invoice": b["source_id"],
                            "amount_minor": b["amount_minor"],
                            "reason": reason,
                        }
                    )
            else:
                active[key] = b
        headers = {(c, k): b for (c, kind, k), b in active.items() if kind == "invoice"}
        children = defaultdict(lambda: defaultdict(list))
        for (company, kind, _), b in active.items():
            if (
                kind in {"invoice_line", "credit", "erp_posting"}
                and (company, b["invoice_id"]) in headers
            ):
                children[company, b["invoice_id"]][kind].append(b)
        invoices = []
        for key, h in sorted(headers.items()):
            sums = {
                kind: sum(r["amount_minor"] for r in children[key][kind])
                for kind in ["invoice_line", "credit", "erp_posting"]
            }
            row = dict(
                company=key[0],
                invoice_id=key[1],
                gross_minor=h["amount_minor"],
                lines_minor=sums["invoice_line"],
                credits_minor=sums["credit"],
                net_minor=h["amount_minor"] - sums["credit"],
                erp_minor=sums["erp_posting"],
            )
            assert row["gross_minor"] == row["lines_minor"]
            observed = next(
                r
                for r in data[version]["results"]["fct_invoices"]
                if (r["company"], r["invoice_id"]) == key
            )
            assert all(observed[k] == v for k, v in row.items())
            invoices.append(row)
        assert len(invoices) == len(data[version]["results"]["fct_invoices"]) == 5
        allocations = [
            b
            for (company, kind, _), b in active.items()
            if kind == "allocation"
            and (company, b["invoice_id"]) in headers
            and (company, "payment", b["payment_id"]) in active
        ]
        for b in allocations:
            observed = next(
                r
                for r in data[version]["results"]["fct_allocations"]
                if (r["company"], r["allocation_id"]) == (b["company"], b["source_id"])
            )
            assert observed["amount_minor"] == b["amount_minor"]
            assert (
                observed["invoice_id"] == b["invoice_id"]
                and observed["payment_id"] == b["payment_id"]
            )
        assert len(allocations) == len(data[version]["results"]["fct_allocations"]) == 3
        for (company, kind, payment), b in active.items():
            if kind == "payment":
                assert (
                    sum(
                        a["amount_minor"]
                        for a in allocations
                        if (a["company"], a["payment_id"]) == (company, payment)
                    )
                    == b["amount_minor"]
                )
        eliminations = []
        for i in invoices:
            h = headers[i["company"], i["invoice_id"]]
            if h["counterparty_company"] is None:
                continue
            charges = [
                b
                for b in active.values()
                if b["kind"] == "intercompany_charge"
                and (
                    b["company"],
                    b["invoice_id"],
                    b["counterparty_company"],
                    b["counterparty_entity"],
                )
                == (
                    i["company"],
                    i["invoice_id"],
                    h["counterparty_company"],
                    h["counterparty_entity"],
                )
            ]
            accepts = [
                a
                for a in active.values()
                if a["kind"] == "intercompany_acceptance"
                and any(
                    (
                        a["company"],
                        a["invoice_id"],
                        a["counterparty_company"],
                        a["counterparty_entity"],
                        a["link_id"],
                    )
                    == (
                        h["counterparty_company"],
                        i["invoice_id"],
                        i["company"],
                        h["legal_entity"],
                        charge["link_id"],
                    )
                    for charge in charges
                )
            ]
            supported = (
                len(charges) == len(accepts) == 1
                and all(
                    b["amount_minor"] == i["net_minor"] and b["currency"] == h["currency"]
                    for b in charges + accepts
                )
                and i["erp_minor"] == i["net_minor"]
                and not any(
                    (a["company"], a["invoice_id"]) == (i["company"], i["invoice_id"])
                    for a in allocations
                )
            )
            amount = i["net_minor"] if supported else 0
            observed = next(
                r
                for r in data[version]["results"]["intercompany_eliminations"]
                if (r["company"], r["invoice_id"]) == (i["company"], i["invoice_id"])
            )
            assert (
                observed["elimination_minor"] == amount
                and observed["charge_count"] == len(charges)
                and observed["acceptance_count"] == len(accepts)
            )
            eliminations.append(
                {
                    "company": i["company"],
                    "invoice_id": i["invoice_id"],
                    "elimination_minor": amount,
                    "charge_count": len(charges),
                    "acceptance_count": len(accepts),
                }
            )
        amounts = dict(
            bookings_minor=sum(
                b["amount_minor"] for b in active.values() if b["kind"] == "booking"
            ),
            net_invoice_minor=sum(i["net_minor"] for i in invoices),
            erp_posted_minor=sum(i["erp_minor"] for i in invoices),
            allocated_cash_minor=sum(b["amount_minor"] for b in allocations),
            elimination_minor=sum(e["elimination_minor"] for e in eliminations),
        )
        amounts["consolidated_invoice_minor"] = (
            amounts["net_invoice_minor"] - amounts["elimination_minor"]
        )
        amounts["consolidated_erp_minor"] = (
            amounts["erp_posted_minor"] - amounts["elimination_minor"]
        )
        observed = {
            k: sum(r[k] for r in data[version]["results"]["portfolio_totals"]) for k in amounts
        }
        assert amounts == observed
        for metric in amounts:
            assert (
                sum(r[metric] for r in data[version]["results"]["legal_entity_totals"])
                == amounts[metric]
            )
        variances = {
            (
                i["company"],
                i["invoice_id"],
                "erp_posting_difference",
                i["net_minor"] - i["erp_minor"],
            )
            for i in invoices
            if i["net_minor"] != i["erp_minor"]
        }
        variances |= {
            (
                e["company"],
                e["invoice_id"],
                "intercompany_unresolved",
                headers[e["company"], e["invoice_id"]]["amount_minor"],
            )
            for e in eliminations
            if not e["elimination_minor"]
        }
        assert variances == {
            (r["company"], r["source_id"], r["code"], r["amount_minor"])
            for r in data[version]["results"]["reconciliation_variances"]
        }
        # Deliberately wrong grain: two lines x two posting entries multiply the header.
        key = ("cedar", "I1")
        naive = (
            headers[key]["amount_minor"]
            * len(children[key]["invoice_line"])
            * len(children[key]["erp_posting"])
        )
        assert naive != headers[key]["amount_minor"]
        evidence[version] = {
            "source_revisions_match_frozen_inputs": True,
            "source_count": len(frozen),
            "totals_minor": amounts,
            "invoice_recalculation": invoices,
            "elimination_evidence": eliminations,
            "excluded_invoices": excluded,
            "separate_variances": sorted(variances),
            "join_multiplication_negative": {
                "correct_gross_minor": headers[key]["amount_minor"],
                "naive_join_gross_minor": naive,
                "detected": True,
            },
            "source_set_sha256": sha(
                sorted(
                    [r["body"] for r in selected.values()],
                    key=lambda b: (b["company"], b["kind"], b["source_id"]),
                )
            ),
        }
    delta = {
        k: evidence["restated"]["totals_minor"][k] - evidence["original"]["totals_minor"][k]
        for k in evidence["original"]["totals_minor"]
    }
    assert delta == dict(
        bookings_minor=0,
        net_invoice_minor=2000000,
        erp_posted_minor=2000000,
        allocated_cash_minor=0,
        elimination_minor=0,
        consolidated_invoice_minor=2000000,
        consolidated_erp_minor=2000000,
    )
    return {
        "method": "standalone_source_event_selection_and_integer_document_arithmetic_no_application_oracle_imports",
        "versions": evidence,
        "restatement_delta_minor": delta,
        "differences": 0,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    data = json.loads(Path(a.input).read_bytes())
    result = audit(data)
    # Verify that the comparison is sensitive to an incorrect published figure.
    data["restated"]["results"]["portfolio_totals"][0]["consolidated_invoice_minor"] += 1
    try:
        audit(data)
    except AssertionError:
        result["one_cent_publication_mutation_detected"] = True
    else:
        raise AssertionError("negative_control_not_detected")
    Path(a.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"versions": 2, "differences": 0, "one_cent_negative_detected": True}))


if __name__ == "__main__":
    main()
