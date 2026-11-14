"""Offline source/oracle/finite-execution contracts; not a substitute for native Spark."""

import ast
import copy
from pathlib import Path

import pytest

from onboarding.lakehouse_plan import export_fixture, sha, namespace, job_spec, credit_projection


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
    assert "VERSION AS OF" in source
    assert "readChangeFeed" in source and "availableNow=True" in source
    assert "same_revision_content_conflict" in source
