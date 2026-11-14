"""Recorded management evidence must not become an invented data acceptance."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "lakehouse_evidence", ROOT / "scripts/check_lakehouse_preflight.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_actual_management_record_source_and_historical_bytes():
    assert checker.verify()["historical_files_unchanged"] == 228


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_jobs_execution_verified", True),
        ("separate_principal_authorization_verified", True),
        ("catalog_write_permissions_verified", True),
        ("billing_plan_credits_or_expiry_verified_by_these_apis", True),
        ("compute_starts_requested", 1),
        ("region", "us-east-2"),
        ("native_gate", {"launch_performed": True}),
    ],
)
def test_semantic_checks_reject_invented_scope_even_without_hash_gate(field, value):
    record = json.loads((ROOT / checker.RECORD / "management-reads.json").read_bytes())
    record[field] = value
    with pytest.raises(AssertionError):
        checker.check_content(record)
