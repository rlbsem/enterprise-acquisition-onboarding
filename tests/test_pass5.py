"""Focused independent Pass 5 negatives; real HTTP and PostgreSQL consequences."""

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from onboarding.db import connect
from onboarding.execution import step
from onboarding.fixtures import canonical
from onboarding.pass2_demo import valid_handoff, send, reviewed, post
from onboarding.sandbox import Sandbox
from onboarding.financial_demo import setup, financial_send
from onboarding.financial_fixtures import policy, ORIGINAL_CUTOFF
from onboarding.reporting import approve_policy, freeze, build
from onboarding.console import COOKIE


@pytest.fixture(scope="module")
def audit_runtime(tmp_path_factory):
    with Sandbox(tmp_path_factory.mktemp("pass5") / "runtime") as runtime:
        yield runtime


@pytest.fixture
def audited(audit_runtime):
    audit_runtime.reset()
    return audit_runtime


def record(name, data):
    folder = os.environ.get("PASS5_EVIDENCE")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        Path(folder, name + ".json").write_text(
            json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8"
        )


def state(stack):
    # Hash complete rows, not only counts: a denied mutation must not rewrite content.
    tables = [
        "companies",
        "messages",
        "source_records",
        "customer_fields",
        "crosswalks",
        "mapping_versions",
        "baselines",
        "quarantine",
        "quarantine_resolutions",
        "reviews",
        "review_decisions",
        "gate_runs",
        "audit",
        "business_events",
        "business_heads",
        "outbound",
        "outbound_attempts",
        "financial_events",
        "financial_snapshots",
        "financial_inputs",
        "financial_publications",
    ]
    with connect(stack.admin_dsn) as c:
        rows = {
            t: c.execute("SELECT to_jsonb(t) AS row FROM " + t + " t").fetchall() for t in tables
        }
    return {
        t: hashlib.sha256(
            json.dumps(sorted(json.dumps(r, sort_keys=True, default=str) for r in rs)).encode()
        ).hexdigest()
        for t, rs in rows.items()
    }


def login(stack, user):
    c = httpx.Client(base_url=stack.url, trust_env=False)
    r = c.post(
        "/console/api/login",
        headers={"Origin": stack.url},
        json={k: stack.console_credentials[user][k] for k in ["username", "password"]},
    )
    assert r.status_code == 200
    return c, {"Origin": stack.url, "X-CSRF-Token": r.json()["csrf"]}


def summit(stack):
    for message in stack.messages:
        if message["company"] == "summit":
            send(stack, message)
    return reviewed(stack)["quarantine"][0]


def test_pass5_cross_company_candidate_and_forged_review_id_leave_no_mutation(audited):
    s = audited
    q = summit(s)
    c, headers = login(s, "reviewer")
    try:
        before = state(s)
        wrong = c.post(
            "/console/api/companies/summit/identity",
            headers=headers,
            json={
                "quarantine_id": q["id"],
                "candidate": canonical("cedar"),
                "reason": "Pass 5 deliberate cross-company candidate",
            },
        )
        assert (
            wrong.status_code == 409
            and wrong.json()["detail"] == "candidate_not_in_original_review"
        )
        assert state(s) == before
        proposal = c.post(
            "/console/api/companies/summit/identity",
            headers=headers,
            json={
                "quarantine_id": q["id"],
                "candidate": canonical("summit"),
                "reason": "Pass 5 legitimate pending proposal",
            },
        ).json()["review_id"]
        before = state(s)
        forged = c.post(
            "/console/api/companies/summit/reviews/00000000-0000-0000-0000-000000000001/decision",
            headers=headers,
            json={"result": "approved", "reason": "Pass 5 forged identifier"},
        )
        cross = c.post(
            f"/console/api/companies/cedar/reviews/{proposal}/decision",
            headers=headers,
            json={"result": "approved", "reason": "Pass 5 path substitution"},
        )
        bypass = c.post(
            f"/console/api/companies/summit/reviews/{proposal}/decision",
            headers=headers,
            json={
                "result": "approved",
                "reason": "Pass 5 altered candidate",
                "candidate": canonical("cedar"),
            },
        )
        assert [forged.status_code, cross.status_code, bypass.status_code] == [409, 403, 422]
        assert state(s) == before
        with connect(s.dsn) as db:
            assert (
                db.execute(
                    "SELECT count(*) n FROM crosswalks WHERE company='summit' AND source='legacy-crm'"
                ).fetchone()["n"]
                == 0
            )
            assert (
                db.execute(
                    "SELECT status FROM messages WHERE id=%s", (q["message_id"],)
                ).fetchone()["status"]
                == "quarantined"
            )
        record(
            "identity-negative",
            {
                "statuses": [
                    wrong.status_code,
                    forged.status_code,
                    cross.status_code,
                    bypass.status_code,
                ],
                "rejection": wrong.json(),
                "original_quarantine": {k: q[k] for k in ["id", "message_id", "reason", "hash"]},
                "control_rows_unchanged": True,
                "pending_proposal": proposal,
                "unauthorized_links": 0,
            },
        )
    finally:
        c.close()


