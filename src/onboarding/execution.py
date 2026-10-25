"""Durable handoff intent, bounded attempts and independent remote proof before replay."""

import argparse
import json
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .contracts import digest
from .db import connect, lock
from .engine import require, Refused, inspect_gate, audit
from .receiver import record_for


def intended(c, company, canonical, identifiers):
    opco = c.execute("SELECT * FROM companies WHERE id=%s", (company,)).fetchone()
    require(opco, "unknown_company")
    gate = inspect_gate(c, company)
    require(
        opco["status"] == "portfolio_ready"
        and gate["passed"]
        and opco["gate_hash"] == gate["input_hash"],
        "current_admission_required",
    )
    sources = c.execute(
        "SELECT source,source_id,revision,version,message_id,raw_hash FROM source_records WHERE company=%s AND canonical=%s ORDER BY source",
        (company, canonical),
    ).fetchall()
    require(len(sources) == 3, "complete_customer_source_coverage_required")
    business = {}
    require(
        set(identifiers) == {"opportunity", "work_order", "finance_account"},
        "three_distinct_business_references_required",
    )
    for kind, identifier in identifiers.items():
        row = c.execute(
            "SELECT * FROM business_heads WHERE company=%s AND kind=%s AND record_id=%s",
            (company, kind, identifier),
        ).fetchone()
        require(
            row
            and str(row["canonical"]) == canonical
            and row["payload"]["mapping_version"] == opco["active_mapping"],
            "business_reference_stale_or_outside_scope",
        )
        latest = c.execute(
            "SELECT * FROM business_events WHERE company=%s AND payload->>'kind'=%s AND payload->>'record_id'=%s ORDER BY (payload->>'revision')::integer DESC,id DESC LIMIT 1",
            (company, kind, identifier),
        ).fetchone()
        require(
            latest and latest["status"] == "accepted" and latest["hash"] == row["hash"],
            "newer_business_fact_requires_review",
        )
        business[kind] = {
            "record_id": identifier,
            "source": row["payload"]["source"],
            "revision": row["revision"],
            "state": row["payload"]["state"],
            "hash": row["hash"],
            "event_id": row["event_id"],
        }
    work = c.execute(
        "SELECT payload FROM business_heads WHERE company=%s AND kind='work_order' AND record_id=%s",
        (company, identifiers["work_order"]),
    ).fetchone()["payload"]
    require(
        work["commercial_reference"] == identifiers["opportunity"],
        "work_order_commercial_parent_mismatch",
    )
    return {
        "schema_version": "onboarding-handoff.v1",
        "company": company,
        "legal_entity": opco["legal_entity"],
        "canonical": canonical,
        "mapping_version": opco["active_mapping"],
        "admission_hash": gate["input_hash"],
        "sources": sources,
        "business": business,
    }


def plan(config, company, canonical, identifiers):
    with connect(config["dsn"]) as c:
        lock(c, company)
        payload = intended(c, company, canonical, identifiers)
        effect = str(uuid5(NAMESPACE_URL, "onboarding-handoff:" + digest(payload)))
        payload["effect_id"] = effect
        old = c.execute("SELECT * FROM outbound WHERE effect_id=%s", (effect,)).fetchone()
        if old:
            require(
                old["payload"] == payload and old["hash"] == digest(payload),
                "outbound_identity_conflict",
            )
        else:
            c.execute(
                "INSERT INTO outbound(effect_id,company,payload,hash) VALUES(%s,%s,%s,%s)",
                (effect, company, Jsonb(payload), digest(payload)),
            )
            audit(c, company, "outbound_intent_committed", effect, {"hash": digest(payload)})
    return {"effect_id": effect, "duplicate": bool(old)}


def client(config, timeout=2):
    return httpx.Client(
        base_url=config["receiver"]["url"],
        headers={"X-Receiver-Token": config["receiver"]["token"]},
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
    )


