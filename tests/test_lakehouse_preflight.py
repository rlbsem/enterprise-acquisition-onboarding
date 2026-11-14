"""Offline contract and spending-gate negatives; no native data execution."""

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from onboarding.lakehouse_preflight import (
    PreflightRefused,
    collect,
    commands,
    native_gate,
    project,
)

NOW = datetime(2026, 11, 13, 20, tzinfo=UTC)
TARGET = {
    "host": "https://dbc-unit-test.cloud.databricks.com",
    "account_id": "00000000-0000-0000-0000-000000000001",
    "workspace_id": "123",
    "region": "us-west-2",
}


def observed():
    return {
        "identity": {
            "active": True,
            "userName": "private@example.com",
            "groups": [{"display": "admins"}],
        },
        "workspace": {
            "account_id": TARGET["account_id"],
            "workspace_id": 123,
            "deployment_name": "dbc-unit-test",
            "aws_region": "us-west-2",
            "pricing_tier": "PREMIUM",
            "compute_mode": "SERVERLESS",
            "workspace_status": "RUNNING",
        },
        "metastore": {"workspace_id": 123, "metastore_id": "private-metastore"},
        "catalogs": [
            {
                "name": "workspace",
                "catalog_type": "MANAGED_CATALOG",
                "storage_location": "private-storage",
                "effective_predictive_optimization_flag": {"value": "ENABLE"},
            }
        ],
        "jobs": [],
        "warehouses": [
            {
                "enable_serverless_compute": True,
                "cluster_size": "Small",
                "state": "STOPPED",
                "num_clusters": 0,
                "auto_stop_mins": 10,
                "jdbc_url": "private-jdbc",
            }
        ],
        "principals": [],
    }


def gate_inputs():
    report = project(TARGET, observed(), NOW.isoformat())
    owner = {
        "target_binding": report["target_binding"],
        "observed_at_utc": NOW.isoformat(),
        "expires_at_utc": "2026-11-27T20:00:00+00:00",
        "trial_active": True,
        "currency": "USD",
        "payment_arrangement": "express_no_payment_method",
        "remaining_credit_usd": "400",
        "approved_trial_consumption_usd": "10",
    }
    cost = {
        "target_binding": report["target_binding"],
        "pricing_status": "applicable_rates_verified",
        "region": "us-west-2",
        "pricing_tier": "PREMIUM",
        "planned_total_usd": "8",
    }
    return report, owner, cost


def test_readonly_projection_keeps_unproved_permissions_unproved():
    report = project(TARGET, observed(), NOW.isoformat())
    encoded = json.dumps(report)
    for private in [
        "private@example.com",
        "private-storage",
        "private-jdbc",
        "private-metastore",
        TARGET["host"],
        TARGET["account_id"],
    ]:
        assert private not in encoded
    assert (
        report["resources_created"]
        == report["compute_starts_requested"]
        == report["sql_statements_submitted"]
        == 0
    )
    assert report["predictive_optimization_inherited_enabled"]
    for field in [
        "native_jobs_execution_verified",
        "separate_principal_authorization_verified",
        "catalog_write_permissions_verified",
        "billing_plan_credits_or_expiry_verified_by_these_apis",
    ]:
        assert report[field] is False
    gate = native_gate(report, {}, {}, NOW)
    assert not gate["eligible_for_separately_authorized_bounded_pilot"]
    assert not gate["launch_performed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "http://unsafe.example"),
        ("host", TARGET["host"] + "/?token=bad"),
        ("account_id", "../other"),
        ("workspace_id", "123;start"),
        ("region", "wrong"),
    ],
)
def test_target_rejects_unapproved_origins_and_command_injection(field, value):
    with pytest.raises(PreflightRefused):
        commands({**TARGET, field: value})


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("identity", "active", False),
        ("workspace", "account_id", "different"),
        ("workspace", "workspace_id", 124),
        ("workspace", "aws_region", "us-east-1"),
        ("metastore", "workspace_id", 124),
        ("workspace", "compute_mode", "CLASSIC"),
    ],
)
def test_native_observation_divergence_blocks(section, key, value):
    inputs = observed()
    inputs[section][key] = value
    with pytest.raises(PreflightRefused):
        project(TARGET, inputs, NOW.isoformat())


def test_complete_bounded_pilot_gate_is_not_execution_authorization():
    report, owner, cost = gate_inputs()
    result = native_gate(report, owner, cost, NOW)
    assert result == {
        "eligible_for_separately_authorized_bounded_pilot": True,
        "reasons": [],
        "launch_performed": False,
    }