def test_pass5_all_console_write_routes_enforce_role_and_csrf_before_mutation(audited):
    s = audited
    q = summit(s)
    proposal = post(
        s,
        "/v1/reviews/summit/identity",
        {
            "quarantine_id": q["id"],
            "candidate": canonical("summit"),
            "reason": "Pass 5 prepared decision target",
        },
    )["review_id"]
    routes = {
        "identity": {
            "quarantine_id": q["id"],
            "candidate": canonical("summit"),
            "reason": "attack",
        },
        "mapping-preview": {"contract": reviewed(s)["contract"]},
        "mapping": {"contract": reviewed(s)["contract"], "coverage": {}, "reason": "attack"},
        f"reviews/{proposal}/decision": {"result": "approved", "reason": "attack"},
        "correction": {"quarantine_id": q["id"], "message_id": q["message_id"], "reason": "attack"},
        "admission": {"reason": "attack"},
    }
    checks = []
    before = state(s)
    for user in ["sponsor", "cedar-leader", "reviewer"]:
        c, headers = login(s, user)
        try:
            for suffix, body in routes.items():
                if user != "reviewer":
                    variants = [("role_or_scope", headers)]
                else:
                    variants = [
                        ("missing_csrf", {"Origin": s.url}),
                        ("wrong_csrf", {**headers, "X-CSRF-Token": "forged"}),
                        ("foreign_origin", {**headers, "Origin": "https://attacker.invalid"}),
                    ]
                for variant, h in variants:
                    r = c.post("/console/api/companies/summit/" + suffix, headers=h, json=body)
                    assert r.status_code == 403, (user, suffix, variant, r.status_code)
                    checks.append(
                        {
                            "role": user,
                            "route": suffix.replace(proposal, "pending-review"),
                            "negative": variant,
                            "status": r.status_code,
                        }
                    )
            assert state(s) == before
        finally:
            c.close()
    record(
        "write-route-matrix",
        {
            "requests": checks,
            "control_before": before,
            "control_after": state(s),
            "all_control_rows_unchanged": True,
        },
    )


def test_pass5_copied_cookie_after_logout_and_invalid_sessions_fail_closed(audited):
    s = audited
    c, headers = login(s, "reviewer")
    copied = c.cookies.get(COOKIE)
    with connect(s.console["auth_dsn"]) as db:
        assert db.execute("SELECT count(*) n FROM console_sessions").fetchone()["n"] == 1
    assert c.post("/console/api/logout", headers=headers).status_code == 200
    c.close()
    before = state(s)
    statuses = []
    for value in [copied, "invalid-session", "x" * 201, ""]:
        with httpx.Client(base_url=s.url, trust_env=False, cookies={COOKIE: value}) as attacker:
            for path in [
                "/session",
                "/overview",
                "/companies/summit",
                "/reports/original",
                "/reports/original/sources/1",
            ]:
                r = attacker.get("/console/api" + path)
                assert r.status_code == 401
                statuses.append(r.status_code)
            r = attacker.post(
                "/console/api/companies/summit/admission",
                headers=headers,
                json={"reason": "replayed signed-out session"},
            )
            assert r.status_code == 401
            statuses.append(r.status_code)
    assert state(s) == before
    with connect(s.console["auth_dsn"]) as db:
        assert db.execute("SELECT count(*) n FROM console_sessions").fetchone()["n"] == 0
    record(
        "session-replay",
        {
            "statuses": statuses,
            "revoked_sessions_remaining": 0,
            "all_control_rows_unchanged": True,
            "cookie_values_exported": False,
        },
    )


