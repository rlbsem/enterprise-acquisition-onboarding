"""Projection and semantic checks cannot turn local fixtures into native evidence."""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "lakehouse_export", Path("scripts/export_lakehouse_evidence.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample():
    return dict(
        run_id=123,
        source_commit="a" * 40,
        state=dict(
            life_cycle_state="TERMINATED",
            result_state="SUCCESS",
            state_message="private owner metadata",
        ),
        tasks=[
            dict(
                task_key="pilot",
                run_id=124,
                state=dict(life_cycle_state="TERMINATED", result_state="SUCCESS"),
                result=dict(
                    source_commit="a" * 40,
                    synthetic=True,
                    status="passed",
                    observations=[
                        dict(check="test-only", result=dict(equal=True, actual=1, expected=1))
                    ],
                ),
            )
        ],
    )


def test_public_projection_omits_unapproved_metadata():
    record = module.project(sample())
    assert "state_message" not in record["state"]
    assert module.verify(record)


@pytest.mark.parametrize("change", ["source", "state", "comparison", "identity"])
def test_semantic_corruption_is_refused(change):
    r = module.project(sample())
    if change == "source":
        r["tasks"][0]["result"]["source_commit"] = "b" * 40
    elif change == "state":
        r["tasks"][0]["state"]["result_state"] = "FAILED"
    elif change == "comparison":
        r["tasks"][0]["result"]["observations"][0]["result"]["actual"] = 2
    else:
        r["run_id"] = "simulated"
    with pytest.raises(ValueError):
        module.verify(r)


def test_native_failure_remains_a_failure():
    r = copy.deepcopy(sample())
    r["state"]["result_state"] = "FAILED"
    r["tasks"][0].pop("result")
    r["tasks"][0]["state"]["result_state"] = "FAILED"
    r["tasks"][0]["error"] = "ImportError: incompatible runtime\nprivate stack trace"
    public = module.project(r)
    assert module.verify(public)
    assert public["state"]["result_state"] == "FAILED"
    assert public["tasks"][0]["failure_observation"] == "ImportError: incompatible runtime"


def test_credential_shaped_error_is_never_exported():
    r = sample()
    r["tasks"][0]["error"] = "Bearer forbidden-test-only"
    with pytest.raises(ValueError):
        module.project(r)
