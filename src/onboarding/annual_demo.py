"""Actual annual source intake, PostgreSQL/dbt, independent oracle and rejected publication."""

import argparse
import copy
import json
from pathlib import Path
from . import annual_fixtures as fixture
from .sandbox import Sandbox
from .financial_demo import financial_send, totals
from .pass2_demo import send, post, valid_handoff
from .execution import step
from .reporting import approve_policy, freeze, build, oracle_snapshot, plain
from .contracts import digest
from .db import connect


def setup(stack):
    for message in stack.messages:
        send(stack, message)
    assert all(
        post(stack, "/v1/admission/" + c, {}, "controller")["passed"] for c in ["cedar", "meridian"]
    )
    assert not post(stack, "/v1/admission/summit", {}, "controller")["passed"]
    rows = fixture.records()
    accepted = []
    for row in rows:
        response = financial_send(stack, row)
        if row["company"] == "summit" and row["kind"] == "booking":
            assert (
                response["status"] == "rejected"
                and response["reason"] == "financial_identity_unresolved"
            )
        else:
            assert response["status"] == "accepted", (row["company"], row["source_id"], response)
            accepted.append(row)
    approve_policy(stack.reviewer_dsn, 1, fixture.policy(accepted))
    return accepted


def execute(stack, workspace):
    rows = setup(stack)
    effect = valid_handoff(stack)
    assert step(stack.sender_config, effect) == "confirmed"
    freeze(stack.reviewer_dsn, "original", 1, fixture.ORIGINAL_CUTOFF)
    first = build(stack, "original", Path(workspace) / "original")
    original_hash = digest(first["results"])
    assert financial_send(stack, rows[1])["duplicate"]
    rejected = []
    for name, changes in [
        ("wrong_entity", {"legal_entity": "LE-US-02"}),
        ("wrong_owner", {"source": "hubspot", "owner": "crm"}),
        ("unknown_identity", {"source_customer_id": "not-reviewed"}),
    ]:
        r = financial_send(stack, {**rows[1], **changes, "event_id": "annual-negative-" + name})
        assert r["status"] == "rejected"
        rejected.append({"case": name, "response": r})
    revised = fixture.corrections(rows)
    for row in revised:
        assert financial_send(stack, row)["status"] == "accepted"
    freeze(stack.reviewer_dsn, "original-cutoff-replay", 1, fixture.ORIGINAL_CUTOFF)
    assert oracle_snapshot(stack, "original-cutoff-replay") == oracle_snapshot(stack, "original")
    freeze(stack.reviewer_dsn, "restated", 1, fixture.REVISED_CUTOFF, "original")
    second = build(stack, "restated", Path(workspace) / "restated")
    assert (
        totals(second)["consolidated_invoice_minor"] - totals(first)["consolidated_invoice_minor"]
        == 4500000
    )
    latest = {(r["company"], r["kind"], r["source_id"]): r for r in rows}
    latest.update({(r["company"], r["kind"], r["source_id"]): r for r in revised})
    bad = copy.deepcopy(revised[1])
    bad.update(
        revision=3,
        event_id="annual-unbalanced:3",
        amount_minor=bad["amount_minor"] + 1,
        observed_at="2027-01-16T12:00:00+00:00",
    )
    assert financial_send(stack, bad)["status"] == "accepted"
    freeze(stack.reviewer_dsn, "unbalanced-candidate", 1, "2027-01-17T00:00:00+00:00", "restated")
    blocked = build(
        stack, "unbalanced-candidate", Path(workspace) / "blocked", expect_success=False
    )
    assert blocked["return_code"] != 0 and any(r["status"] == "fail" for r in blocked["results"])
    with connect(stack.reviewer_dsn) as c:
        saved = c.execute(
            "SELECT results FROM financial_publications WHERE report_id='original'"
        ).fetchone()["results"]
        assert digest(saved) == original_hash
        assert c.execute("SELECT count(*) n FROM financial_publications").fetchone()["n"] == 2
        source_events = c.execute("SELECT * FROM financial_events ORDER BY id").fetchall()
        frozen = {
            t: c.execute("SELECT * FROM " + t + " ORDER BY " + key).fetchall()
            for t, key in [
                ("financial_policies", "version"),
                ("financial_snapshots", "id"),
                ("financial_inputs", "report_id,event_id"),
            ]
        }
    with connect(stack.receiver_admin) as c:
        assert c.execute("SELECT count(*) n FROM effects").fetchone()["n"] == 1
        assert (
            c.execute("SELECT count(*) n FROM requests WHERE operation='apply'").fetchone()["n"]
            == 1
        )
    return plain(
        dict(
            schema_version="annual-execution.v1",
            synthetic=True,
            currency="USD",
            money_unit="integer_minor_units",
            lane="actual_local_postgresql_http_and_dbt_postgres",
            native_vendor_calls=0,
            scenario=fixture.policy(rows)["scenario"],
            periods=fixture.PERIODS,
            source_event_count=len(source_events),
            original_source_count=len(rows),
            attempted_base_source_count=len(fixture.records()),
            rejected_held_crm_bookings=sum(
                r["status"] == "rejected"
                and r["body"]["company"] == "summit"
                and r["body"]["kind"] == "booking"
                for r in source_events
            ),
            source_controls_original=fixture.source_controls(rows),
            source_controls_restated=fixture.source_controls(list(latest.values())),
            original=first,
            restated=second,
            totals_before=totals(first),
            totals_after=totals(second),
            original_report_unchanged=True,
            original_cutoff_replay_equal=True,
            rejected_updates=rejected,
            blocked_candidate={"published": False, "dbt": blocked},
            source_events=source_events,
            records=frozen,
            downstream_effects=1,
            downstream_posts=1,
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("fresh_output_required")
    with Sandbox(a.workspace) as stack:
        result = execute(stack, Path(a.workspace) / "warehouse-runs")
    result["owned_resources_cleaned"] = True
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(
        json.dumps(
            {"source_records": result["source_event_count"], "totals": result["totals_after"]}
        )
    )


if __name__ == "__main__":
    main()
