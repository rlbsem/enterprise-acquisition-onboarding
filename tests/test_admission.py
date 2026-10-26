import copy
from concurrent.futures import ThreadPoolExecutor
import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb
from onboarding.db import connect
from onboarding.demo import execute
from onboarding.engine import admit, portfolio
from onboarding.fixtures import approve_mapping, mapping


def send(stack, message):
    with stack.client(company=message["company"], source=message["source"]) as c:
        r = c.post("/v1/intake", json=message)
        r.raise_for_status()
        return r.json()


def company(stack, which="cedar"):
    return [copy.deepcopy(m) for m in stack.messages if m["company"] == which]


def counts(stack):
    with connect(stack.dsn) as c:
        return {
            t: c.execute("SELECT count(*) n FROM " + t).fetchone()["n"]
            for t in ["messages", "deliveries", "source_records", "customer_fields", "quarantine"]
        }


def test_full_http_demo_all_four_acceptance_scenarios(stack):
    r = execute(stack)
    assert r["scenarios"]["A_clean"]["observed_included_companies"] == 2
    assert r["scenarios"]["B_ambiguity"]["observed"] == "ambiguous_identity"
    assert (
        r["scenarios"]["C_readiness_gate"]["invalid_legal_entity_response"]["reason"]
        == "incorrect_legal_entity"
    )
    assert r["scenarios"]["D_replay"]["after"] == 8
    assert not r["portfolio"]["companies"][2]["included"]


def test_import_is_not_admission_and_same_local_ids_do_not_merge(stack):
    for m in stack.messages[:6]:
        assert send(stack, m)["status"] == "accepted"
    assert portfolio(stack.dsn)["included_companies"] == 0
    for name in ["cedar", "meridian"]:
        assert admit(stack.dsn, name)["passed"]
    view = portfolio(stack.dsn)
    assert view["included_customer_accounts"] == 2
    ids = {row["canonical"] for c in view["companies"] for row in c["source_records"]}
    assert len(ids) == 2
    assert {r["source_id"] for c in view["companies"] for r in c["source_records"]} == {"100"}


def test_weak_name_candidates_remain_unlinked_and_raw_evidence_is_preserved(stack):
    m = company(stack, "summit")[0]
    r = send(stack, m)
    assert r["reason"] == "ambiguous_identity"
    with connect(stack.dsn) as c:
        q = c.execute("SELECT * FROM quarantine").fetchone()
        assert len(q["detail"]["candidate_ids"]) == 2
        assert c.execute("SELECT body FROM messages").fetchone()["body"] == m
    assert counts(stack)["source_records"] == 0 and not admit(stack.dsn, "summit")["passed"]


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("legalEntity", "LE-US-02", "incorrect_legal_entity"),
        ("companyId", "", "missing_source_identifier"),
        ("dealStage", "Unmapped CRM stage", "unmapped_lifecycle_state"),
        ("version", True, "invalid_source_revision"),
    ],
)
def test_malformed_owned_records_quarantine_without_projecting(stack, field, value, reason):
    m = company(stack)[0]
    m["data"][field] = value
    assert send(stack, m)["reason"] == reason
    assert counts(stack)["source_records"] == 0 and not admit(stack.dsn, "cedar")["passed"]


def test_missing_identifier_and_injected_lower_authority_field_are_not_ignored(stack):
    m = company(stack)[0]
    del m["data"]["companyId"]
    assert send(stack, m)["reason"] == "unmapped_or_missing_source_fields"
    m = company(stack)[1]
    m["data"]["dealStage"] = "closedwon"
    assert send(stack, m)["reason"] == "unmapped_or_missing_source_fields"
    assert counts(stack)["customer_fields"] == 0


def test_exact_replay_preserves_readiness_but_content_collision_blocks(stack):
    messages = company(stack)
    for m in messages:
        send(stack, m)
    assert admit(stack.dsn, "cedar")["passed"]
    before = counts(stack)
    r = send(stack, messages[0])
    after = counts(stack)
    assert r["duplicate"] and after["source_records"] == before["source_records"] == 3
    assert portfolio(stack.dsn)["included_companies"] == 1
    m = copy.deepcopy(messages[0])
    m["data"]["companyName"] = "Changed identity"
    assert send(stack, m)["reason"] == "event_identity_content_conflict"
    with connect(stack.dsn) as c:
        assert (
            c.execute("SELECT body FROM messages WHERE source=%s", ("hubspot",)).fetchone()["body"]
            == messages[0]
        )
    assert portfolio(stack.dsn)["included_companies"] == 0


def test_new_envelope_same_source_version_is_still_one_business_record(stack):
    m = company(stack)[0]
    send(stack, m)
    m["event_id"] = "another-delivery-id"
    assert send(stack, m)["reason"] == "same_record_replay"
    assert counts(stack)["messages"] == 2 and counts(stack)["source_records"] == 1


@pytest.mark.parametrize(
    "change,expected",
    [
        ("stale", "stale_or_conflicting_source_revision"),
        ("gap", "source_revision_gap"),
        ("time", "source_observation_regression"),
        ("state", "unsupported_lifecycle_transition"),
    ],
)
def test_no_regress_preserves_latest_owned_state(stack, change, expected):
    m = company(stack)[0]
    send(stack, m)
    newer = copy.deepcopy(m)
    newer["event_id"] = "changed"
    newer["data"]["version"] = 2
    if change == "stale":
        newer["data"]["version"] = 1
        newer["data"]["companyName"] = "Other"
    elif change == "gap":
        newer["data"]["version"] = 3
    elif change == "time":
        newer["observed_at"] = "2026-09-01T00:00:00+00:00"
    else:
        newer["data"]["dealStage"] = "new"
    assert send(stack, newer)["reason"] == expected
    with connect(stack.dsn) as c:
        assert c.execute("SELECT raw FROM source_records").fetchone()["raw"] == m["data"]


