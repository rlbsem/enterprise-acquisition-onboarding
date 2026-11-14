"""Offline semantic and byte-integrity checks for preserved native acceptance records."""

import hashlib
import json
from pathlib import Path
import subprocess

from export_lakehouse_evidence import verify

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "docs/evidence/lakehouse-native/2026-11-14"
    hashes = json.loads((directory / "artifact-sha256.json").read_bytes())
    native_results = 0
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
