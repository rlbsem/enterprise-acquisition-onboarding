"""Explicit review decisions; original source messages and exceptions never change."""

import json
from uuid import uuid4
from psycopg.types.json import Jsonb
from .contracts import digest, validate_contract
from .db import connect, lock
from .engine import require, normalize, audit, inspect_gate


def freeze(value):
    return json.loads(json.dumps(value, default=str))


def context(c, company):
    return digest(
        freeze(
            {
                "mapping": c.execute(
                    "SELECT active_mapping FROM companies WHERE id=%s", (company,)
                ).fetchone(),
                "messages": c.execute(
                    "SELECT id,hash,status FROM messages WHERE company=%s ORDER BY id", (company,)
                ).fetchall(),
                "sources": c.execute(
                    "SELECT * FROM source_records WHERE company=%s ORDER BY source,source_id",
                    (company,),
                ).fetchall(),
                "links": c.execute(
                    "SELECT * FROM crosswalks WHERE company=%s ORDER BY source,source_id,version",
                    (company,),
                ).fetchall(),
                "quarantine": c.execute(
                    "SELECT id,reason FROM quarantine WHERE company=%s ORDER BY id", (company,)
                ).fetchall(),
                "resolutions": c.execute(
                    "SELECT * FROM quarantine_resolutions WHERE company=%s ORDER BY quarantine_id",
                    (company,),
                ).fetchall(),
            }
        )
    )


def latest(c, company):
    opco = c.execute("SELECT * FROM companies WHERE id=%s", (company,)).fetchone()
    require(opco, "unknown_company")
    contract = c.execute(
        "SELECT body FROM mapping_versions WHERE company=%s AND version=%s",
        (company, opco["active_mapping"]),
    ).fetchone()["body"]
    groups = {}
    for row in c.execute(
        "SELECT * FROM messages WHERE company=%s ORDER BY id", (company,)
    ).fetchall():
        body = row["body"]
        rule = contract["sources"].get(row["source"])
        data = body["data"]
        if not rule or body["mapping_version"] > opco["active_mapping"]:
            continue
        identity, revision = data.get(rule["id"]), data.get(rule["revision"])
        if not isinstance(identity, str) or not identity or type(revision) is not int:
            continue
        k = (row["source"], identity)
        prior = groups.get(k)
        if prior is None or revision > prior[0]:
            groups[k] = (revision, digest(data), row)
        elif revision == prior[0] and digest(data) != prior[1]:
            groups[k] = (revision, None, prior[2])
    require(all(item[1] is not None for item in groups.values()), "competing_source_revision")
    return opco, contract, [x[2] for x in groups.values()]


def inventory(c, company, contract):
    opco, old, rows = latest(c, company)
    coverage = {source: {} for source in old["sources"]}
    require(set(contract["sources"]) == set(old["sources"]), "source_inventory_change_out_of_scope")
    for source in old["sources"]:
        require(
            all(
                contract["sources"][source][k] == old["sources"][source][k]
                for k in ["id", "entity", "revision", "domain"]
            ),
            "source_identity_rekey_requires_migration",
        )
    for row in rows:
        source = row["source"]
        rule = contract["sources"][source]
        identity, revision, _ = normalize(row["body"]["data"], rule, opco["legal_entity"])
        coverage[source][identity] = {"revision": revision, "hash": digest(row["body"]["data"])}
    require(all(coverage.values()), "incomplete_source_inventory")
    return opco, rows, coverage


def inspect(dsn, company):
    with connect(dsn) as c:
        conflict = None
        try:
            opco, contract, rows = latest(c, company)
        except ValueError as exc:
            conflict = str(exc)
            opco = c.execute("SELECT * FROM companies WHERE id=%s", (company,)).fetchone()
            require(opco, "unknown_company")
            contract = c.execute(
                "SELECT body FROM mapping_versions WHERE company=%s AND version=%s",
                (company, opco["active_mapping"]),
            ).fetchone()["body"]
            rows = c.execute(
                "SELECT * FROM messages WHERE company=%s ORDER BY id", (company,)
            ).fetchall()
        quarantines = c.execute(
            "SELECT q.*,m.body,m.hash,r.kind AS resolution FROM quarantine q JOIN messages m ON m.id=q.message_id LEFT JOIN quarantine_resolutions r ON r.quarantine_id=q.id WHERE q.company=%s ORDER BY q.id",
            (company,),
        ).fetchall()
        return freeze(
            {
                "company": company,
                "mapping_version": opco["active_mapping"],
                "contract": contract,
                "source_conflict": conflict,
                "source_evidence": rows,
                "quarantine": quarantines,
                "customers": c.execute(
                    "SELECT * FROM customers WHERE company=%s ORDER BY id", (company,)
                ).fetchall(),
                "reviews": c.execute(
                    "SELECT r.*,d.result,d.actor AS decision_actor FROM reviews r LEFT JOIN review_decisions d ON d.review_id=r.id WHERE r.company=%s ORDER BY r.created_at",
                    (company,),
                ).fetchall(),
            }
        )


