"""Offline source/oracle/finite-execution contracts; not a substitute for native Spark."""

import ast
import copy
from pathlib import Path

import pytest

from onboarding.lakehouse_plan import (
    export_fixture,
    sha,
    namespace,
    job_spec,
    credit_projection,
    admit_credit_step,
    reserve_completed_duration,
    add_consumer_run_as_role,
)


def test_original_financial_oracle_and_correction_are_separate():
    f = export_fixture()
    assert f == export_fixture()
    assert f["synthetic"] and f["currency"] == "USD"
    assert len(f["controls"]) == 3
    assert not f["controls"][1]["admitted"]
    before, after = [f["expected"][k] for k in ["original", "restated"]]
    assert before != after
    assert before["variances"] and after["variances"]
    assert len(f["corrections"]) == 3
    assert len(before["totals"]) == 2 and len(before["legal"]) == 6
    changed = copy.deepcopy(f)
    changed["baseline"][0]["amount_minor"] += 1
    assert sha(changed) != sha(f)


def test_full_fixture_exercises_held_entities_and_intercompany_eliminations():
    f = export_fixture(50)
    assert len(f["controls"]) == 50
    assert any(not c["admitted"] for c in f["controls"])
    assert any(b["kind"] == "intercompany_acceptance" for b in f["baseline"])
    assert sum(r["elimination_minor"] for r in f["expected"]["original"]["totals"]) > 0
    assert any(v[2] == "intercompany_unresolved" for v in f["expected"]["restated"]["variances"])
    assert any(v[2] == "erp_posting_difference" for v in f["expected"]["restated"]["variances"])


@pytest.mark.parametrize(
    "value", ["production", "acq_lh_a;DROP", "workspace.x", "acq_lh_", "acq_lh_../x"]
)
def test_namespace_refuses_unowned_targets(value):
    with pytest.raises(ValueError):
        namespace(value)


def test_native_job_is_unscheduled_bounded_and_has_no_cluster_or_retry():
    spec = job_spec(
        "/Shared/acquisition-lakehouse/test/acceptance",
        "acq_lh_20261114pilot",
        "pilot",
        "a" * 40,
        "b" * 64,
    )
    assert spec["timeout_seconds"] == 900
    assert "schedule" not in spec and "job_clusters" not in spec
    assert spec["tasks"][0]["max_retries"] == 0
    assert spec["tasks"][0]["disable_auto_optimization"] is True
    assert spec["tasks"][0]["retry_on_timeout"] is False
    assert not {"new_cluster", "existing_cluster_id"} & spec["tasks"][0].keys()
    assert spec["tasks"][0]["notebook_task"]["base_parameters"]["fixture_hash"] == "b" * 64


@pytest.mark.parametrize(
    "change",
    [dict(phase="other"), dict(seconds=901), dict(revision="main"), dict(path="/Users/someone/x")],
)
def test_spec_rejects_unbounded_or_unpinned_requests(change):
    values = dict(
        path="/Shared/acquisition-lakehouse/test/acceptance",
        schema="acq_lh_20261114pilot",
        phase="pilot",
        revision="a" * 40,
        fixture_hash="b" * 64,
    )
    with pytest.raises(ValueError):
        job_spec(**(values | change))


def test_pilot_projection_includes_cleanup_and_delayed_usage_reserve():
    assert float(credit_projection(1200)) < 20
    assert float(credit_projection(1200)) > 5
    with pytest.raises(ValueError):
        credit_projection(float("nan"))


def test_native_notebook_parses_without_local_spark_dependency():
    source = Path("scripts/lakehouse_notebook.py").read_text()
    ast.parse(source)
    ast.parse(source, feature_version=(3, 10))
    assert "from datetime import UTC" not in source
    assert "VERSION AS OF" in source
    assert "readChangeFeed" in source and "availableNow=True" in source
    assert "same_revision_content_conflict" in source
    assert "FROM {{ns}}.publications p LATERAL VIEW" in source


def test_pending_usage_is_reserved_and_never_treated_as_zero():
    ledger = dict(observed_usd="0", pending_reserved_usd="12", cleanup_reserved_usd="2")
    assert admit_credit_step(ledger, "5") == "19"
    with pytest.raises(ValueError):
        admit_credit_step(ledger, "7")
    with pytest.raises(ValueError):
        admit_credit_step(ledger, "1", expansion=True)


def test_expansion_requires_success_actual_usage_and_verified_rate():
    ledger = dict(
        observed_usd="1",
        pending_reserved_usd="10",
        cleanup_reserved_usd="10",
        pilot_accepted=True,
        actual_usage_observed=True,
        applicable_rate_verified=True,
    )
    assert admit_credit_step(ledger, "100", expansion=True) == "121"
    for field in ["pilot_accepted", "actual_usage_observed", "applicable_rate_verified"]:
        with pytest.raises(ValueError):
            admit_credit_step(ledger | {field: False}, "1", expansion=True)
    with pytest.raises(ValueError):
        admit_credit_step(ledger, "290", expansion=True)


def test_completed_runtime_replaces_pending_estimate_once_without_claiming_billing():
    ledger = dict(
        pending_reserved_usd="5",
        observed_usd="0",
        actual_usage_observed=False,
        submissions=[dict(run_id=1, reserved_usd="5")],
    )
    reserve_completed_duration(ledger, 1, 120000)
    assert float(ledger["pending_reserved_usd"]) == 0.875
    assert ledger["observed_usd"] == "0" and not ledger["actual_usage_observed"]
    assert "not measured billing" in ledger["submissions"][0]["estimate_basis"]
    reserve_completed_duration(ledger, 1, 120000)
    assert float(ledger["pending_reserved_usd"]) == 0.875


def test_controlled_interoperability_reruns_have_a_separate_finite_allowance():
    ledger = dict(
        observed_usd="0",
        pending_reserved_usd="12",
        cleanup_reserved_usd="2",
        controlled_rerun_reserved_usd="7",
    )
    assert admit_credit_step(ledger, "5") == "26"
    with pytest.raises(ValueError):
        admit_credit_step(ledger | dict(controlled_rerun_reserved_usd="21"), "1")
    with pytest.raises(ValueError):
        admit_credit_step(ledger, "7")


def test_run_as_binding_preserves_manager_and_other_principal_roles():
    name = "accounts/test-only/servicePrincipals/owned-only/ruleSets/default"
    original = dict(
        name=name,
        etag="test-only-version",
        grant_rules=[
            dict(role="roles/servicePrincipal.manager", principals=["users/existing"]),
            dict(role="roles/servicePrincipal.user", principals=["users/other"]),
        ],
    )
    patch = add_consumer_run_as_role(original, name, "deployer")
    assert patch["rule_set"]["etag"] == "test-only-version"
    assert patch["rule_set"]["grant_rules"][0] == original["grant_rules"][0]
    assert patch["rule_set"]["grant_rules"][1]["principals"] == ["users/other", "users/deployer"]
    assert original["grant_rules"][1]["principals"] == ["users/other"]
    with pytest.raises(ValueError):
        add_consumer_run_as_role(original, "unowned-target", "deployer")