def test_owner_remaining_days_supports_a_conservative_window_not_an_exact_expiry():
    report, owner, cost = gate_inputs()
    owner.pop("expires_at_utc")
    owner.update(reported_remaining_days=14, payment_arrangement="no_payment_method_linked")
    assert native_gate(report, owner, cost, NOW)["eligible_for_separately_authorized_bounded_pilot"]
    # The window never overrides explicit consumption approval.
    owner.pop("approved_trial_consumption_usd")
    result = native_gate(report, owner, cost, NOW)
    assert not result["eligible_for_separately_authorized_bounded_pilot"]
    assert "bounded_trial_consumption_not_approved" in result["reasons"]


@pytest.mark.parametrize("remaining", [1, "14", True, 15])
def test_relative_expiry_rejects_ambiguous_or_insufficient_days(remaining):
    report, owner, cost = gate_inputs()
    owner.pop("expires_at_utc")
    owner["reported_remaining_days"] = remaining
    assert not native_gate(report, owner, cost, NOW)[
        "eligible_for_separately_authorized_bounded_pilot"
    ]


@pytest.mark.parametrize(
    "location,key,value",
    [
        (0, "unity_catalog_assignment_observed", False),
        (1, "trial_active", False),
        (1, "currency", "CAD"),
        (1, "payment_arrangement", "unknown"),
        (1, "payment_arrangement", "aws_marketplace"),
        (1, "expires_at_utc", "14 days from now"),
        (1, "expires_at_utc", "2026-11-13T22:00:00+00:00"),
        (1, "observed_at_utc", "2026-11-11T20:00:00+00:00"),
        (1, "observed_at_utc", "2026-11-14T20:00:00+00:00"),
        (1, "approved_trial_consumption_usd", None),
        (1, "remaining_credit_usd", "NaN"),
        (1, "approved_trial_consumption_usd", "Infinity"),
        (1, "remaining_credit_usd", "25"),
        (1, "target_binding", {"wrong": "workspace"}),
        (2, "planned_total_usd", "11"),
        (2, "planned_total_usd", "-1"),
        (2, "region", "us-east-2"),
        (2, "pricing_status", "estimate_only"),
        (2, "target_binding", {"wrong": "workspace"}),
    ],
)
def test_spending_gate_rejects_missing_stale_or_unapproved_evidence(location, key, value):
    inputs = list(gate_inputs())
    inputs[location][key] = value
    result = native_gate(*inputs, NOW)
    assert not result["eligible_for_separately_authorized_bounded_pilot"]
    assert result["reasons"] and not result["launch_performed"]


def test_collector_only_invokes_allowlisted_read_commands_and_scrubs_inherited_auth(
    tmp_path, monkeypatch
):
    binary = tmp_path / "cli.exe"
    binary.write_bytes(b"test-double-not-a-vendor-client")
    responses = iter(observed().values())
    calls = []
    monkeypatch.setenv("DATABRICKS_TOKEN", "synthetic-must-not-be-used")
    monkeypatch.setenv("DATABRICKS_HOST", "https://unapproved.example")

    def run(args, **kwargs):
        assert "DATABRICKS_TOKEN" not in kwargs["env"]
        assert "DATABRICKS_HOST" not in kwargs["env"]
        assert kwargs["env"]["DATABRICKS_AUTH_STORAGE"] == "secure"
        calls.append(args[1:])
        if args[1] == "version":
            return SimpleNamespace(returncode=0, stdout="Databricks CLI v1.26.0\n")
        return SimpleNamespace(returncode=0, stdout=json.dumps(next(responses)))

    monkeypatch.setattr("onboarding.lakehouse_preflight.subprocess.run", run)
    report = collect(str(binary), "private-config", "workspace-reader", "account-reader", TARGET)
    assert len(report["management_read_receipts"]) == 7
    assert calls[1:] == [
        [
            *args,
            "--profile",
            "account-reader" if name == "workspace" else "workspace-reader",
            "--output",
            "json",
        ]
        for name, args in commands(TARGET).items()
    ]
    assert report["compute_starts_requested"] == 0


def test_cli_failures_do_not_disclose_vendor_logs_or_credentials(tmp_path, monkeypatch):
    def run(args, **kwargs):
        if args[1] == "version":
            return SimpleNamespace(returncode=0, stdout="Databricks CLI v1.26.0")
        return SimpleNamespace(returncode=1, stdout="sensitive-body", stderr="sensitive-diagnostic")

    monkeypatch.setattr("onboarding.lakehouse_preflight.subprocess.run", run)
    with pytest.raises(PreflightRefused, match="^management_read_failed_identity$"):
        collect(str(tmp_path / "cli"), "private", "w", "a", copy.deepcopy(TARGET))
