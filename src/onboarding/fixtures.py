"""Synthetic source-account snapshots, independent reviewed acquisition baselines and mappings."""

import copy
from uuid import NAMESPACE_URL, uuid5
from psycopg.types.json import Jsonb
from .contracts import digest, validate_contract
from .db import connect, lock


def canonical(company, number=1):
    return str(uuid5(NAMESPACE_URL, f"synthetic-admission:{company}:{number}"))


def mapping(style):
    if style == "hubspot":
        definitions = [
            (
                "hubspot",
                "crm",
                "companyId",
                "legalEntity",
                "version",
                {"companyName": "display_name", "dealStage": "sales_state"},
                {"dealStage": {"new": "prospect", "closedwon": "qualified"}},
            ),
            (
                "lmn",
                "operations",
                "clientId",
                "entity",
                "revision",
                {"jobState": "operations_state"},
                {
                    "jobState": {
                        "Planned": "scheduled",
                        "In Progress": "active",
                        "Complete": "complete",
                    }
                },
            ),
            (
                "quickbooks",
                "finance",
                "CustomerRef",
                "EntityRef",
                "SyncToken",
                {"AccountState": "finance_state"},
                {"AccountState": {"Review": "pending", "Reconciled": "verified"}},
            ),
        ]
    elif style == "salesforce":
        definitions = [
            (
                "salesforce",
                "crm",
                "Id",
                "LegalEntity",
                "Revision",
                {"Name": "display_name", "StageName": "sales_state"},
                {"StageName": {"Prospecting": "prospect", "Closed Won": "qualified"}},
            ),
            (
                "aspire",
                "operations",
                "account_key",
                "entity_code",
                "sequence",
                {"service_status": "operations_state"},
                {
                    "service_status": {
                        "QUEUED": "scheduled",
                        "SERVICING": "active",
                        "FINISHED": "complete",
                    }
                },
            ),
            (
                "netsuite",
                "finance",
                "internalId",
                "subsidiary",
                "recordVersion",
                {"controlStatus": "finance_state"},
                {"controlStatus": {"PENDING": "pending", "VERIFIED": "verified"}},
            ),
        ]
    else:
        definitions = [
            (
                "legacy-crm",
                "crm",
                "legacy_id",
                "legal_entity",
                "revision",
                {"legacy_name": "display_name", "status": "sales_state"},
                {"status": {"lead": "prospect", "won": "qualified"}},
            ),
            (
                "legacy-ops",
                "operations",
                "customer_key",
                "entity",
                "version",
                {"work_status": "operations_state"},
                {
                    "work_status": {
                        "scheduled": "scheduled",
                        "working": "active",
                        "done": "complete",
                    }
                },
            ),
            (
                "legacy-finance",
                "finance",
                "account_id",
                "entity",
                "version",
                {"verification": "finance_state"},
                {"verification": {"unreviewed": "pending", "checked": "verified"}},
            ),
        ]
    return {
        "schema_version": "admission-mapping.v1",
        "sources": {
            source: {
                "domain": domain,
                "id": identity,
                "entity": entity,
                "revision": rev,
                "fields": fields,
                "states": states,
            }
            for source, domain, identity, entity, rev, fields, states in definitions
        },
    }


COMPANIES = [
    ("cedar", "Cedar Services", "LE-CA-01", "2025-06-01", "hubspot"),
    ("meridian", "Meridian Facilities", "LE-US-02", "2026-02-01", "salesforce"),
    ("summit", "Summit Operator", "LE-CA-03", "2026-10-01", "legacy"),
]


def documents(company, style, entity):
    rule = mapping(style)
    result = []
    for index, (source, definition) in enumerate(rule["sources"].items()):
        body = {definition["id"]: "100", definition["entity"]: entity, definition["revision"]: 1}
        for field, target in definition["fields"].items():
            body[field] = (
                "Common Property Group"
                if target == "display_name"
                else list(definition["states"][field])[
                    -1 if definition["domain"] != "operations" else 1
                ]
            )
        result.append(
            {
                "schema_version": "source-customer.v1",
                "company": company,
                "source": source,
                "event_id": f"{source}-customer-100-v1",
                "mapping_version": 1,
                "observed_at": "2026-10-01T12:00:00+00:00",
                "data": body,
            }
        )
    return result


def approve_mapping(admin_dsn, company, version, body, reviewed_by, reference):
    """Trusted local governance operation, intentionally absent from intake API."""
    validate_contract(body)
    if not reviewed_by.strip() or not reference.strip():
        raise ValueError("review_identity_and_reference_required")
    with connect(admin_dsn) as c:
        lock(c, company)
        row = c.execute("SELECT active_mapping FROM companies WHERE id=%s", (company,)).fetchone()
        if row is None or version != (row["active_mapping"] or 0) + 1:
            raise ValueError("mapping_version_must_advance_by_one")
        c.execute(
            "INSERT INTO mapping_versions(company,version,body,hash,reviewed_by,review_reference) VALUES(%s,%s,%s,%s,%s,%s)",
            (company, version, Jsonb(body), digest(body), reviewed_by, reference),
        )
        c.execute(
            "UPDATE companies SET active_mapping=%s,status='staged',gate_hash=NULL WHERE id=%s",
            (version, company),
        )


def seed(admin_dsn):
    with connect(admin_dsn) as c:
        c.execute(
            "TRUNCATE audit,gate_runs,customer_fields,source_records,quarantine,deliveries,messages,baselines,crosswalks,customers,mapping_versions,systems,companies,platforms RESTART IDENTITY CASCADE"
        )
        c.execute("INSERT INTO platforms VALUES('harbor-platform','Harbor Platform - Synthetic')")
        for company, name, entity, acquired, style in COMPANIES:
            c.execute(
                "INSERT INTO companies(id,parent,name,legal_entity,acquired_on) VALUES(%s,'harbor-platform',%s,%s,%s)",
                (company, name, entity, acquired),
            )
            for source, rule in mapping(style)["sources"].items():
                c.execute(
                    "INSERT INTO systems VALUES(%s,%s,%s,%s)",
                    (company, source, rule["domain"], source + "-account-contract.v1"),
                )
    all_messages = []
    for company, _, entity, _, style in COMPANIES:
        contract = mapping(style)
        approve_mapping(
            admin_dsn,
            company,
            1,
            contract,
            "synthetic-governance-installer",
            "fixture-review.v1:" + company,
        )
        incoming = documents(company, style, entity)
        all_messages += incoming
        with connect(admin_dsn) as c:
            for i in range(1, 3 if company == "summit" else 2):
                c.execute(
                    "INSERT INTO customers VALUES(%s,%s,%s,%s)",
                    (company, entity, canonical(company, i), "Common Property Group"),
                )
            for message in incoming:
                source = message["source"]
                if not (company == "summit" and source == "legacy-crm"):
                    c.execute(
                        "INSERT INTO crosswalks VALUES(%s,%s,%s,'100',%s,1,%s)",
                        (
                            company,
                            entity,
                            source,
                            canonical(company),
                            "reviewed-contract-and-entity-match.v1",
                        ),
                    )
                c.execute(
                    "INSERT INTO baselines VALUES(%s,%s,1,%s,%s)",
                    (
                        company,
                        source,
                        Jsonb({"100": {"revision": 1, "hash": digest(message["data"])}}),
                        "independently-reviewed-source-inventory.v1:" + company + ":" + source,
                    ),
                )
    return copy.deepcopy(all_messages)
