"""PostgreSQL is authoritative; admission requires reviewed, exact source coverage."""

from datetime import datetime
from psycopg.types.json import Jsonb
from .contracts import Message, AUTHORITY, TRANSITIONS, digest, validate_contract
from .db import connect, lock


class Refused(ValueError):
    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.detail = detail or {}


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def normalize(raw, rule, entity):
    keys = {rule["id"], rule["entity"], rule["revision"], *rule["fields"]}
    require(set(raw) == keys, "unmapped_or_missing_source_fields")
    require(
        isinstance(raw[rule["id"]], str) and 0 < len(raw[rule["id"]].strip()) <= 100,
        "missing_source_identifier",
    )
    require(
        type(raw[rule["revision"]]) is int and raw[rule["revision"]] > 0, "invalid_source_revision"
    )
    require(raw[rule["entity"]] == entity, "incorrect_legal_entity")
    values = {}
    for original, target in rule["fields"].items():
        value = raw[original]
        require(isinstance(value, str) and 0 < len(value) <= 200, "invalid_source_value")
        if original in rule["states"]:
            require(value in rule["states"][original], "unmapped_lifecycle_state")
            value = rule["states"][original][value]
        require(AUTHORITY.get(target) == rule["domain"], "source_ownership_conflict")
        values[target] = value
    return raw[rule["id"]], raw[rule["revision"]], values


def audit(c, company, action, reference, detail):
    c.execute(
        "INSERT INTO audit(company,action,reference,detail) VALUES(%s,%s,%s,%s)",
        (company, action, str(reference), Jsonb(detail)),
    )


def quarantine(c, message, identifier, reason, detail=None):
    c.execute(
        "INSERT INTO quarantine(company,message_id,reason,detail) VALUES(%s,%s,%s,%s)",
        (message["company"], identifier, reason, Jsonb(detail or {})),
    )
    c.execute(
        "UPDATE companies SET status='held',gate_hash=NULL WHERE id=%s", (message["company"],)
    )
    audit(c, message["company"], "quarantined", identifier, {"reason": reason})