def read_proof(remote, row):
    response = remote.get("/effects/" + str(row["effect_id"]), params={"company": row["company"]})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    proof = response.json()
    expected = record_for(row["payload"])
    require(
        proof.get("effect_id") == str(row["effect_id"])
        and proof.get("payload") == row["payload"]
        and proof.get("payload_hash") == row["hash"],
        "receiver_payload_proof_mismatch",
    )
    require(
        proof.get("record") == expected and proof.get("record_hash") == digest(expected),
        "receiver_record_contract_mismatch",
    )
    actual = remote.get("/records/" + expected["id"], params={"company": row["company"]})
    actual.raise_for_status()
    require(actual.json() == expected, "independent_receiver_readback_mismatch")
    return proof


def step(config, effect, timeout=2, respect_due=True, crash_marker=None):
    with psycopg.connect(config["dsn"], row_factory=dict_row, autocommit=True) as session:
        if not session.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,3)) AS held", (str(effect),)
        ).fetchone()["held"]:
            return "busy"
        company = None
        try:
            row = session.execute("SELECT * FROM outbound WHERE effect_id=%s", (effect,)).fetchone()
            require(row, "unknown_outbound_intent")
            company = row["company"]
            # The same lock as intake/review is held across this local dispatch.
            session.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (company,))

            def mark(state, detail, proof=None):
                with session.transaction():
                    session.execute(
                        "UPDATE outbound SET state=%s,detail=%s,proof=coalesce(%s,proof),next_at=clock_timestamp()+least(power(2,attempts),30)*interval '1 second' WHERE effect_id=%s",
                        (state, detail, Jsonb(proof) if proof else None, effect),
                    )
                    audit(session, company, "outbound_" + state, effect, {"reason": detail})
                return state

            try:
                with client(config, timeout) as remote:
                    proof = read_proof(remote, row)
                    if proof is None:
                        if row["state"] == "confirmed":
                            return mark("blocked", "previously_confirmed_receiver_effect_missing")
                        if row["state"] in ["blocked", "exhausted"]:
                            return row["state"]
                        if row["attempts"] >= 3:
                            return mark("exhausted", "dispatch_budget_exhausted")
                        if (
                            respect_due
                            and not session.execute(
                                "SELECT next_at<=clock_timestamp() AS due FROM outbound WHERE effect_id=%s",
                                (effect,),
                            ).fetchone()["due"]
                        ):
                            return row["state"]
                        with session.transaction():
                            references = {
                                k: v["record_id"] for k, v in row["payload"]["business"].items()
                            }
                            current = intended(
                                session, company, row["payload"]["canonical"], references
                            )
                            require(
                                {k: v for k, v in row["payload"].items() if k != "effect_id"}
                                == current,
                                "outbound_authority_changed",
                            )
                            session.execute(
                                "UPDATE outbound SET attempts=attempts+1 WHERE effect_id=%s",
                                (effect,),
                            )
                            session.execute(
                                "INSERT INTO outbound_attempts(company,effect_id,ordinal,stage,result) VALUES(%s,%s,%s,'dispatch','started')",
                                (company, effect, row["attempts"] + 1),
                            )
                        response = remote.post(
                            "/effects",
                            json=row["payload"],
                            headers={"Idempotency-Key": str(effect)},
                        )
                        if response.status_code in [409, 422]:
                            return mark("blocked", "receiver_rejected_contract")
                        response.raise_for_status()
                        if crash_marker:
                            Path(crash_marker).write_text(
                                "real_receiver_response_before_sender_confirmation"
                            )
                            while True:
                                time.sleep(0.1)
                        proof = read_proof(remote, row)
                        require(proof is not None, "ack_without_independent_receiver_proof")
                    return mark("confirmed", "independent_receipt_and_record", proof)
            except Refused as exc:
                return mark("blocked", str(exc))
            except (httpx.TransportError, httpx.HTTPStatusError):
                return mark("uncertain", "remote_outcome_unknown_readback_before_retry")
        finally:
            if company:
                session.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (company,))
            session.execute("SELECT pg_advisory_unlock(hashtextextended(%s,3))", (str(effect),))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--effect", required=True)
    p.add_argument("--crash-marker")
    a = p.parse_args()
    step(
        json.loads(Path(a.config).read_text(encoding="utf-8")),
        a.effect,
        crash_marker=a.crash_marker,
    )


if __name__ == "__main__":
    main()
