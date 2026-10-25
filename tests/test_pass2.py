import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from psycopg.conninfo import make_conninfo, conninfo_to_dict
import psycopg
import pytest
from onboarding.db import connect
from onboarding.execution import step, client
from onboarding.sandbox import child_env
from onboarding.fixtures import canonical, mapping, approve_mapping
from onboarding.business import fixtures
from onboarding.pass2_demo import execute, post, send, reviewed, valid_handoff, set_fault, coverage


def capture(name, expected, observed):
    if os.environ.get("ONBOARDING_TEST_EVIDENCE"):
        Path(os.environ["ONBOARDING_TEST_EVIDENCE"], name + ".json").write_bytes(
            (json.dumps({"expected": expected, "observed": observed}, indent=2) + "\n").encode()
        )


def test_complete_actual_review_resnapshot_and_lost_ack_workflow(stack):
    r = execute(stack)
    assert r["A_identity"]["after_passed"] and not r["B_wrong_entity"]["admission_passed"]
    assert r["C_resnapshot"]["final_gate"]["mapping_version"] == 2
    assert (
        r["D_E_delivery"]["uncertain"] == "uncertain"
        and r["D_E_delivery"]["recovered"] == "confirmed"
    )
    assert r["D_E_delivery"]["final_effects"] == 1
    assert len(r["control"]["quarantine_resolutions"]) == 3
    assert {row["body"]["version"] for row in r["control"]["source_record_history"]} == {1, 2}
    with connect(stack.dsn) as c:
        assert (
            c.execute("SELECT count(*) n FROM customers WHERE company='summit'").fetchone()["n"]
            == 2
        )
        original = c.execute("SELECT status FROM messages WHERE source='legacy-crm'").fetchone()
        assert original["status"] == "quarantined"


def test_review_identity_is_separate_and_scoped(stack):
    for message in stack.messages:
        if message["company"] == "summit":
            send(stack, message)
    with stack.client(company="summit", source="legacy-crm") as c:
        assert c.get("/v1/reviews/summit").status_code == 403
        assert (
            c.post(
                "/v1/reviews/summit/identity",
                json={
                    "quarantine_id": 1,
                    "candidate": canonical("summit"),
                    "reason": "untrusted source approval",
                },
            ).status_code
            == 403
        )
    with stack.client("reviewer") as c:
        assert c.get("/v1/reviews/unknown-company").status_code == 403
    view = reviewed(stack)
    q = view["quarantine"][0]
    post(
        stack,
        "/v1/reviews/summit/identity",
        {
            "quarantine_id": q["id"],
            "candidate": canonical("cedar"),
            "reason": "wrong entity candidate",
        },
        expected=409,
    )
    assert q["body"]["data"]["legacy_name"] == "Common Property Group"


def test_stale_identity_decision_fails_closed(stack):
    for message in stack.messages:
        if message["company"] == "summit":
            send(stack, message)
    q = reviewed(stack)["quarantine"][0]
    proposal = post(
        stack,
        "/v1/reviews/summit/identity",
        {"quarantine_id": q["id"], "candidate": canonical("summit"), "reason": "Scoped review"},
    )["review_id"]
    original = next(
        m for m in stack.messages if m["company"] == "summit" and m["source"] == "legacy-crm"
    )
    newer = {**original, "event_id": "crm-newer", "data": {**original["data"], "revision": 2}}
    send(stack, newer)
    error = post(
        stack,
        f"/v1/reviews/summit/{proposal}/decision",
        {"result": "approved", "reason": "stale snapshot"},
        expected=409,
    )
    assert error["detail"] == "review_context_stale"
    with connect(stack.dsn) as c:
        assert (
            c.execute(
                "SELECT count(*) n FROM crosswalks WHERE company='summit' AND source='legacy-crm'"
            ).fetchone()["n"]
            == 0
        )


def test_invalid_mapping_contract_and_incomplete_inventory_are_rejected(stack):
    valid_handoff(stack)
    view = reviewed(stack, "cedar")
    body = copy.deepcopy(view["contract"])
    body["sources"]["lmn"]["states"] = {}
    post(
        stack,
        "/v1/reviews/cedar/mapping",
        {"contract": body, "coverage": {}, "reason": "unsupported mapping"},
        expected=409,
    )
    post(
        stack,
        "/v1/reviews/cedar/mapping",
        {"contract": view["contract"], "coverage": {}, "reason": "missing source inventory"},
        expected=409,
    )
    with connect(stack.dsn) as c:
        assert (
            c.execute("SELECT active_mapping FROM companies WHERE id='cedar'").fetchone()[
                "active_mapping"
            ]
            == 1
        )