def apply_record(c, opco, message, identifier, allow_remap=False):
    company, source = message["company"], message["source"]
    changed = False
    mapping = c.execute(
        "SELECT * FROM mapping_versions WHERE company=%s AND version=%s",
        (company, message["mapping_version"]),
    ).fetchone()
    require(
        mapping is not None and opco["active_mapping"] == message["mapping_version"],
        "unapproved_or_inactive_mapping",
    )
    require(digest(mapping["body"]) == mapping["hash"], "mapping_content_conflict")
    rule = validate_contract(mapping["body"])["sources"].get(source)
    require(rule is not None, "source_not_in_approved_contract")
    identity, revision, values = normalize(message["data"], rule, opco["legal_entity"])
    links = c.execute(
        "SELECT * FROM crosswalks WHERE company=%s AND legal_entity=%s AND source=%s AND source_id=%s AND version=%s",
        (company, opco["legal_entity"], source, identity, message["mapping_version"]),
    ).fetchall()
    if len(links) != 1:
        name = values.get("display_name", "")
        candidates = [
            str(r["id"])
            for r in c.execute(
                "SELECT id FROM customers WHERE company=%s AND lower(name)=lower(%s)",
                (company, name),
            )
        ]
        raise Refused(
            "ambiguous_identity" if len(candidates) > 1 else "unmapped_identity",
            {"candidate_ids": candidates},
        )
    canonical = links[0]["canonical"]
    current = c.execute(
        "SELECT * FROM source_records WHERE company=%s AND source=%s AND source_id=%s",
        (company, source, identity),
    ).fetchone()
    replay = (
        current
        and revision == current["revision"]
        and current["raw"] == message["data"]
        and current["version"] == message["mapping_version"]
    )
    remap = bool(
        current
        and allow_remap
        and revision == current["revision"]
        and current["raw"] == message["data"]
    )
    if current and not replay and not remap:
        require(revision > current["revision"], "stale_or_conflicting_source_revision")
        require(revision == current["revision"] + 1, "source_revision_gap")
        require(
            datetime.fromisoformat(message["observed_at"]) >= current["observed_at"],
            "source_observation_regression",
        )
        require(current["canonical"] == canonical, "identity_reassignment_requires_migration")
    if not replay:
        for field, value in values.items():
            old = c.execute(
                "SELECT * FROM customer_fields WHERE company=%s AND canonical=%s AND field=%s",
                (company, canonical, field),
            ).fetchone()
            if old:
                require(
                    (old["source"], old["source_id"]) == (source, identity),
                    "conflicting_source_identity",
                )
                if field in TRANSITIONS and old["value"] != value:
                    require(
                        value in TRANSITIONS[field].get(old["value"], []),
                        "unsupported_lifecycle_transition",
                    )
        c.execute(
            "INSERT INTO source_records(company,source,source_id,canonical,revision,version,message_id,raw,raw_hash,normalized,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(company,source,source_id) DO UPDATE SET revision=excluded.revision,version=excluded.version,message_id=excluded.message_id,raw=excluded.raw,raw_hash=excluded.raw_hash,normalized=excluded.normalized,observed_at=excluded.observed_at",
            (
                company,
                source,
                identity,
                canonical,
                revision,
                message["mapping_version"],
                identifier,
                Jsonb(message["data"]),
                digest(message["data"]),
                Jsonb(values),
                message["observed_at"],
            ),
        )
        for field, value in values.items():
            c.execute(
                "INSERT INTO customer_fields VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(company,canonical,field) DO UPDATE SET value=excluded.value,source=excluded.source,source_id=excluded.source_id,revision=excluded.revision,message_id=excluded.message_id",
                (
                    company,
                    canonical,
                    field,
                    Jsonb(value),
                    source,
                    identity,
                    revision,
                    identifier,
                ),
            )
        changed = True
    return changed, "same_record_replay" if replay else "validated_against_reviewed_mapping"


def intake(dsn, document):
    message = Message.model_validate(document).model_dump()
    company, source = message["company"], message["source"]
    with connect(dsn) as c:
        lock(c, company)
        opco = c.execute("SELECT * FROM companies WHERE id=%s", (company,)).fetchone()
        require(opco is not None, "unknown_company")
        require(
            c.execute(
                "SELECT 1 FROM systems WHERE company=%s AND source=%s", (company, source)
            ).fetchone(),
            "unknown_source",
        )
        prior = c.execute(
            "SELECT * FROM messages WHERE company=%s AND source=%s AND event_id=%s",
            (company, source, message["event_id"]),
        ).fetchone()
        content = digest(message)
        if prior:
            exact = prior["hash"] == content and prior["body"] == message
            outcome = prior["status"] if exact else "quarantined"
            c.execute(
                "INSERT INTO deliveries(message_id,company,source,event_id,incoming,hash,outcome) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    prior["id"],
                    company,
                    source,
                    message["event_id"],
                    Jsonb(message),
                    content,
                    "duplicate" if exact else "identity_collision",
                ),
            )
            if not exact:
                quarantine(
                    c,
                    message,
                    prior["id"],
                    "event_identity_content_conflict",
                    {"incoming_hash": content},
                )
            audit(
                c,
                company,
                "duplicate_delivery" if exact else "identity_collision",
                prior["id"],
                {"incoming_hash": content},
            )
            return {
                "message_id": prior["id"],
                "status": outcome,
                "duplicate": exact,
                "reason": prior["reason"] if exact else "event_identity_content_conflict",
            }
        row = c.execute(
            "INSERT INTO messages(company,source,event_id,body,hash) VALUES(%s,%s,%s,%s,%s) RETURNING id",
            (company, source, message["event_id"], Jsonb(message), content),
        ).fetchone()
        identifier = row["id"]
        changed = False
        try:
            changed, reason = apply_record(c, opco, message, identifier)
            status = "accepted"
        except Refused as exc:
            status, reason = "quarantined", str(exc)
            quarantine(c, message, identifier, reason, exc.detail)
        c.execute(
            "UPDATE messages SET status=%s,reason=%s WHERE id=%s", (status, reason, identifier)
        )
        c.execute(
            "INSERT INTO deliveries(message_id,company,source,event_id,incoming,hash,outcome) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (identifier, company, source, message["event_id"], Jsonb(message), content, status),
        )
        if changed:
            c.execute("UPDATE companies SET status='staged',gate_hash=NULL WHERE id=%s", (company,))
        audit(
            c,
            company,
            status,
            identifier,
            {"reason": reason, "mapping_version": message["mapping_version"], "source": source},
        )
        return {"message_id": identifier, "status": status, "duplicate": False, "reason": reason}


