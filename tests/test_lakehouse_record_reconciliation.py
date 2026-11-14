"""Offline independent reconciliation of genuine archived runs; no cloud calls."""

import copy
import json
from pathlib import Path

import pytest

from onboarding.lakehouse_plan import validate_native_financial_result

DIRECTORY = Path("docs/evidence/lakehouse-native/2026-11-14")


def result(name):
    return json.loads((DIRECTORY / name).read_bytes())["tasks"][0]["result"]


def test_actual_native_publications_and_source_hash_reconcile_independently():
    assert validate_native_financial_result(result("06-postcheck.json"))
    assert validate_native_financial_result(result("08-restricted-consumer.json"))
    assert validate_native_financial_result(result("09-financial-sql-audit.json"))


def test_changing_actual_and_recorded_expected_together_still_fails_oracle():
    record = copy.deepcopy(result("06-postcheck.json"))
    check = next(
        o["result"]
        for o in record["observations"]
        if o["check"] == "restated_continuation_readback"
    )
    check["actual"]["totals"][0]["net_invoice_minor"] += 1
    check["expected"]["totals"][0]["net_invoice_minor"] += 1
    with pytest.raises(ValueError):
        validate_native_financial_result(record)


def test_changed_native_source_membership_is_not_a_reconciled_receipt():
    record = copy.deepcopy(result("06-postcheck.json"))
    check = next(
        o["result"] for o in record["observations"] if o["check"] == "restated_source_hash_readback"
    )
    check["actual"] = check["expected"] = "0" * 64
    with pytest.raises(ValueError):
        validate_native_financial_result(record)


def test_parse_failure_cannot_be_relabelled_as_access_denial():
    record = copy.deepcopy(result("08-restricted-consumer.json"))
    next(o["result"] for o in record["observations"] if o["check"] == "raw_read_denied")[
        "error_class"
    ] = "PARSE_SYNTAX_ERROR"
    with pytest.raises(ValueError):
        validate_native_financial_result(record)
