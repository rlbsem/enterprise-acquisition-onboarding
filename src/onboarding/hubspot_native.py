"""Bounded HubSpot Service Key readback for the isolated Cedar test pair.

This module DOES NOT import or dispatch acquisition source events, create records,
claim company admission, or execute CRM writes. A successful native read merely
confirms the two known synthetic records and their explicit relationship.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

API_ORIGIN = "https://api.hubapi.com"
API_VERSION = "2026-09"
SERVICE_KEY_ENV = "HUBSPOT_SERVICE_KEY"


class HubSpotBoundaryError(RuntimeError):
    """Safe, finite failure reason; never disclose a credential or vendor body."""


@dataclass(frozen=True)
class CedarFixture:
    portal_id: str = "343801908"
    company_id: str = "229684469730"
    company_name: str = "Cedar Services — Synthetic Acceptance"
    contact_id: str = "288567817180"
    firstname: str = "Cedar"
    lastname: str = "Test Contact"
    email: str = "cedar.test.contact@example.com"


def _association_ids(record: dict, target_type: str) -> set[str]:
    associations = record.get("associations")
    if not isinstance(associations, dict):
        raise HubSpotBoundaryError("association_not_observed")
    link = associations.get(target_type)
    if not isinstance(link, dict) or not isinstance(link.get("results"), list):
        raise HubSpotBoundaryError("association_not_observed")
    paging = link.get("paging")
    if paging is not None and (not isinstance(paging, dict) or paging.get("next")):
        raise HubSpotBoundaryError("association_page_incomplete")
    ids: list[str] = []
    for row in link["results"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise HubSpotBoundaryError("association_schema_invalid")
        ids.append(row["id"])
    if len(ids) != len(set(ids)):
        raise HubSpotBoundaryError("duplicate_association")
    return set(ids)


class HubSpotReadOnlyReader:
    """Only GET is implemented; fixed API origin and a short bounded timeout."""

    def __init__(self, service_key: str, *, transport: httpx.BaseTransport | None = None):
        if not isinstance(service_key, str) or not service_key.strip():
            raise HubSpotBoundaryError("service_key_not_configured")
        self._http = httpx.Client(
            base_url=API_ORIGIN,
            headers={
                "Authorization": f"Bearer {service_key}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(7.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __enter__(self) -> HubSpotReadOnlyReader:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._http.close()

    def _get(self, object_type: str, record_id: str, properties: str, associations: str) -> dict:
        if object_type not in {"companies", "contacts"} or not record_id.isdecimal():
            raise HubSpotBoundaryError("unapproved_record_target")
        try:
            response = self._http.get(
                f"/crm/objects/{API_VERSION}/{object_type}/{record_id}",
                params={"properties": properties, "associations": associations},
            )
        except httpx.RequestError:
            raise HubSpotBoundaryError("provider_transport_unavailable") from None
        if response.status_code in {401, 403}:
            raise HubSpotBoundaryError("service_key_access_denied")
        if response.status_code == 404:
            raise HubSpotBoundaryError("source_record_not_found")
        if response.status_code == 429:
            raise HubSpotBoundaryError("provider_rate_limited_no_replay")
        if response.status_code != 200:
            raise HubSpotBoundaryError("provider_unexpected_status")
        try:
            body = response.json()
        except ValueError:
            raise HubSpotBoundaryError("provider_invalid_json") from None
        if (
            not isinstance(body, dict)
            or str(body.get("id")) != record_id
            or body.get("archived") is not False
            or not isinstance(body.get("properties"), dict)
        ):
            raise HubSpotBoundaryError("source_identity_or_shape_mismatch")
        return body

    def verify(self, fixture: CedarFixture = CedarFixture()) -> dict:
        company = self._get("companies", fixture.company_id, "name", "contacts")
        contact = self._get("contacts", fixture.contact_id, "firstname,lastname,email", "companies")

        if company["properties"].get("name") != fixture.company_name:
            raise HubSpotBoundaryError("company_name_diverged")
        for property_name in ("firstname", "lastname", "email"):
            if contact["properties"].get(property_name) != getattr(fixture, property_name):
                raise HubSpotBoundaryError("contact_field_diverged")

        if _association_ids(company, "contacts") != {fixture.contact_id}:
            raise HubSpotBoundaryError("company_contact_link_diverged")
        if _association_ids(contact, "companies") != {fixture.company_id}:
            raise HubSpotBoundaryError("contact_company_link_diverged")

        # Only the bounded synthetic source projection is emitted; raw provider
        # payloads, tokens, headers, URLs and unrelated CRM fields stay private.
        projection = {
            "fixture_company_id": fixture.company_id,
            "fixture_contact_id": fixture.contact_id,
            "fixture_company_name": fixture.company_name,
            "association": "verified_bidirectionally",
            "exact_expected_fields": "matched",
        }
        projection_sha256 = hashlib.sha256(
            json.dumps(
                projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return {
            "boundary": "native_hubspot_service_key_read_only",
            "api_version": API_VERSION,
            "expected_portal_id": fixture.portal_id,
            "verified_portal_id_by_api": False,
            "observed_at_utc": datetime.now(UTC).isoformat(),
            "checks": {
                "company_object": "matched",
                "contact_object": "matched",
                "contact_to_company": "matched",
                "company_to_contact": "matched",
            },
            "sanitized_projection_sha256": projection_sha256,
            "crm_writes": 0,
            "acquisition_admission_executed": False,
            "cdc_continuity_verified": False,
            "production_validation": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Explicitly authorize two GET requests to the isolated HubSpot fixture",
    )
    args = parser.parse_args(argv)
    if not args.read_only:
        parser.error("--read-only is required to make provider requests")
    secret = os.environ.get(SERVICE_KEY_ENV, "")
    try:
        with HubSpotReadOnlyReader(secret) as client:
            report = client.verify()
    except HubSpotBoundaryError as exc:
        print(json.dumps({"outcome": "blocked", "reason": str(exc)}))
        return 2
    print(json.dumps({"outcome": "verified", **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
