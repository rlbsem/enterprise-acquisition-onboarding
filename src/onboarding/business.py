"""Commercial, work-order and finance-account facts remain separate source-owned contracts."""

from typing import Literal
from pydantic import Field
from psycopg.types.json import Jsonb
from .contracts import Closed, digest
from .db import connect, lock
from .engine import require, Refused, audit

DOMAINS = {
    "opportunity": ("crm", {"won"}),
    "work_order": ("operations", {"created", "completed"}),
    "finance_account": ("finance", {"verified"}),
}


class Business(Closed):
    schema_version: Literal["business-fact.v1"] = "business-fact.v1"
    company: str
    legal_entity: str
    source: str
    source_customer_id: str
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal["opportunity", "work_order", "finance_account"]
    record_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    mapping_version: int = Field(ge=1)
    state: str
    commercial_reference: str | None = None


def ingest(dsn, body):
    body = Business.model_validate(body).model_dump()
    with connect(dsn) as c:
        lock(c, body["company"])
        company = body["company"]
        old = c.execute(
            "SELECT * FROM business_events WHERE company=%s AND source=%s AND event_id=%s",
            (company, body["source"], body["event_id"]),
        ).fetchone()
        if old:
            require(old["payload"] == body, "business_event_content_conflict")
            return {
                "status": old["status"],
                "duplicate": True,
                "id": old["id"],
                "reason": old["reason"],
            }
        try:
            opco = c.execute("SELECT * FROM companies WHERE id=%s", (company,)).fetchone()
            require(opco, "unknown_company")
            require(
                body["legal_entity"] == opco["legal_entity"]
                and body["mapping_version"] == opco["active_mapping"],
                "business_scope_or_mapping_stale",
            )
            system = c.execute(
                "SELECT domain FROM systems WHERE company=%s AND source=%s",
                (company, body["source"]),
            ).fetchone()
            require(
                system and system["domain"] == DOMAINS[body["kind"]][0],
                "business_source_authority_denied",
            )
            require(body["state"] in DOMAINS[body["kind"]][1], "unsupported_business_state")
            link = c.execute(
                "SELECT canonical FROM crosswalks WHERE company=%s AND source=%s AND source_id=%s AND version=%s",
                (company, body["source"], body["source_customer_id"], body["mapping_version"]),
            ).fetchone()
            require(link, "business_identity_unresolved")
            if body["kind"] == "work_order":
                parent = c.execute(
                    "SELECT * FROM business_heads WHERE company=%s AND kind='opportunity' AND record_id=%s",
                    (company, body["commercial_reference"]),
                ).fetchone()
                require(
                    parent
                    and parent["canonical"] == link["canonical"]
                    and parent["payload"]["state"] == "won",
                    "commercial_parent_required",
                )
            else:
                require(body["commercial_reference"] is None, "unexpected_commercial_reference")
            current = c.execute(
                "SELECT * FROM business_heads WHERE company=%s AND kind=%s AND record_id=%s",
                (company, body["kind"], body["record_id"]),
            ).fetchone()
            if current:
                require(
                    body["revision"] == current["revision"] + 1
                    and current["canonical"] == link["canonical"],
                    "business_revision_or_identity_conflict",
                )
                require(
                    not (
                        current["payload"]["state"] == "completed" and body["state"] != "completed"
                    ),
                    "business_state_regression",
                )
            else:
                require(body["revision"] == 1, "initial_business_revision_required")
            status, reason = "accepted", "source_owned_business_fact"
        except Refused as exc:
            status, reason = "rejected", str(exc)
        row = c.execute(
            "INSERT INTO business_events(company,source,event_id,payload,hash,status,reason) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (company, body["source"], body["event_id"], Jsonb(body), digest(body), status, reason),
        ).fetchone()
        if status == "accepted":
            c.execute(
                "INSERT INTO business_heads VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(company,kind,record_id) DO UPDATE SET revision=excluded.revision,event_id=excluded.event_id,payload=excluded.payload,hash=excluded.hash",
                (
                    company,
                    body["kind"],
                    body["record_id"],
                    link["canonical"],
                    body["revision"],
                    row["id"],
                    Jsonb(body),
                    digest(body),
                ),
            )
        audit(c, company, "business_" + status, row["id"], {"kind": body["kind"], "reason": reason})
    return {"status": status, "duplicate": False, "id": row["id"], "reason": reason}


def fixtures(company, entity, sources, version=1):
    result = []
    for kind, source, state in zip(DOMAINS, sources, ["won", "created", "verified"], strict=True):
        result.append(
            {
                "schema_version": "business-fact.v1",
                "company": company,
                "legal_entity": entity,
                "source": source,
                "source_customer_id": "100",
                "event_id": company + "-" + kind + "-v1",
                "kind": kind,
                "record_id": company + "-" + kind,
                "revision": 1,
                "mapping_version": version,
                "state": state,
                "commercial_reference": company + "-opportunity" if kind == "work_order" else None,
            }
        )
    return result
