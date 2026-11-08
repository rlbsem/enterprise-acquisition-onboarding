"""Offline independent assertions over actual recorded provider observations."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hubspot_evidence", ROOT / "scripts/check_hubspot_native_evidence.py"
)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def test_recorded_native_acceptance_and_original_bytes():
    assert evidence.verify()["historical_files_unchanged"] == 140


@pytest.mark.parametrize(
    "fault",
    [
        "extra_company",
        "duplicate_pair",
        "wrong_property",
        "paging",
        "http_error",
        "false_portal_claim",
        "discard_failure",
        "write_claim",
    ],
)
def test_independent_evidence_rejects_divergence(tmp_path, fault):
    folder = tmp_path / "evidence"
    shutil.copytree(ROOT / evidence.RECORD, folder)
    name = "attempt-04/independent-responses.json"
    data = json.loads((folder / name).read_bytes())
    if fault == "extra_company":
        data[1]["source"]["association_results"].append(
            {"id": "other", "type": "contact_to_company_unlabeled"}
        )
    elif fault == "duplicate_pair":
        data[1]["source"]["association_results"].append(data[1]["source"]["association_results"][0])
    elif fault == "wrong_property":
        data[1]["source"]["properties"]["email"] = "wrong@example.com"
    elif fault == "paging":
        data[0]["source"]["association_paging_present"] = True
    elif fault == "http_error":
        data[0]["status_code"] = 403
    elif fault == "false_portal_claim":
        name = "attempt-04/cli.json"
        data = json.loads((folder / name).read_bytes())
        data["result"]["verified_portal_id_by_api"] = True
    elif fault == "discard_failure":
        name = "attempt-03/cli.json"
        data = {"result": {"outcome": "verified"}}
    else:
        name = "fixture-repair.json"
        data = json.loads((folder / name).read_bytes())
        data["property_edits_requested"] = 1
    (folder / name).write_text(json.dumps(data), encoding="utf-8")
    # Recompute content assertions directly so rejection is not merely a hash mismatch.
    with pytest.raises(AssertionError):
        evidence.check_content(folder)