def inspect_gate(c, company):
    opco = c.execute("SELECT * FROM companies WHERE id=%s", (company,)).fetchone()
    require(opco is not None, "unknown_company")
    mapping = c.execute(
        "SELECT * FROM mapping_versions WHERE company=%s AND version=%s",
        (company, opco["active_mapping"]),
    ).fetchone()
    issues = []
    coverage = []
    customer_domains = {}
    records = c.execute(
        "SELECT * FROM source_records WHERE company=%s ORDER BY source,source_id", (company,)
    ).fetchall()
    quarantined = c.execute(
        "SELECT q.id,q.reason,q.message_id FROM quarantine q LEFT JOIN quarantine_resolutions r ON r.quarantine_id=q.id WHERE q.company=%s AND r.quarantine_id IS NULL ORDER BY q.id",
        (company,),
    ).fetchall()
    if quarantined:
        issues.append("unresolved_quarantine")
    if not mapping or digest(mapping["body"]) != mapping["hash"]:
        issues.append("approved_mapping_required")
    else:
        contract = validate_contract(mapping["body"])
        for system in c.execute(
            "SELECT * FROM systems WHERE company=%s ORDER BY source", (company,)
        ):
            source = system["source"]
            rule = contract["sources"].get(source)
            baseline = c.execute(
                "SELECT * FROM baselines WHERE company=%s AND source=%s AND version=%s",
                (company, source, opco["active_mapping"]),
            ).fetchone()
            found = [r for r in records if r["source"] == source]
            observed = {
                r["source_id"]: {"revision": r["revision"], "hash": r["raw_hash"]} for r in found
            }
            expected = baseline["expected"] if baseline else None
            complete = expected is not None and expected == observed and bool(expected)
            coverage.append(
                {
                    "source": source,
                    "domain": system["domain"],
                    "expected": len(expected) if expected is not None else None,
                    "observed": len(found),
                    "complete": complete,
                    "review_reference": baseline["review_reference"] if baseline else None,
                }
            )
            if not complete:
                issues.append("source_coverage_gap:" + source)
            if not rule or rule["domain"] != system["domain"]:
                issues.append("source_contract_gap:" + source)
                continue
            for record in found:
                customer_domains.setdefault(str(record["canonical"]), set()).add(system["domain"])
                valid = (
                    record["version"] == opco["active_mapping"]
                    and digest(record["raw"]) == record["raw_hash"]
                )
                try:
                    _, _, normalized = normalize(record["raw"], rule, opco["legal_entity"])
                    valid = valid and normalized == record["normalized"]
                except Refused:
                    valid = False
                link = c.execute(
                    "SELECT canonical FROM crosswalks WHERE company=%s AND source=%s AND source_id=%s AND version=%s",
                    (company, source, record["source_id"], opco["active_mapping"]),
                ).fetchone()
                valid = valid and link is not None and link["canonical"] == record["canonical"]
                for field, value in record["normalized"].items():
                    target = c.execute(
                        "SELECT * FROM customer_fields WHERE company=%s AND canonical=%s AND field=%s",
                        (company, record["canonical"], field),
                    ).fetchone()
                    valid = (
                        valid
                        and target is not None
                        and (
                            target["value"],
                            target["source"],
                            target["source_id"],
                            target["revision"],
                            target["message_id"],
                        )
                        == (
                            value,
                            source,
                            record["source_id"],
                            record["revision"],
                            record["message_id"],
                        )
                    )
                if not valid:
                    issues.append(
                        "source_projection_reconciliation_failed:"
                        + source
                        + ":"
                        + record["source_id"]
                    )
        if set(contract["sources"]) != {r["source"] for r in coverage}:
            issues.append("source_inventory_contract_conflict")
    if not customer_domains or any(
        domains != {"crm", "operations", "finance"} for domains in customer_domains.values()
    ):
        issues.append("cross_domain_customer_coverage_gap")
    result = {
        "company": company,
        "mapping_version": opco["active_mapping"],
        "passed": not issues,
        "issues": sorted(set(issues)),
        "coverage": coverage,
        "quarantine": quarantined,
        "reconciled_customer_accounts": len(customer_domains),
    }
    fingerprint = {
        "mapping_hash": mapping["hash"] if mapping else None,
        "coverage": coverage,
        "records": [
            {
                k: str(r[k]) if k == "canonical" else r[k]
                for k in [
                    "source",
                    "source_id",
                    "canonical",
                    "revision",
                    "version",
                    "raw_hash",
                    "normalized",
                    "message_id",
                ]
            }
            for r in records
        ],
        "quarantine": quarantined,
        "issues": result["issues"],
    }
    result["input_hash"] = digest(fingerprint)
    return result


