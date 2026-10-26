"""Source-linked financial consolidation, open variances and immutable restatement."""

import argparse
import copy
import json
from pathlib import Path
from .sandbox import Sandbox
from .db import connect
from .contracts import digest
from .pass2_demo import send, post, valid_handoff
from .execution import step
from .financial_fixtures import records, corrections, policy, ORIGINAL_CUTOFF, REVISED_CUTOFF
from .reporting import approve_policy, freeze, build, oracle_snapshot, plain


def financial_send(stack, b):
    return post(stack, "/v1/financial", b, "source", b)


def setup(stack):
    for m in stack.messages:
        send(stack, m)
    for company in ["cedar", "meridian"]:
        assert post(stack, "/v1/admission/" + company, {}, "controller")["passed"]
    assert not post(stack, "/v1/admission/summit", {}, "controller")["passed"]
    original = records()
    for b in original:
        assert financial_send(stack, b)["status"] == "accepted"
    approve_policy(stack.reviewer_dsn, 1, policy(original))
    return original


def totals(result):
    return {
        k: sum(r[k] for r in result["results"]["portfolio_totals"])
        for k in [
            "bookings_minor",
            "net_invoice_minor",
            "erp_posted_minor",
            "allocated_cash_minor",
            "elimination_minor",
            "consolidated_invoice_minor",
            "consolidated_erp_minor",
        ]
    }


def execute(stack, workspace):
    original = setup(stack)
    effect = valid_handoff(stack)
    assert step(stack.sender_config, effect) == "confirmed"
    with connect(stack.receiver_admin) as c:
        remote_before = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
        posts_before = c.execute(
            "SELECT count(*) n FROM requests WHERE operation IN('apply','duplicate')"
        ).fetchone()["n"]
    first_snapshot = freeze(stack.reviewer_dsn, "original", 1, ORIGINAL_CUTOFF)
    first = build(stack, "original", Path(workspace) / "original")
    initial_hash = digest(first["results"])
    assert totals(first) == dict(
        bookings_minor=55000000,
        net_invoice_minor=38800000,
        erp_posted_minor=38300000,
        allocated_cash_minor=23000000,
        elimination_minor=2000000,
        consolidated_invoice_minor=36800000,
        consolidated_erp_minor=36300000,
    )
    # Invalid source updates remain rejected and never change accepted financial facts.
    rejected = []
    for reason, change in [
        ("wrong_entity", {"legal_entity": "LE-US-02"}),
        ("wrong_currency", {"currency": "CAD"}),
        ("lower_authority", {"source": "hubspot", "owner": "crm"}),
        ("stale_revision", {}),
    ]:
        bad = {**original[1], **change, "event_id": "negative-" + reason}
        response = financial_send(stack, bad)
        assert response["status"] == "rejected"
        rejected.append({"case": reason, "response": response})
    assert financial_send(stack, original[1])["duplicate"]
    for b in corrections(original):
        assert financial_send(stack, b)["status"] == "accepted"
    freeze(stack.reviewer_dsn, "original-cutoff-replay", 1, ORIGINAL_CUTOFF)
    assert oracle_snapshot(stack, "original-cutoff-replay") == oracle_snapshot(stack, "original")
    second_snapshot = freeze(stack.reviewer_dsn, "restated", 1, REVISED_CUTOFF, "original")
    second = build(stack, "restated", Path(workspace) / "restated")
    changed = [r for r in second["results"]["restatement_bridge"] if r["delta_minor"]]
    assert len(changed) == 5 and all(
        r["period"] == "2026-01-01" and r["delta_minor"] == 2000000 for r in changed
    )
    with connect(stack.reviewer_dsn) as c:
        saved = c.execute(
            "SELECT results FROM financial_publications WHERE report_id='original'"
        ).fetchone()["results"]
        assert digest(saved) == initial_hash
    # A source-owned but unbalanced new line snapshot must fail real dbt data tests.
    bad = copy.deepcopy(corrections(original)[1])
    bad.update(
        revision=3,
        event_id="invoice_line:I1-L1:3",
        amount_minor=10000001,
        observed_at="2026-10-24T12:00:00+00:00",
    )
    assert financial_send(stack, bad)["status"] == "accepted"
    freeze(stack.reviewer_dsn, "unbalanced-candidate", 1, "2026-10-25T00:00:00+00:00", "restated")
    blocked = build(
        stack, "unbalanced-candidate", Path(workspace) / "blocked", expect_success=False
    )
    assert any(r["status"] == "fail" for r in blocked["results"])
    with connect(stack.reviewer_dsn) as c:
        assert c.execute("SELECT count(*) n FROM financial_publications").fetchone()["n"] == 2
        raw = c.execute("SELECT * FROM financial_events ORDER BY id").fetchall()
        frozen = {
            t: c.execute("SELECT * FROM " + t + " ORDER BY " + key).fetchall()
            for t, key in [
                ("financial_policies", "version"),
                ("financial_snapshots", "id"),
                ("financial_inputs", "report_id,event_id"),
                ("financial_publications", "report_id"),
            ]
        }
        financial_audit = c.execute(
            "SELECT * FROM audit WHERE action LIKE 'financial_%%' ORDER BY id"
        ).fetchall()
    with connect(stack.receiver_admin) as c:
        remote_after = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
        posts_after = c.execute(
            "SELECT count(*) n FROM requests WHERE operation IN('apply','duplicate')"
        ).fetchone()["n"]
    assert remote_before == remote_after == 1
    assert posts_before == posts_after == 1
    return plain(
        dict(
            lane="actual_local_postgresql_http_and_dbt_postgres",
            synthetic=True,
            currency="USD",
            money_unit="integer_minor_units",
            native_vendor_calls=0,
            original=first,
            restated=second,
            totals_before=totals(first),
            totals_after=totals(second),
            changed_bridge=changed,
            rejected_updates=rejected,
            original_report_unchanged=True,
            original_cutoff_replay_equal=True,
            downstream_effects_before=remote_before,
            downstream_effects_after=remote_after,
            downstream_posts_before=posts_before,
            downstream_posts_after=posts_after,
            financial_audit=financial_audit,
            blocked_candidate={"published": False, "dbt": blocked},
            snapshots=[first_snapshot, second_snapshot],
            source_events=raw,
            records=frozen,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args()
    out = Path(a.output)
    if out.exists():
        raise ValueError("fresh_output_required")
    with Sandbox(a.workspace) as stack:
        result = execute(stack, Path(a.workspace) / "warehouse-runs")
    result["owned_resources_cleaned"] = True
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(
        json.dumps(
            {
                "currency": "USD",
                "before": result["totals_before"],
                "after": result["totals_after"],
                "open_variances": result["restated"]["results"]["reconciliation_variances"],
                "blocked_candidate_published": False,
            }
        )
    )


if __name__ == "__main__":
    main()
