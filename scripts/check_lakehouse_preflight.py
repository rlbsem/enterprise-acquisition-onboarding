"""Offline hash, source and boundary checks over recorded management API reads."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RECORD = Path("docs/evidence/lakehouse-preflight/2026-11-14")


def check_content(report):
    assert report["schema"] == "lakehouse-readonly-preflight.v1"
    assert report["boundary"] == "actual_databricks_management_api_reads_no_compute"
    assert (report["cloud"], report["region"], report["pricing_tier"], report["compute_mode"]) == (
        "aws",
        "us-west-2",
        "PREMIUM",
        "SERVERLESS",
    )
    for field in [
        "active_identity_verified",
        "workspace_admin_membership_observed",
        "unity_catalog_assignment_observed",
        "managed_workspace_catalog_observed",
        "jobs_api_read_succeeded",
        "principal_api_read_succeeded",
    ]:
        assert report[field] is True
    for field in [
        "native_jobs_execution_verified",
        "separate_principal_authorization_verified",
        "catalog_write_permissions_verified",
        "billing_plan_credits_or_expiry_verified_by_these_apis",
    ]:
        assert report[field] is False
    assert (
        report["resources_created"]
        == report["compute_starts_requested"]
        == report["sql_statements_submitted"]
        == 0
    )
    assert (
        report["jobs_returned_bounded_page"] == report["existing_service_principals_observed"] == 0
    )
    assert report["warehouses"] == [
        {
            "serverless": True,
            "size": "Small",
            "state": "STOPPED",
            "active_clusters": 0,
            "auto_stop_mins": 10,
        }
    ]
    assert report["predictive_optimization_inherited_enabled"] is True
    assert report["native_gate"] == {
        "eligible_for_separately_authorized_bounded_pilot": False,
        "reasons": [
            "exact_trial_expiry_or_observation_missing",
            "no_out_of_pocket_billing_boundary_unconfirmed",
            "applicable_costs_not_established",
            "bounded_trial_consumption_not_approved",
        ],
        "launch_performed": False,
    }
    assert report["cli_version"] == "1.26.0"
    receipts = report["management_read_receipts"]
    assert [r["operation"] for r in receipts] == [
        "identity",
        "workspace",
        "metastore",
        "catalogs",
        "jobs",
        "warehouses",
        "principals",
    ]
    assert all(
        r["method"] == "GET"
        and r["return_code"] == 0
        and re.fullmatch(r"[0-9a-f]{64}", r["private_response_sha256"])
        for r in receipts
    )
    assert set(report["target_binding"]) == {"account_sha256", "workspace_sha256", "host_sha256"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in report["target_binding"].values())


def verify(root=ROOT):
    folder = root / RECORD
    manifest = json.loads((folder / "artifact-sha256.json").read_bytes())
    actual = {
        p.name
        for p in folder.iterdir()
        if p.is_file() and p.name not in {"README.md", "artifact-sha256.json"}
    }
    assert set(manifest) == actual
    for name, expected in manifest.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected, name
    report = json.loads((folder / "management-reads.json").read_bytes())
    check_content(report)
    source = subprocess.check_output(
        ["git", "show", report["source_revision"] + ":src/onboarding/lakehouse_preflight.py"],
        cwd=root,
    )
    assert hashlib.sha256(source).hexdigest() == report["source_sha256"]
    original = json.loads((folder / "historical-sha256.json").read_bytes())
    assert len(original) == 228
    for name, expected in original.items():
        path = (root / name).resolve()
        assert path.is_relative_to(root.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    return {
        "native_management_reads": len(report["management_read_receipts"]),
        "native_data_execution": False,
        "launch_gate": "blocked",
        "historical_files_unchanged": len(original),
        "artifact_hashes": len(manifest),
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