def test_stale_mapping_approval_does_not_activate_or_rewrite_history(stack):
    valid_handoff(stack)
    view = reviewed(stack, "cedar")
    contract = view["contract"]
    proposal = post(
        stack,
        "/v1/reviews/cedar/mapping",
        {
            "contract": contract,
            "coverage": coverage(view, contract),
            "reason": "Exact source review",
        },
    )["review_id"]
    old = next(m for m in stack.messages if m["company"] == "cedar" and m["source"] == "lmn")
    send(
        stack,
        {
            **old,
            "event_id": "new-ops",
            "data": {**old["data"], "revision": 2, "jobState": "Complete"},
        },
    )
    post(
        stack,
        f"/v1/reviews/cedar/{proposal}/decision",
        {"result": "approved", "reason": "stale reviewed inventory"},
        expected=409,
    )
    with connect(stack.dsn) as c:
        assert (
            c.execute("SELECT active_mapping FROM companies WHERE id='cedar'").fetchone()[
                "active_mapping"
            ]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM source_record_history WHERE company='cedar'"
            ).fetchone()["n"]
            == 4
        )


@pytest.mark.parametrize("change", ["admission", "mapping", "business", "source_revision"])
def test_revoked_or_changed_authority_prevents_new_dispatch(stack, change):
    effect = valid_handoff(stack)
    if change == "admission":
        old = stack.messages[0]
        send(
            stack,
            {**old, "event_id": "new-conflict", "data": {**old["data"], "legalEntity": "LE-WRONG"}},
        )
    elif change == "mapping":
        approve_mapping(
            stack.admin_dsn, "cedar", 2, mapping("hubspot"), "fixture-reviewer", "new-version"
        )
    elif change == "business":
        body = fixtures("cedar", "LE-CA-01", ["hubspot", "lmn", "quickbooks"])[1]
        body.update(event_id="work-v2", revision=2, state="completed")
        post(stack, "/v1/business", body, "source", body)
    else:
        old = stack.messages[0]
        send(stack, {**old, "event_id": "new-source", "data": {**old["data"], "revision": 2}})
    assert step(stack.sender_config, effect) == "blocked"
    with connect(stack.receiver_admin) as c:
        effects = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
        posts = c.execute("SELECT count(*) n FROM requests WHERE operation='apply'").fetchone()["n"]
        assert effects == posts == 0
    capture(
        "authorization-" + change,
        {"state": "blocked", "effects": 0, "posts": 0},
        {"state": "blocked", "effects": effects, "posts": posts},
    )


def test_lost_ack_history_reconciliation_does_not_require_new_write_authority(stack):
    effect = valid_handoff(stack)
    set_fault(stack, effect, ["lost_ack"])
    assert step(stack.sender_config, effect, timeout=0.2) == "uncertain"
    with connect(stack.dsn) as c:
        c.execute("UPDATE companies SET status='held',gate_hash=NULL WHERE id='cedar'")
    assert step(stack.sender_config, effect) == "confirmed"
    with connect(stack.receiver_admin) as c:
        assert (
            c.execute("SELECT count(*) n FROM requests WHERE operation='apply'").fetchone()["n"]
            == 1
        )
        assert c.execute("SELECT count(*) n FROM records").fetchone()["n"] == 1


def test_unavailable_receiver_before_commit_exhausts_bounded_budget(stack):
    effect = valid_handoff(stack)
    set_fault(stack, effect, ["unavailable"] * 3)
    for attempt in range(1, 4):
        assert step(stack.sender_config, effect, respect_due=False) == "uncertain"
        # Ordinary calls respect the persisted backoff; the finite test loop alone accelerates it.
        # After attempt three, exhaustion takes precedence over waiting for another due time.
        assert step(stack.sender_config, effect) == ("uncertain" if attempt < 3 else "exhausted")
        with connect(stack.dsn) as c:
            assert c.execute("SELECT attempts FROM outbound").fetchone()["attempts"] == attempt
    assert step(stack.sender_config, effect, respect_due=False) == "exhausted"
    assert step(stack.sender_config, effect, respect_due=False) == "exhausted"
    with connect(stack.dsn) as c:
        actual = c.execute("SELECT state,attempts FROM outbound").fetchone()
        assert actual["attempts"] == 3 and actual["state"] == "exhausted"
    with connect(stack.receiver_admin) as c:
        effects = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
        assert effects == 0
        assert (
            c.execute("SELECT count(*) n FROM requests WHERE operation='apply'").fetchone()["n"]
            == 3
        )
    capture(
        "exhaustion",
        {"state": "exhausted", "attempts": 3, "effects": 0},
        {**actual, "effects": effects},
    )


