"""Offline semantic and byte-integrity checks for preserved native acceptance records."""

import hashlib
import json
from pathlib import Path
import subprocess

from export_lakehouse_evidence import verify
from onboarding.lakehouse_plan import export_fixture, sha

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "docs/evidence/lakehouse-native/2026-11-14"
    hashes = json.loads((directory / "artifact-sha256.json").read_bytes())
    native_results = 0
    actual_files = {p.name for p in directory.glob("*.json") if p.name != "artifact-sha256.json"}
    if actual_files != set(hashes):
        raise ValueError("unlisted_or_missing_native_artifact")
    fixture = export_fixture(3)
    for name, expected in hashes.items():
        path = directory / name
        if path.parent != directory or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("native_artifact_changed:" + name)
        if name.endswith(".json") and name[0].isdigit():
            record = json.loads(path.read_bytes())
            verify(record)
            subprocess.check_output(
                [
                    "git",
                    "cat-file",
                    "-e",
                    record["source_commit"] + ":scripts/lakehouse_notebook.py",
                ],
                cwd=ROOT,
            )
            native_results += sum("result" in t for t in record["tasks"])
            for task in record["tasks"]:
                result = task.get("result")
                if not result:
                    continue
                if result["fixture_sha256"] != sha(fixture):
                    raise ValueError("native_fixture_changed")
                if result["phase"] == "pilot":
                    observations = {o["check"]: o["result"] for o in result["observations"]}
                    for label in ["original", "restated"]:
                        if (
                            observations[label + "_full_financial_oracle"]["actual"]
                            != fixture["expected"][label]
                        ):
                            raise ValueError("native_result_disagrees_with_independent_oracle")
    print(
        json.dumps(
            dict(
                checked_hashes=len(hashes),
                native_task_results=native_results,
                offline_integrity_only=True,
            )
        )
    )


if __name__ == "__main__":
    main()
