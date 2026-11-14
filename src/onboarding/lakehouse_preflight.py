"""GET-only Databricks feasibility capture; no compute, SQL, or provisioning calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

CLI_VERSION = "1.26.0"
SOURCE_BASE = Path(__file__).resolve().parents[2]


class PreflightRefused(RuntimeError):
    """Finite safe failure code, without raw CLI logs or authentication data."""


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("timezone_required")
    return result.astimezone(UTC)


def target_check(target: dict) -> None:
    url = urlsplit(target["host"])
    if (
        url.scheme != "https"
        or not re.fullmatch(r"[a-z0-9-]+\.cloud\.databricks\.com", url.netloc)
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
        or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", target["account_id"])
        or not re.fullmatch(r"[0-9]+", str(target["workspace_id"]))
        or not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]+", target["region"])
    ):
        raise PreflightRefused("invalid_pinned_target")


def commands(target: dict) -> dict[str, tuple[str, ...]]:
    """The complete remote request allowlist. No arbitrary command passthrough."""
    target_check(target)
    return {
        "identity": ("current-user", "me"),
        "workspace": ("account", "workspaces", "get", str(target["workspace_id"])),
        "metastore": ("metastores", "current"),
        "catalogs": ("catalogs", "list"),
        "jobs": ("jobs", "list", "--limit", "5"),
        "warehouses": ("warehouses", "list"),
        "principals": ("service-principals", "list"),
    }


def project(target: dict, observations: dict, at: str) -> dict:
    """Allowlist a public projection; exclude emails, endpoints and storage paths."""
    target_check(target)
    identity, workspace, metastore = [
        observations[k] for k in ["identity", "workspace", "metastore"]
    ]
    if (
        identity.get("active") is not True
        or workspace.get("account_id") != target["account_id"]
        or str(workspace.get("workspace_id")) != str(target["workspace_id"])
        or workspace.get("deployment_name") + ".cloud.databricks.com"
        != urlsplit(target["host"]).hostname
        or workspace.get("aws_region") != target["region"]
        or str(metastore.get("workspace_id")) != str(target["workspace_id"])
        or not metastore.get("metastore_id")
    ):
        raise PreflightRefused("pinned_identity_or_workspace_mismatch")
    if (
        workspace.get("compute_mode") != "SERVERLESS"
        or workspace.get("workspace_status") != "RUNNING"
    ):
        raise PreflightRefused("unsupported_workspace_mode_or_state")
    for name in ["catalogs", "jobs", "warehouses", "principals"]:
        if not isinstance(observations[name], list):
            raise PreflightRefused("unexpected_cli_inventory_schema")
    warehouses = observations["warehouses"]
    return {
        "schema": "lakehouse-readonly-preflight.v1",
        "observed_at_utc": at,
        "boundary": "actual_databricks_management_api_reads_no_compute",
        "target_binding": {
            "account_sha256": fingerprint(target["account_id"]),
            "workspace_sha256": fingerprint(str(target["workspace_id"])),
            "host_sha256": fingerprint(target["host"].rstrip("/")),
        },
        "cloud": "aws",
        "region": target["region"],
        "pricing_tier": workspace["pricing_tier"],
        "compute_mode": workspace["compute_mode"],
        "active_identity_verified": True,
        "workspace_admin_membership_observed": any(
            g.get("display") == "admins" for g in identity.get("groups", [])
        ),
        "unity_catalog_assignment_observed": True,
        "managed_workspace_catalog_observed": any(
            c.get("name") == "workspace" and c.get("catalog_type") == "MANAGED_CATALOG"
            for c in observations["catalogs"]
        ),
        "predictive_optimization_inherited_enabled": any(
            c.get("effective_predictive_optimization_flag", {}).get("value") == "ENABLE"
            for c in observations["catalogs"]
        ),
        "jobs_api_read_succeeded": True,
        "jobs_returned_bounded_page": len(observations["jobs"]),
        "principal_api_read_succeeded": True,
        "existing_service_principals_observed": len(observations["principals"]),
        "warehouses": [
            {
                "serverless": w.get("enable_serverless_compute"),
                "size": w.get("cluster_size"),
                "state": w.get("state"),
                "active_clusters": w.get("num_clusters"),
                "auto_stop_mins": w.get("auto_stop_mins"),
            }
            for w in warehouses
        ],
        "native_jobs_execution_verified": False,
        "separate_principal_authorization_verified": False,
        "catalog_write_permissions_verified": False,
        "billing_plan_credits_or_expiry_verified_by_these_apis": False,
        "resources_created": 0,
        "compute_starts_requested": 0,
        "sql_statements_submitted": 0,
    }


def native_gate(report: dict, owner: dict, cost: dict, now: datetime) -> dict:
    """Preparation gate only. A pass does not execute or authorize API mutations."""
    reasons = []
    required = [
        "active_identity_verified",
        "unity_catalog_assignment_observed",
        "managed_workspace_catalog_observed",
        "jobs_api_read_succeeded",
        "principal_api_read_succeeded",
    ]
    if not all(report.get(k) is True for k in required):
        reasons.append("required_management_reads_not_verified")
    try:
        observation = aware(report["observed_at_utc"])
        owner_at = aware(owner["observed_at_utc"])
        expiry = aware(owner["expires_at_utc"])
        if not timedelta(0) <= now - observation <= timedelta(hours=24) or not timedelta(
            0
        ) <= now - owner_at <= timedelta(hours=24):
            reasons.append("stale_or_future_observation")
        if expiry < now + timedelta(hours=4):
            reasons.append("insufficient_execution_and_cleanup_window")
    except (KeyError, ValueError, TypeError):
        reasons.append("exact_trial_expiry_or_observation_missing")
    if owner.get("target_binding") != report.get("target_binding") or not report.get(
        "target_binding"
    ):
        reasons.append("owner_observation_target_not_bound")
    if owner.get("trial_active") is not True or owner.get("currency") != "USD":
        reasons.append("active_usd_trial_not_confirmed")
    if owner.get("payment_arrangement") != "express_no_payment_method":
        reasons.append("no_out_of_pocket_billing_boundary_unconfirmed")
    if cost.get("target_binding") != report.get("target_binding"):
        reasons.append("cost_plan_target_not_bound")
    if (
        cost.get("pricing_status") != "applicable_rates_verified"
        or cost.get("region") != report.get("region")
        or cost.get("pricing_tier") != report.get("pricing_tier")
    ):
        reasons.append("applicable_costs_not_established")
    try:
        values = [
            Decimal(str(v))
            for v in [
                owner["remaining_credit_usd"],
                owner["approved_trial_consumption_usd"],
                cost["planned_total_usd"],
            ]
        ]
        if (
            any(not v.is_finite() or v <= 0 for v in values)
            or values[2] > values[1]
            or values[2] + Decimal("20") > values[0]
        ):
            reasons.append("cost_or_credit_headroom_not_approved")
    except (KeyError, ValueError, TypeError, InvalidOperation):
        reasons.append("bounded_trial_consumption_not_approved")
    return {
        "eligible_for_separately_authorized_bounded_pilot": not reasons,
        "reasons": reasons,
        "launch_performed": False,
    }


def collect(
    cli: str, config: str, workspace_profile: str, account_profile: str, target: dict
) -> dict:
    env = {**os.environ, "DATABRICKS_CONFIG_FILE": config, "DATABRICKS_AUTH_STORAGE": "secure"}
    # Require explicit private CLI profiles, never silently inherit a PAT/alternate target.
    for key in list(env):
        if key.startswith("DATABRICKS_") and key not in {
            "DATABRICKS_CONFIG_FILE",
            "DATABRICKS_AUTH_STORAGE",
        }:
            del env[key]
    version = subprocess.run(
        [cli, "version"], env=env, capture_output=True, text=True, timeout=20, check=False
    )
    if version.returncode or version.stdout.strip() != "Databricks CLI v" + CLI_VERSION:
        raise PreflightRefused("pinned_cli_version_required")
    raw = {}
    receipts = []
    for name, args in commands(target).items():
        profile = account_profile if name == "workspace" else workspace_profile
        result = subprocess.run(
            [cli, *args, "--profile", profile, "--output", "json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise PreflightRefused("management_read_failed_" + name)
        try:
            raw[name] = json.loads(result.stdout)
        except ValueError:
            raise PreflightRefused("invalid_cli_json_" + name) from None
        receipts.append(
            {
                "operation": name,
                "method": "GET",
                "return_code": result.returncode,
                "private_response_sha256": fingerprint(result.stdout),
            }
        )
    report = project(target, raw, datetime.now(UTC).isoformat())
    report["cli_version"] = CLI_VERSION
    report["cli_binary_sha256"] = hashlib.sha256(Path(cli).read_bytes()).hexdigest()
    report["management_read_receipts"] = receipts
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", required=True)
    parser.add_argument("--cli", required=True)
    parser.add_argument(
        "--private-config",
        required=True,
        help="Non-secret target/profile JSON outside public artifacts",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        if output.exists() or not output.parent.is_dir():
            raise PreflightRefused("fresh_output_in_existing_private_directory_required")
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=SOURCE_BASE, text=True
        ).strip()
        source_bytes = Path(__file__).read_bytes()
        committed = subprocess.check_output(
            ["git", "show", revision + ":src/onboarding/lakehouse_preflight.py"], cwd=SOURCE_BASE
        )
        if source_bytes != committed:
            raise PreflightRefused("exact_committed_preflight_source_required")
        configuration = json.loads(Path(args.private_config).read_bytes())
        report = collect(
            args.cli,
            configuration["config_file"],
            configuration["workspace_profile"],
            configuration["account_profile"],
            configuration["target"],
        )
        report["source_revision"] = revision
        report["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
        report["native_gate"] = native_gate(
            report,
            configuration.get("owner_observation", {}),
            configuration.get("cost_plan", {}),
            datetime.now(UTC),
        )
        with output.open("x", encoding="utf-8", newline="\n") as out:
            json.dump(report, out, indent=2)
            out.write("\n")
        print(json.dumps({"management_reads": "verified", "native_gate": report["native_gate"]}))
        return 0
    except (
        PreflightRefused,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "outcome": "blocked",
                    "reason": str(error)
                    if isinstance(error, PreflightRefused)
                    else type(error).__name__,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