def test_unknown_receiver_readback_never_counts_as_absence(stack):
    effect = valid_handoff(stack)
    broken = {**stack.sender_config, "receiver": {**stack.receiver, "url": "http://127.0.0.1:1"}}
    assert step(broken, effect, timeout=0.2) == "uncertain"
    with connect(stack.dsn) as c:
        assert c.execute("SELECT attempts FROM outbound").fetchone()["attempts"] == 0


def test_sender_cannot_open_receiver_database_or_forge_governance(stack, monkeypatch):
    dbname = conninfo_to_dict(stack.receiver_dsn)["dbname"]
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        with psycopg.connect(make_conninfo(stack.dsn, dbname=dbname)):
            pass
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect(stack.dsn) as c:
            c.execute(
                "INSERT INTO reviews(id,company,kind,actor,reason,context_hash,payload) VALUES(gen_random_uuid(),'cedar','identity','forged','x','x','{}')"
            )
    monkeypatch.setenv("ONBOARDING_TEST_ADMIN_DSN", "must-not-inherit")
    assert "ONBOARDING_TEST_ADMIN_DSN" not in child_env()
    assert set(json.loads(stack.sender_path.read_text())) == {"dsn", "receiver"}


def test_receiver_exact_content_and_independent_readback(stack):
    effect = valid_handoff(stack)
    assert step(stack.sender_config, effect) == "confirmed"
    with connect(stack.dsn) as c:
        payload = c.execute("SELECT payload FROM outbound").fetchone()["payload"]
    with client(stack.sender_config) as c:
        assert (
            c.post("/effects", json=payload, headers={"Idempotency-Key": effect}).status_code == 200
        )
        assert (
            c.post(
                "/effects",
                json={**payload, "canonical": canonical("meridian")},
                headers={"Idempotency-Key": effect},
            ).status_code
            == 409
        )
    with connect(stack.receiver_admin) as c:
        c.execute("ALTER TABLE records DISABLE TRIGGER records_immutable")
        c.execute("UPDATE records SET body=jsonb_set(body,'{legal_entity}','\"wrong\"')")
        c.execute("ALTER TABLE records ENABLE TRIGGER records_immutable")
    assert step(stack.sender_config, effect) == "blocked"
    with connect(stack.receiver_admin) as c:
        assert (
            c.execute("SELECT count(*) n FROM requests WHERE operation='apply'").fetchone()["n"]
            == 1
        )


def test_real_worker_process_death_recovers_original_effect(stack, tmp_path):
    effect = valid_handoff(stack)
    marker = tmp_path / "commit-observed"
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "onboarding.execution",
            "--config",
            str(stack.sender_path),
            "--effect",
            effect,
            "--crash-marker",
            str(marker),
        ],
        env=child_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and time.monotonic() < deadline and child.poll() is None:
            time.sleep(0.05)
        assert marker.exists()
        assert step(stack.sender_config, effect) == "busy"
        child.kill()
        child.wait(timeout=8)
        assert step(stack.sender_config, effect) == "confirmed"
        with connect(stack.receiver_admin) as c:
            effects = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
            posts = c.execute("SELECT count(*) n FROM requests WHERE operation='apply'").fetchone()[
                "n"
            ]
        assert effects == posts == 1
        if os.environ.get("ONBOARDING_TEST_EVIDENCE"):
            Path(os.environ["ONBOARDING_TEST_EVIDENCE"], "process-death.json").write_bytes(
                (
                    json.dumps(
                        {
                            "actual_process_terminated": True,
                            "child_exit_code": child.returncode,
                            "competing_worker": "busy",
                            "confirmed_after_restart": True,
                            "receiver_effects": effects,
                            "receiver_posts": posts,
                        }
                    )
                    + "\n"
                ).encode()
            )
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_finance_state_cannot_be_manufactured_by_crm(stack):
    valid_handoff(stack)
    body = fixtures("cedar", "LE-CA-01", ["hubspot", "lmn", "quickbooks"])[2]
    body.update(source="hubspot", event_id="forged-finance")
    r = post(stack, "/v1/business", body, "source", body)
    assert r["status"] == "rejected" and r["reason"] == "business_source_authority_denied"