def test_pass5_observed_history_does_not_authorize_a_new_intent(audited):
    s = audited
    effect = valid_handoff(s)
    assert step(s.sender_config, effect) == "confirmed"
    old = s.messages[0]
    send(
        s,
        {**old, "event_id": "pass5-revocation", "data": {**old["data"], "legalEntity": "LE-WRONG"}},
    )
    assert step(s.sender_config, effect) == "confirmed"
    with s.client("controller") as c:
        r = c.post(
            "/v1/handoff/cedar",
            json={
                "canonical": canonical("cedar"),
                "references": {
                    k: "cedar-" + k for k in ["opportunity", "work_order", "finance_account"]
                },
            },
        )
    assert r.status_code == 409 and r.json()["detail"] == "current_admission_required"
    with connect(s.receiver_admin) as db:
        counts = {
            t: db.execute("SELECT count(*) n FROM " + t).fetchone()["n"]
            for t in ["effects", "records"]
        }
        counts["posts"] = db.execute(
            "SELECT count(*) n FROM requests WHERE operation IN('apply','duplicate')"
        ).fetchone()["n"]
    assert counts == {"effects": 1, "records": 1, "posts": 1}
    with connect(s.dsn) as db:
        assert db.execute("SELECT count(*) n FROM outbound").fetchone()["n"] == 1
        assert (
            db.execute("SELECT status FROM companies WHERE id='cedar'").fetchone()["status"]
            == "held"
        )
    record(
        "historical-authority",
        {
            "historical_readback": "confirmed",
            "new_plan_status": r.status_code,
            "new_plan_rejection": r.json(),
            "remote": counts,
            "outbound_intents": 1,
            "current_admission": "held",
        },
    )


def test_pass5_overallocated_payment_fails_dbt_and_unpublished_http_is_unreadable(
    audited, tmp_path
):
    s = audited
    original = setup(s)
    freeze(s.reviewer_dsn, "original", 1, ORIGINAL_CUTOFF)
    build(s, "original", tmp_path / "valid")
    a = next(
        b
        for b in original
        if b["company"] == "cedar" and b["kind"] == "allocation" and b["source_id"] == "A2"
    )
    extra = {**a, "source_id": "A-extra", "event_id": "pass5-extra-allocation"}
    assert financial_send(s, extra)["status"] == "accepted"
    approve_policy(s.reviewer_dsn, 2, policy(original + [extra]))
    freeze(s.reviewer_dsn, "overallocated-candidate", 2, ORIGINAL_CUTOFF)
    result = build(s, "overallocated-candidate", tmp_path / "invalid", expect_success=False)
    assert any(
        r["status"] == "fail" and "financial_amount_controls" in r["id"] for r in result["results"]
    )
    with connect(s.dsn) as db:
        event = db.execute(
            "SELECT event_id FROM financial_inputs WHERE report_id='original' AND body->>'company'='meridian' LIMIT 1"
        ).fetchone()["event_id"]
        own = db.execute(
            "SELECT event_id FROM financial_inputs WHERE report_id='original' AND body->>'company'='cedar' LIMIT 1"
        ).fetchone()["event_id"]
        assert [
            r["report_id"]
            for r in db.execute("SELECT report_id FROM financial_publications").fetchall()
        ] == ["original"]
    before = state(s)
    requests = []
    for user in ["sponsor", "cedar-leader", "reviewer"]:
        c, _ = login(s, user)
        try:
            paths = [
                ("/reports/overallocated-candidate", 404),
                (f"/reports/overallocated-candidate/sources/{own}", 404),
                ("/reports/forged-report", 404),
            ]
            if user == "cedar-leader":
                paths += [
                    ("/reports/original?company=meridian", 403),
                    ("/reports/original?company=all", 403),
                    (f"/reports/original/sources/{event}", 404),
                    (f"/reports/original/sources/{own}", 200),
                ]
                body = c.get("/console/api/reports/original").json()
                assert body["scope"] == ["cedar"]
                assert all(
                    row["company"] == "cedar" for rows in body["datasets"].values() for row in rows
                )
                assert all(row["company"] == "cedar" for row in body["sources"])
            overview = c.get("/console/api/overview").json()
            assert [r["report_id"] for r in overview["reports"]] == ["original"]
            for path, expected in paths:
                response = c.get("/console/api" + path)
                assert response.status_code == expected, (user, path, response.status_code)
                requests.append({"role": user, "path": path, "status": response.status_code})
        finally:
            c.close()
    assert state(s) == before
    record(
        "payment-and-publication-negative",
        {
            "payment_minor": 8000000,
            "allocation_sum_minor": 9000000,
            "dbt": result,
            "publications": ["original"],
            "requests": requests,
            "all_control_rows_unchanged_by_http_reads": True,
        },
    )
