import hashlib
import json
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

AUTHORITY = {
    "display_name": "crm",
    "sales_state": "crm",
    "operations_state": "operations",
    "finance_state": "finance",
}
TRANSITIONS = {
    "sales_state": {"prospect": ["qualified"], "qualified": []},
    "operations_state": {
        "scheduled": ["active", "complete"],
        "active": ["complete"],
        "complete": [],
    },
    "finance_state": {"pending": ["verified"], "verified": []},
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Message(Closed):
    schema_version: Literal["source-customer.v1"] = "source-customer.v1"
    company: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    source: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    event_id: str = Field(min_length=1, max_length=100)
    mapping_version: int = Field(ge=1)
    observed_at: str
    data: dict

    @model_validator(mode="after")
    def time(self):
        if datetime.fromisoformat(self.observed_at).utcoffset() is None:
            raise ValueError("aware_source_observation_required")
        return self


def validate_contract(contract):
    if (
        set(contract) != {"schema_version", "sources"}
        or contract["schema_version"] != "admission-mapping.v1"
    ):
        raise ValueError("unsupported_mapping_contract")
    domains = []
    for source, rule in contract["sources"].items():
        if set(rule) != {"domain", "id", "entity", "revision", "fields", "states"}:
            raise ValueError("closed_source_mapping_required")
        domain = rule["domain"]
        domains.append(domain)
        owned = {field for field, owner in AUTHORITY.items() if owner == domain}
        if (
            len(rule["fields"]) != len(set(rule["fields"].values()))
            or set(rule["fields"].values()) != owned
        ):
            raise ValueError("conflicting_or_incomplete_field_mapping")
        if any(AUTHORITY.get(target) != domain for target in rule["fields"].values()):
            raise ValueError("field_ownership_conflict:" + source)
        if not set(rule["states"]).issubset(rule["fields"]):
            raise ValueError("unmapped_state_contract")
        state_fields = {field for field, target in rule["fields"].items() if target in TRANSITIONS}
        if set(rule["states"]) != state_fields:
            raise ValueError("explicit_lifecycle_normalization_required")
        source_fields = [rule["id"], rule["entity"], rule["revision"], *rule["fields"]]
        if len(source_fields) != len(set(source_fields)):
            raise ValueError("overlapping_source_identity_fields")
        for local, states in rule["states"].items():
            target = rule["fields"][local]
            if (
                target not in TRANSITIONS
                or not states
                or not set(states.values()).issubset(TRANSITIONS[target])
            ):
                raise ValueError("invalid_normalized_lifecycle_contract")
        if any(
            not isinstance(v, str) or not v for v in [rule["id"], rule["entity"], rule["revision"]]
        ):
            raise ValueError("source_identity_fields_required")
    if sorted(domains) != ["crm", "finance", "operations"]:
        raise ValueError("three_independent_domains_required")
    return contract
