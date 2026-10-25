"""Executed review, resnapshot and independently receipted handoff; synthetic local only."""

import argparse
import copy
import json
from pathlib import Path
import httpx
from .sandbox import Sandbox
from .fixtures import canonical
from .contracts import digest
from .db import connect
from .business import fixtures
from .execution import step, client


def post(stack, path, body, role="reviewer", message=None, expected=200):
    kwargs = (
        {"company": message["company"], "source": message["source"]} if role == "source" else {}
    )
    with stack.client(role, **kwargs) as c:
        r = c.post(path, json=body)
    if r.status_code != expected:
        raise AssertionError((path, r.status_code, r.text))
    return r.json()


def send(stack, message):
    return post(stack, "/v1/intake", message, "source", message)


def reviewed(stack, company="summit"):
    with stack.client("reviewer") as c:
        r = c.get("/v1/reviews/" + company)
        r.raise_for_status()
        return r.json()


def coverage(snapshot, contract):
    result = {s: {} for s in contract["sources"]}
    for row in snapshot["source_evidence"]:
        rule = contract["sources"][row["source"]]
        data = row["body"]["data"]
        result[row["source"]][data[rule["id"]]] = {
            "revision": data[rule["revision"]],
            "hash": digest(data),
        }
    return result


def resolve_identity(stack):
    view = reviewed(stack)
    q = next(
        q for q in view["quarantine"] if q["reason"] == "ambiguous_identity" and not q["resolution"]
    )
    body = {
        "quarantine_id": q["id"],
        "candidate": canonical("summit"),
        "reason": "Reviewed scoped customer references; preserve the second candidate as a separate account.",
    }
    first = post(stack, "/v1/reviews/summit/identity", body)["review_id"]
    post(
        stack,
        f"/v1/reviews/summit/{first}/decision",
        {
            "result": "rejected",
            "reason": "Original source references require another explicit review.",
        },
    )
    rejected_replay = post(
        stack,
        f"/v1/reviews/summit/{first}/decision",
        {"result": "approved", "reason": "Attempt to overwrite rejection"},
        expected=409,
    )
    identifier = post(stack, "/v1/reviews/summit/identity", body)["review_id"]
    decision = post(
        stack,
        f"/v1/reviews/summit/{identifier}/decision",
        {
            "result": "approved",
            "reason": "Selected the existing scoped canonical account; no customer merge.",
        },
    )
    return {
        "rejected_review": first,
        "rejected_replay": rejected_replay,
        "approved_review": identifier,
        "decision": decision,
    }


def valid_handoff(stack, company="cedar"):
    messages = [m for m in stack.messages if m["company"] == company]
    for m in messages:
        send(stack, m)
    if company == "summit":
        resolve_identity(stack)
    post(stack, "/v1/admission/" + company, {}, "controller")
    entity = {"cedar": "LE-CA-01", "summit": "LE-CA-03"}[company]
    for body in fixtures(company, entity, [m["source"] for m in messages]):
        post(stack, "/v1/business", body, "source", body)
    result = post(
        stack,
        "/v1/handoff/" + company,
        {
            "canonical": canonical(company),
            "references": {
                kind: company + "-" + kind
                for kind in ["opportunity", "work_order", "finance_account"]
            },
        },
        "controller",
    )
    return result["effect_id"]


def set_fault(stack, effect, modes):
    r = httpx.post(
        stack.receiver["url"] + "/test/faults",
        headers={"X-Receiver-Token": stack.receiver_injector},
        json={"effect_id": effect, "modes": modes},
        trust_env=False,
    )
    r.raise_for_status()