def propose_identity(dsn, company, quarantine_id, candidate, actor, reason):
    with connect(dsn) as c:
        lock(c, company)
        q = c.execute(
            "SELECT q.*,m.body,m.hash FROM quarantine q JOIN messages m ON m.id=q.message_id WHERE q.id=%s AND q.company=%s",
            (quarantine_id, company),
        ).fetchone()
        require(q and q["reason"] == "ambiguous_identity", "identity_resolution_not_applicable")
        require(
            candidate in q["detail"].get("candidate_ids", []), "candidate_not_in_original_review"
        )
        opco, contract, rows = latest(c, company)
        require(any(r["id"] == q["message_id"] for r in rows), "source_review_stale")
        normalize(q["body"]["data"], contract["sources"][q["body"]["source"]], opco["legal_entity"])
        require(
            not c.execute(
                "SELECT 1 FROM quarantine_resolutions WHERE quarantine_id=%s", (quarantine_id,)
            ).fetchone(),
            "already_resolved",
        )
        identifier = str(uuid4())
        payload = {
            "quarantine_id": quarantine_id,
            "candidate": candidate,
            "message_id": q["message_id"],
            "message_hash": q["hash"],
            "mapping_version": opco["active_mapping"],
        }
        c.execute(
            "INSERT INTO reviews(id,company,kind,actor,reason,context_hash,payload) VALUES(%s,%s,'identity',%s,%s,%s,%s)",
            (identifier, company, actor, reason, context(c, company), Jsonb(payload)),
        )
        audit(c, company, "identity_proposed", identifier, {"actor": actor, "payload": payload})
    return identifier


def propose_mapping(dsn, company, contract, coverage, actor, reason):
    try:
        validate_contract(contract)
    except ValueError as exc:
        from .engine import Refused

        raise Refused("invalid_mapping_contract") from exc
    with connect(dsn) as c:
        lock(c, company)
        opco, rows, actual = inventory(c, company, contract)
        require(coverage == actual, "reviewed_coverage_mismatch")
        identifier = str(uuid4())
        payload = {
            "previous_version": opco["active_mapping"],
            "version": opco["active_mapping"] + 1,
            "contract": contract,
            "coverage": coverage,
            "message_ids": [r["id"] for r in rows],
        }
        c.execute(
            "INSERT INTO reviews(id,company,kind,actor,reason,context_hash,payload) VALUES(%s,%s,'mapping',%s,%s,%s,%s)",
            (identifier, company, actor, reason, context(c, company), Jsonb(payload)),
        )
        audit(
            c,
            company,
            "mapping_proposed",
            identifier,
            {"actor": actor, "version": payload["version"]},
        )
    return identifier


def resolve_corrected(dsn, company, quarantine_id, message_id, actor, reason):
    with connect(dsn) as c:
        lock(c, company)
        q = c.execute(
            "SELECT q.*,m.body FROM quarantine q JOIN messages m ON m.id=q.message_id WHERE q.id=%s AND q.company=%s",
            (quarantine_id, company),
        ).fetchone()
        require(
            q and q["reason"] in ["incorrect_legal_entity", "unmapped_lifecycle_state"],
            "corrected_source_resolution_not_applicable",
        )
        opco, contract, rows = latest(c, company)
        new = next((r for r in rows if r["id"] == message_id), None)
        require(
            new and new["status"] == "accepted" and new["source"] == q["body"]["source"],
            "current_accepted_correction_required",
        )
        rule = contract["sources"][new["source"]]
        old = q["body"]["data"]
        data = new["body"]["data"]
        require(
            data[rule["id"]] == old.get(rule["id"])
            and data[rule["revision"]] > old.get(rule["revision"], 0),
            "higher_revision_same_identity_required",
        )
        normalize(data, rule, opco["legal_entity"])
        c.execute(
            "INSERT INTO quarantine_resolutions(quarantine_id,company,kind,actor,reason,source_message_id,detail) VALUES(%s,%s,'source_corrected',%s,%s,%s,%s)",
            (
                quarantine_id,
                company,
                actor,
                reason,
                message_id,
                Jsonb({"original_message_id": q["message_id"], "revision": data[rule["revision"]]}),
            ),
        )
        c.execute("UPDATE companies SET status='staged',gate_hash=NULL WHERE id=%s", (company,))
        audit(
            c,
            company,
            "source_correction_reviewed",
            quarantine_id,
            {"actor": actor, "message_id": message_id},
        )
    return {"resolved": quarantine_id, "original_preserved": True}