def admit(dsn, company):
    with connect(dsn) as c:
        lock(c, company)
        gate = inspect_gate(c, company)
        c.execute(
            "INSERT INTO gate_runs(company,input_hash,result) VALUES(%s,%s,%s)",
            (company, gate["input_hash"], Jsonb(gate)),
        )
        c.execute(
            "UPDATE companies SET status=%s,gate_hash=%s WHERE id=%s",
            (
                "portfolio_ready" if gate["passed"] else "held",
                gate["input_hash"] if gate["passed"] else None,
                company,
            ),
        )
        audit(
            c,
            company,
            "admission_passed" if gate["passed"] else "admission_blocked",
            gate["input_hash"],
            {"issues": gate["issues"]},
        )
    return gate


def portfolio(dsn):
    with connect(dsn) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        companies = []
        included = 0
        for opco in c.execute("SELECT * FROM companies ORDER BY id").fetchall():
            gate = inspect_gate(c, opco["id"])
            ready = (
                opco["status"] == "portfolio_ready"
                and gate["passed"]
                and gate["input_hash"] == opco["gate_hash"]
            )
            if ready:
                included += gate["reconciled_customer_accounts"]
            rows = c.execute(
                "SELECT source,source_id,canonical,revision,version,message_id,raw,normalized FROM source_records WHERE company=%s ORDER BY source,source_id",
                (opco["id"],),
            ).fetchall()
            companies.append(
                {
                    "id": opco["id"],
                    "parent": opco["parent"],
                    "brand": opco["name"],
                    "legal_entity": opco["legal_entity"],
                    "acquired_on": str(opco["acquired_on"]),
                    "status": opco["status"],
                    "included": ready,
                    "gate": gate,
                    "source_records": [{**r, "canonical": str(r["canonical"])} for r in rows],
                }
            )
        return {
            "schema_version": "portfolio-admission.v1",
            "synthetic": True,
            "native_vendor_execution": False,
            "metric_definition": "Scoped customer accounts in currently admitted companies; cross-brand party identity and statutory consolidation are not inferred.",
            "included_customer_accounts": included,
            "included_companies": sum(x["included"] for x in companies),
            "companies": companies,
        }
