"""Offline verification of recorded native reads; never requests vendor access."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = Path("docs/evidence/hubspot-native/2026-11-08")
INITIAL = "cdb0d5bb4155466cbda5fedef46aa6503ac60f00"
ACCEPTED = "0e6a5b6ae0ef0cf05b75f636e9ab5676499b1cf4"
COMPANY, CONTACT = "229684469730", "288567817180"


def read(path: Path):
    return json.loads(path.read_bytes())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_content(folder: Path) -> dict:
    """Check observations independently of the application's provider parser."""
    provenance = read(folder / "provenance.json")
    assert provenance["initial_source_revision"] == INITIAL
    assert provenance["accepted_source_revision"] == ACCEPTED
    assert provenance["scope_boundary"] == [
        "crm.objects.companies.read",
        "crm.objects.contacts.read",
    ]
    boundaries = provenance["boundaries"]
    assert boundaries == {
        "native_cli_executed": True,
        "independent_native_reads_executed": True,
        "native_api_crm_writes": 0,
        "separately_authorized_ui_repair": True,
        "portal_id_authenticated_by_object_api": False,
        "acquisition_admission": False,
        "cdc_continuity": False,
        "production_validation": False,
        "connector_used_for_this_acceptance": False,
    }
    final = folder / "attempt-04"
    source = read(final / "source.json")
    cli = read(final / "cli.json")
    acceptance = read(final / "acceptance.json")
    observed = read(final / "independent-responses.json")
    assert source["source_revision"] == acceptance["source_revision"] == ACCEPTED
    assert cli["command"] == "python -m onboarding.hubspot_native --read-only"
    assert cli["returncode"] == 0 and cli["stderr_present"] is False
    result = cli["result"]
    assert result["outcome"] == acceptance["outcome"] == "verified"
    assert result["boundary"] == "native_hubspot_service_key_read_only"
    assert result["api_version"] == "2026-09"
    assert result["expected_portal_id"] == "343801908"
    assert result["checks"] == dict.fromkeys(
        ["company_object", "company_to_contact", "contact_object", "contact_to_company"],
        "matched",
    )
    for field in [
        "acquisition_admission_executed",
        "cdc_continuity_verified",
        "production_validation",
    ]:
        assert result[field] is False
    assert result["verified_portal_id_by_api"] is acceptance["verified_portal_id_by_api"] is False
    assert result["crm_writes"] == acceptance["crm_writes"] == 0
    assert acceptance["cli_verified"] is True
    assert (
        acceptance["native_cli_requests_expected"]
        == acceptance["independent_requests_observed"]
        == 2
    )
    assert acceptance["independent_checks"] == dict.fromkeys(
        [
            "company_id",
            "contact_id",
            "neither_archived",
            "company_properties",
            "contact_properties",
            "company_to_contact",
            "contact_to_company",
            "no_repeated_typed_links",
            "no_paged_association",
        ],
        True,
    )
    assert len(observed) == 2
    expected = [
        (
            "companies",
            COMPANY,
            "name",
            "contacts",
            CONTACT,
            {"name": "Cedar Services — Synthetic Acceptance"},
        ),
        (
            "contacts",
            CONTACT,
            "firstname,lastname,email",
            "companies",
            COMPANY,
            {
                "firstname": "Cedar",
                "lastname": "Test Contact",
                "email": "cedar.test.contact@example.com",
            },
        ),
    ]
    for row, (kind, identity, properties, target, linked, values) in zip(
        observed, expected, strict=True
    ):
        assert row["method"] == "GET" and row["status_code"] == 200
        assert row["path"] == f"/crm/objects/2026-09/{kind}/{identity}"
        assert row["properties_requested"] == properties and row["associations_requested"] == target
        assert re.fullmatch(r"[0-9a-f-]{36}", row["correlation_id"])
        assert re.fullmatch(r"[0-9a-f]{64}", row["response_body_sha256"])
        actual = row["source"]
        assert actual["id"] == identity and actual["archived"] is False
        assert actual["properties"] == values
        assert actual["association_paging_present"] is False
        links = actual["association_results"]
        pairs = {(r["id"], r["type"]) for r in links}
        assert len(links) == len(pairs) and {r["id"] for r in links} == {linked}
        label = "company_to_contact" if kind == "companies" else "contact_to_company"
        assert pairs == {(linked, label), (linked, label + "_unlabeled")}
        assert datetime.fromisoformat(cli["completed_at_utc"]) <= datetime.fromisoformat(
            row["observed_at_utc"]
        )
        assert datetime.fromisoformat(row["observed_at_utc"]) <= datetime.fromisoformat(
            acceptance["completed_at_utc"]
        )
    projection = {
        "fixture_company_id": observed[0]["source"]["id"],
        "fixture_contact_id": observed[1]["source"]["id"],
        "fixture_company_name": observed[0]["source"]["properties"]["name"],
        "association": "verified_bidirectionally",
        "exact_expected_fields": "matched",
    }
    assert (
        sha(
            json.dumps(
                projection, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        == result["sanitized_projection_sha256"]
    )
    for attempt in ["attempt-01", "attempt-02"]:
        original = read(folder / attempt / "cli.json")
        assert original["result"] == {
            "outcome": "blocked",
            "reason": "provider_transport_unavailable",
        }
        assert all(
            "status_code" not in r for r in read(folder / attempt / "independent-responses.json")
        )
    failed = read(folder / "attempt-03" / "cli.json")
    assert failed["result"] == {"outcome": "blocked", "reason": "duplicate_association"}
    earlier = read(folder / "attempt-03" / "independent-responses.json")
    assert all(r["status_code"] == 200 for r in earlier)
    assert {r["id"] for r in earlier[1]["source"]["association_results"]} == {
        COMPANY,
        "229742254061",
    }
    repair = read(folder / "fixture-repair.json")
    assert repair["contact_id"] == CONTACT and repair["portal_id"] == "343801908"
    assert repair["removed_company_association"] == "229742254061"
    assert repair["retained_company_association"] == repair["primary_company_after"] == COMPANY
    assert repair["primary_selection_required_by_ui"] is True
    assert repair["record_deletions"] == repair["property_edits_requested"] == 0
    assert repair["key_or_scope_changes"] is False
    return {
        "native_acceptance": "verified",
        "independent_http_reads": 2,
        "retained_failed_attempts": 3,
    }


def verify(root: Path = ROOT) -> dict:
    folder = root / RECORD
    inventory = read(folder / "artifact-sha256.json")
    actual = {
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and p.name not in {"artifact-sha256.json", "README.md"}
    }
    assert set(inventory) == actual, "native evidence inventory mismatch"
    for name, fingerprint in inventory.items():
        assert sha((folder / name).read_bytes()) == fingerprint, name
    provenance = read(folder / "provenance.json")
    historical = provenance["historical_sha256"]
    assert len(historical) == 140
    for name, fingerprint in historical.items():
        path = (root / name).resolve()
        assert path.is_relative_to(root.resolve())
        assert sha(path.read_bytes()) == fingerprint, name
    for index in range(1, 5):
        source = read(folder / f"attempt-{index:02}" / "source.json")
        revision = ACCEPTED if index == 4 else INITIAL
        assert source["source_revision"] == revision
        for name, fingerprint in source["source_sha256"].items():
            data = subprocess.check_output(["git", "show", revision + ":" + name], cwd=root)
            assert sha(data) == fingerprint, "executed source fingerprint mismatch: " + name
    report = check_content(folder)
    report.update(artifact_hashes=len(inventory), historical_files_unchanged=len(historical))
    return report


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