def decide(dsn, company, identifier, result, actor, reason):
    from .engine import apply_record

    require(result in ["approved", "rejected"], "invalid_review_decision")
    with connect(dsn) as c:
        lock(c, company)
        review = c.execute(
            "SELECT * FROM reviews WHERE id=%s AND company=%s", (identifier, company)
        ).fetchone()
        require(review, "review_not_found_in_scope")
        require(
            not c.execute(
                "SELECT 1 FROM review_decisions WHERE review_id=%s", (identifier,)
            ).fetchone(),
            "review_already_decided",
        )
        require(review["context_hash"] == context(c, company), "review_context_stale")
        payload = review["payload"]
        c.execute(
            "INSERT INTO review_decisions VALUES(%s,%s,%s,%s,%s,clock_timestamp())",
            (identifier, company, actor, result, reason),
        )
        if result == "approved" and review["kind"] == "identity":
            opco, contract, rows = latest(c, company)
            row = next(r for r in rows if r["id"] == payload["message_id"])
            message = row["body"]
            rule = contract["sources"][message["source"]]
            identity, revision, _ = normalize(message["data"], rule, opco["legal_entity"])
            candidate = c.execute(
                "SELECT id FROM customers WHERE company=%s AND legal_entity=%s AND id=%s",
                (company, opco["legal_entity"], payload["candidate"]),
            ).fetchone()
            require(candidate, "candidate_outside_legal_entity")
            c.execute(
                "INSERT INTO crosswalks VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    company,
                    opco["legal_entity"],
                    message["source"],
                    identity,
                    payload["candidate"],
                    opco["active_mapping"],
                    "identity-review:" + str(identifier),
                ),
            )
            apply_record(c, opco, message, row["id"])
            c.execute(
                "INSERT INTO quarantine_resolutions(quarantine_id,company,review_id,kind,actor,reason,source_message_id,detail) VALUES(%s,%s,%s,'identity_approved',%s,%s,%s,%s)",
                (
                    payload["quarantine_id"],
                    company,
                    identifier,
                    actor,
                    reason,
                    row["id"],
                    Jsonb(
                        {
                            "candidate": payload["candidate"],
                            "source_revision": revision,
                            "message_hash": row["hash"],
                        }
                    ),
                ),
            )
        elif result == "approved":
            opco, rows, coverage = inventory(c, company, payload["contract"])
            require(
                coverage == payload["coverage"]
                and [r["id"] for r in rows] == payload["message_ids"],
                "resnapshot_inventory_changed",
            )
            c.execute(
                "INSERT INTO mapping_versions(company,version,body,hash,reviewed_by,review_reference) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    company,
                    payload["version"],
                    Jsonb(payload["contract"]),
                    digest(payload["contract"]),
                    actor,
                    "mapping-review:" + str(identifier),
                ),
            )
            c.execute(
                "INSERT INTO crosswalks SELECT company,legal_entity,source,source_id,canonical,%s,%s FROM crosswalks WHERE company=%s AND version=%s",
                (
                    payload["version"],
                    "mapping-review:" + str(identifier),
                    company,
                    payload["previous_version"],
                ),
            )
            for source, expected in coverage.items():
                c.execute(
                    "INSERT INTO baselines VALUES(%s,%s,%s,%s,%s)",
                    (
                        company,
                        source,
                        payload["version"],
                        Jsonb(expected),
                        "source-review:" + str(identifier),
                    ),
                )
            c.execute(
                "UPDATE companies SET active_mapping=%s WHERE id=%s", (payload["version"], company)
            )
            opco = {**opco, "active_mapping": payload["version"]}
            for row in rows:
                message = {**row["body"], "mapping_version": payload["version"]}
                apply_record(c, opco, message, row["id"], allow_remap=True)
                for q in c.execute(
                    "SELECT q.id FROM quarantine q LEFT JOIN quarantine_resolutions r ON r.quarantine_id=q.id WHERE q.message_id=%s AND q.reason='unmapped_lifecycle_state' AND r.quarantine_id IS NULL",
                    (row["id"],),
                ).fetchall():
                    c.execute(
                        "INSERT INTO quarantine_resolutions(quarantine_id,company,review_id,kind,actor,reason,source_message_id,detail) VALUES(%s,%s,%s,'mapping_revalidated',%s,%s,%s,%s)",
                        (
                            q["id"],
                            company,
                            identifier,
                            actor,
                            reason,
                            row["id"],
                            Jsonb({"mapping_version": payload["version"]}),
                        ),
                    )
        if result == "approved":
            c.execute("UPDATE companies SET status='staged',gate_hash=NULL WHERE id=%s", (company,))
            gate = inspect_gate(c, company)
            c.execute(
                "INSERT INTO gate_runs(company,input_hash,result) VALUES(%s,%s,%s)",
                (company, gate["input_hash"], Jsonb(gate)),
            )
        audit(
            c,
            company,
            "review_" + result,
            identifier,
            {"actor": actor, "reason": reason, "kind": review["kind"]},
        )
    return {"review_id": str(identifier), "result": result, "admitted": False}