def execute(stack):
    for m in stack.messages:
        send(stack, m)
    original_gate = post(stack, "/v1/admission/summit", {}, "controller")
    identity = resolve_identity(stack)
    identity_gate = post(stack, "/v1/admission/summit", {}, "controller")
    assert identity_gate["passed"]
    original = next(
        m for m in stack.messages if m["company"] == "summit" and m["source"] == "legacy-ops"
    )
    wrong = {
        **original,
        "event_id": "p2-wrong-entity",
        "data": {**original["data"], "entity": "LE-US-02"},
    }
    invalid = send(stack, wrong)
    assert invalid["reason"] == "incorrect_legal_entity"
    q = next(q for q in reviewed(stack)["quarantine"] if q["reason"] == "incorrect_legal_entity")
    denied = post(
        stack,
        "/v1/reviews/summit/identity",
        {
            "quarantine_id": q["id"],
            "candidate": canonical("summit"),
            "reason": "Cannot approve the wrong entity",
        },
        expected=409,
    )
    invalid_gate = post(stack, "/v1/admission/summit", {}, "controller")
    assert not invalid_gate["passed"]
    corrected = {
        **original,
        "event_id": "p2-corrected-entity",
        "observed_at": "2026-10-02T12:00:00+00:00",
        "data": {**original["data"], "version": 2},
    }
    correction = send(stack, corrected)
    assert correction["status"] == "accepted"
    post(
        stack,
        "/v1/reviews/summit/correction",
        {
            "quarantine_id": q["id"],
            "message_id": correction["message_id"],
            "reason": "New version from the authorized operations source corrects entity scope.",
        },
    )
    closed = {
        **corrected,
        "event_id": "p2-new-local-state",
        "observed_at": "2026-10-03T12:00:00+00:00",
        "data": {**corrected["data"], "version": 3, "work_status": "closed"},
    }
    assert send(stack, closed)["reason"] == "unmapped_lifecycle_state"
    view = reviewed(stack)
    contract = copy.deepcopy(view["contract"])
    contract["sources"]["legacy-ops"]["states"]["work_status"]["closed"] = "complete"
    expected = coverage(view, contract)
    incomplete = {k: v for k, v in expected.items() if k != "legacy-finance"}
    blocked_coverage = post(
        stack,
        "/v1/reviews/summit/mapping",
        {
            "contract": contract,
            "coverage": incomplete,
            "reason": "Incomplete coverage must not pass",
        },
        expected=409,
    )
    proposal = post(
        stack,
        "/v1/reviews/summit/mapping",
        {
            "contract": contract,
            "coverage": expected,
            "reason": "Explicit source inventory and closed-state normalization reviewed.",
        },
    )["review_id"]
    mapping_decision = post(
        stack,
        f"/v1/reviews/summit/{proposal}/decision",
        {
            "result": "approved",
            "reason": "Re-evaluate every current source with complete reviewed coverage.",
        },
    )
    current_gate = post(stack, "/v1/admission/summit", {}, "controller")
    assert current_gate["passed"] and current_gate["mapping_version"] == 2
    bodies = fixtures("summit", "LE-CA-03", ["legacy-crm", "legacy-ops", "legacy-finance"], 2)
    bodies[1]["state"] = "completed"
    for body in bodies:
        assert post(stack, "/v1/business", body, "source", body)["status"] == "accepted"
    handoff = {
        "canonical": canonical("summit"),
        "references": {
            kind: "summit-" + kind for kind in ["opportunity", "work_order", "finance_account"]
        },
    }
    effect = post(stack, "/v1/handoff/summit", handoff, "controller")["effect_id"]
    set_fault(stack, effect, ["lost_ack"])
    uncertain = step(stack.sender_config, effect, timeout=0.2)
    assert uncertain == "uncertain"
    with connect(stack.receiver_admin) as c:
        committed_before = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
    confirmed = step(stack.sender_config, effect)
    assert confirmed == "confirmed"
    duplicate_plan = post(stack, "/v1/handoff/summit", handoff, "controller")
    assert duplicate_plan["duplicate"]
    with connect(stack.dsn) as c:
        payload = c.execute(
            "SELECT payload FROM outbound WHERE effect_id=%s", (effect,)
        ).fetchone()["payload"]
    with client(stack.sender_config) as c:
        duplicate = c.post("/effects", json=payload, headers={"Idempotency-Key": effect})
        duplicate.raise_for_status()
        conflict = c.post(
            "/effects",
            json={**payload, "admission_hash": "0" * 64},
            headers={"Idempotency-Key": effect},
        )
        assert conflict.status_code == 409
    with connect(stack.dsn) as c:
        control = {
            t: c.execute(
                "SELECT * FROM " + t + " WHERE company='summit' ORDER BY " + order
            ).fetchall()
            for t, order in {
                "reviews": "created_at",
                "review_decisions": "decided_at",
                "quarantine_resolutions": "quarantine_id",
                "source_record_history": "id",
                "business_events": "id",
                "outbound": "effect_id",
                "outbound_attempts": "id",
                "messages": "id",
                "quarantine": "id",
                "mapping_versions": "version",
                "baselines": "version,source",
                "crosswalks": "version,source,source_id",
                "gate_runs": "id",
                "audit": "id",
            }.items()
        }
    with connect(stack.receiver_admin) as c:
        remote = {
            t: c.execute("SELECT * FROM " + t + " ORDER BY id").fetchall()
            for t in ["effects", "records", "requests"]
        }
    with stack.client("viewer") as c:
        portfolio = c.get("/v1/portfolio").json()
    assert len(remote["effects"]) == 1 and len(remote["records"]) == 1
    return {
        "lane": "actual_local_postgresql_http_review_resnapshot_and_receiver",
        "synthetic": True,
        "native_vendor_calls": 0,
        "A_identity": {
            "before_passed": original_gate["passed"],
            "after_passed": identity_gate["passed"],
            **identity,
        },
        "B_wrong_entity": {
            "identity_approval_denied": denied,
            "admission_passed": invalid_gate["passed"],
            "source_correction": correction,
        },
        "C_resnapshot": {
            "incomplete_rejected": blocked_coverage,
            "decision": mapping_decision,
            "final_gate": current_gate,
        },
        "D_E_delivery": {
            "effect_id": effect,
            "uncertain": uncertain,
            "independently_observed_effects_before_recovery": committed_before,
            "recovered": confirmed,
            "duplicate_plan": duplicate_plan["duplicate"],
            "conflicting_payload_http_status": conflict.status_code,
            "final_effects": len(remote["effects"]),
        },
        "control": control,
        "receiver": remote,
        "portfolio": portfolio,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    out = Path(a.output)
    if out.exists():
        raise ValueError("fresh_output_required")
    with Sandbox(a.workspace) as stack:
        result = execute(stack)
    result["owned_resources_cleaned"] = True
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(result, indent=2, default=str) + "\n").encode())
    print(
        json.dumps(
            {
                "resolved_acquisition": "summit",
                "mapping_version": 2,
                "verified_receiver_effects": 1,
                "native_vendor_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