def test_new_valid_source_revision_requires_new_reviewed_baseline(stack):
    messages = company(stack)
    for m in messages:
        send(stack, m)
    assert admit(stack.dsn, "cedar")["passed"]
    changed = messages[1]
    changed["event_id"] = "ops-v2"
    changed["data"].update(revision=2, jobState="Complete")
    assert send(stack, changed)["status"] == "accepted"
    assert "source_coverage_gap:lmn" in admit(stack.dsn, "cedar")["issues"]
    assert portfolio(stack.dsn)["included_companies"] == 0


def test_source_inventory_missing_is_unknown_not_zero(stack):
    for m in company(stack)[:2]:
        send(stack, m)
    gate = admit(stack.dsn, "cedar")
    assert not gate["passed"] and "source_coverage_gap:quickbooks" in gate["issues"]
    with connect(stack.admin_dsn) as c:
        c.execute("DELETE FROM source_records WHERE source='lmn'")
    assert "source_coverage_gap:lmn" in admit(stack.dsn, "cedar")["issues"]


def test_concurrent_real_http_replays_commit_once(stack):
    m = company(stack)[0]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: send(stack, m), range(6)))
    assert sum(r["duplicate"] for r in results) == 5
    assert counts(stack)["messages"] == counts(stack)["source_records"] == 1
    assert counts(stack)["deliveries"] == 6


def test_http_identities_are_scoped_and_sponsor_is_read_only(stack):
    with httpx.Client(base_url=stack.url, trust_env=False) as c:
        assert c.get("/v1/portfolio").status_code == 401
        assert c.post("/v1/intake", json=company(stack)[0]).status_code == 401
    with stack.client(company="cedar", source="hubspot") as c:
        assert c.post("/v1/intake", json=company(stack, "meridian")[0]).status_code == 403
        assert c.post("/v1/admission/cedar").status_code == 403
        assert c.get("/v1/portfolio").status_code == 403
    with stack.client("viewer") as c:
        assert c.post("/v1/admission/cedar").status_code == 403
        assert c.post("/v1/intake", json=company(stack)[0]).status_code == 403
        assert c.get("/v1/portfolio").status_code == 200
    assert counts(stack)["messages"] == 0


def test_service_database_role_cannot_change_governance_or_erase_evidence(stack):
    send(stack, company(stack)[0])
    for query in [
        "UPDATE mapping_versions SET reviewed_by='forged'",
        "UPDATE companies SET legal_entity='wrong'",
        "DELETE FROM messages",
        "UPDATE audit SET action='forged'",
    ]:
        with pytest.raises(psycopg.Error):
            with connect(stack.dsn) as c:
                c.execute(query)
    with pytest.raises(psycopg.errors.RaiseException, match="immutable_message"):
        with connect(stack.admin_dsn) as c:
            c.execute("UPDATE messages SET body='{}'")


def test_governance_rejects_conflicting_field_ownership_and_duplicate_crosswalk(stack):
    bad = mapping("hubspot")
    bad["sources"]["lmn"]["fields"]["dealStage"] = "sales_state"
    with pytest.raises(ValueError):
        approve_mapping(stack.admin_dsn, "cedar", 2, bad, "reviewer", "scope-test")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(stack.admin_dsn) as c:
            c.execute(
                "INSERT INTO crosswalks SELECT company,legal_entity,source,'another',canonical,version,proof FROM crosswalks WHERE company='cedar' AND source='hubspot'"
            )
    assert admit(stack.dsn, "cedar")["mapping_version"] == 1


def test_mapping_change_is_versioned_and_invalidates_old_source_coverage(stack):
    for m in company(stack):
        send(stack, m)
    assert admit(stack.dsn, "cedar")["passed"]
    approve_mapping(
        stack.admin_dsn, "cedar", 2, mapping("hubspot"), "synthetic-reviewer", "review.v2"
    )
    with pytest.raises(ValueError):
        approve_mapping(stack.admin_dsn, "cedar", 2, mapping("hubspot"), "reviewer", "duplicate")
    with pytest.raises(psycopg.errors.RaiseException):
        with connect(stack.admin_dsn) as c:
            c.execute("UPDATE mapping_versions SET hash='forged'")
    assert not admit(stack.dsn, "cedar")["passed"]
    assert portfolio(stack.dsn)["included_companies"] == 0


def test_persisted_ready_flag_and_equal_row_count_do_not_bypass_reconciliation(stack):
    for m in company(stack):
        send(stack, m)
    assert admit(stack.dsn, "cedar")["passed"]
    with connect(stack.admin_dsn) as c:
        c.execute(
            "UPDATE customer_fields SET value=%s WHERE company='cedar' AND field='operations_state'",
            (Jsonb("complete"),),
        )
    gate = admit(stack.dsn, "cedar")
    assert not gate["passed"] and any("reconciliation_failed" in s for s in gate["issues"])
    with connect(stack.dsn) as c:
        c.execute(
            "UPDATE companies SET status='portfolio_ready',gate_hash='forged' WHERE id='cedar'"
        )
    assert portfolio(stack.dsn)["included_companies"] == 0


def test_incomplete_lifecycle_mapping_cannot_be_approved(stack):
    bad = mapping("hubspot")
    bad["sources"]["lmn"]["states"] = {}
    with pytest.raises(ValueError, match="explicit_lifecycle_normalization_required"):
        approve_mapping(stack.admin_dsn, "cedar", 2, bad, "reviewer", "invalid-states")
    assert admit(stack.dsn, "cedar")["mapping_version"] == 1
