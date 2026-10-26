"""Versioned source-owned financial facts; reporting never writes business systems."""

from datetime import date, datetime
from typing import Literal
from pydantic import Field, model_validator
from psycopg.types.json import Jsonb
from .contracts import Closed, digest
from .db import connect, lock
from .engine import require, Refused, audit

KINDS = {
    "booking",
    "invoice",
    "invoice_line",
    "erp_posting",
    "credit",
    "payment",
    "allocation",
    "intercompany_charge",
    "intercompany_acceptance",
}


class Financial(Closed):
    schema_version: Literal["financial-fact.v1"] = "financial-fact.v1"
    company: str
    legal_entity: str
    source: str
    owner: Literal["crm", "finance"]
    source_customer_id: str = "100"
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal[
        "booking",
        "invoice",
        "invoice_line",
        "erp_posting",
        "credit",
        "payment",
        "allocation",
        "intercompany_charge",
        "intercompany_acceptance",
    ]
    source_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    mapping_version: int = Field(ge=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount_minor: int = Field(ge=-1000000000000, le=1000000000000)
    transaction_date: str
    observed_at: str
    invoice_id: str | None = None
    payment_id: str | None = None
    booking_id: str | None = None
    counterparty_company: str | None = None
    counterparty_entity: str | None = None
    link_id: str | None = None

    @model_validator(mode="after")
    def shape(self):
        day = date.fromisoformat(self.transaction_date)
        seen = datetime.fromisoformat(self.observed_at)
        if seen.utcoffset() is None or day > seen.date():
            raise ValueError("dated_observation_required")
        return self


def latest(c, company, kind, source_id):
    row = c.execute(
        "SELECT body FROM financial_events WHERE company=%s AND body->>'kind'=%s AND body->>'source_id'=%s AND status='accepted' ORDER BY (body->>'revision')::int DESC LIMIT 1",
        (company, kind, source_id),
    ).fetchone()
    return row["body"] if row else None


def ingest(dsn, data):
    b = Financial.model_validate(data).model_dump()
    with connect(dsn) as c:
        lock(c, b["company"])
        old = c.execute(
            "SELECT * FROM financial_events WHERE company=%s AND source=%s AND event_id=%s",
            (b["company"], b["source"], b["event_id"]),
        ).fetchone()
        if old:
            require(old["body"] == b, "financial_event_content_conflict")
            return {
                "id": old["id"],
                "status": old["status"],
                "reason": old["reason"],
                "duplicate": True,
            }
        try:
            opco = c.execute("SELECT * FROM companies WHERE id=%s", (b["company"],)).fetchone()
            require(opco and b["legal_entity"] == opco["legal_entity"], "financial_entity_mismatch")
            require(b["mapping_version"] == opco["active_mapping"], "financial_mapping_stale")
            system = c.execute(
                "SELECT domain FROM systems WHERE company=%s AND source=%s",
                (b["company"], b["source"]),
            ).fetchone()
            domain = "crm" if b["kind"] == "booking" else "finance"
            require(
                system and system["domain"] == domain == b["owner"],
                "financial_source_authority_denied",
            )
            require(b["currency"] == "USD", "financial_currency_policy_mismatch")
            require(
                b["amount_minor"] != 0 and (b["amount_minor"] > 0 or b["kind"] == "erp_posting"),
                "invalid_financial_amount",
            )
            link = c.execute(
                "SELECT canonical FROM crosswalks WHERE company=%s AND source=%s AND source_id=%s AND version=%s",
                (b["company"], b["source"], b["source_customer_id"], b["mapping_version"]),
            ).fetchone()
            require(link, "financial_identity_unresolved")
            required = {
                "booking": set(),
                "invoice": set(),
                "invoice_line": {"invoice_id"},
                "erp_posting": {"invoice_id"},
                "credit": {"invoice_id"},
                "payment": set(),
                "allocation": {"invoice_id", "payment_id"},
                "intercompany_charge": {
                    "invoice_id",
                    "counterparty_company",
                    "counterparty_entity",
                    "link_id",
                },
                "intercompany_acceptance": {
                    "invoice_id",
                    "counterparty_company",
                    "counterparty_entity",
                    "link_id",
                },
            }[b["kind"]]
            actual = {
                k
                for k in [
                    "invoice_id",
                    "payment_id",
                    "booking_id",
                    "counterparty_company",
                    "counterparty_entity",
                    "link_id",
                ]
                if b[k] is not None
            }
            allowed = required | (
                {"booking_id", "counterparty_company", "counterparty_entity"}
                if b["kind"] == "invoice"
                else set()
            )
            require(required <= actual <= allowed, "financial_reference_shape_invalid")
            require(
                (b["counterparty_company"] is None) == (b["counterparty_entity"] is None),
                "counterparty_entity_required",
            )
            if b["counterparty_company"]:
                other = c.execute(
                    "SELECT legal_entity FROM companies WHERE id=%s", (b["counterparty_company"],)
                ).fetchone()
                require(
                    other
                    and other["legal_entity"] == b["counterparty_entity"]
                    and b["counterparty_entity"] != b["legal_entity"],
                    "counterparty_entity_mismatch",
                )
            if b["invoice_id"]:
                issuer = (
                    b["counterparty_company"]
                    if b["kind"] == "intercompany_acceptance"
                    else b["company"]
                )
                parent = latest(c, issuer, "invoice", b["invoice_id"])
                require(
                    parent and parent["currency"] == b["currency"],
                    "invoice_reference_missing_or_currency_mismatch",
                )
                require(
                    datetime.fromisoformat(parent["observed_at"])
                    <= datetime.fromisoformat(b["observed_at"]),
                    "financial_reference_not_yet_observed",
                )
            if b["booking_id"]:
                require(
                    latest(c, b["company"], "booking", b["booking_id"]), "booking_reference_missing"
                )
            if b["payment_id"]:
                parent = latest(c, b["company"], "payment", b["payment_id"])
                require(
                    parent and parent["currency"] == b["currency"],
                    "payment_reference_missing_or_currency_mismatch",
                )
                require(
                    datetime.fromisoformat(parent["observed_at"])
                    <= datetime.fromisoformat(b["observed_at"]),
                    "financial_reference_not_yet_observed",
                )
            previous = latest(c, b["company"], b["kind"], b["source_id"])
            if previous:
                require(
                    b["revision"] == previous["revision"] + 1, "financial_revision_not_consecutive"
                )
                require(
                    datetime.fromisoformat(b["observed_at"])
                    >= datetime.fromisoformat(previous["observed_at"]),
                    "financial_observation_regression",
                )
                require(
                    all(
                        b[k] == previous[k]
                        for k in [
                            "source",
                            "owner",
                            "legal_entity",
                            "currency",
                            "source_customer_id",
                            "invoice_id",
                            "payment_id",
                            "booking_id",
                            "counterparty_company",
                            "counterparty_entity",
                            "link_id",
                        ]
                    ),
                    "financial_identity_or_relationship_change",
                )
            else:
                require(b["revision"] == 1, "initial_financial_revision_required")
            status, reason = "accepted", "source_owned_financial_fact"
        except Refused as exc:
            status, reason = "rejected", str(exc)
        row = c.execute(
            "INSERT INTO financial_events(company,source,event_id,body,hash,status,reason) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (b["company"], b["source"], b["event_id"], Jsonb(b), digest(b), status, reason),
        ).fetchone()
        audit(
            c, b["company"], "financial_" + status, row["id"], {"reason": reason, "kind": b["kind"]}
        )
    return {"id": row["id"], "status": status, "reason": reason, "duplicate": False}
