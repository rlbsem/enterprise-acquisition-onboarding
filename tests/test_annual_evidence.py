"""A self-consistent checksum alone must not legitimize incorrect financial evidence."""

import hashlib
import json
import shutil
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_annual_evidence import check  # noqa: E402


@pytest.mark.parametrize("corruption", ["summary", "source", "route"])
def test_annual_checker_rejects_false_claims_even_with_updated_checksums(tmp_path, corruption):
    folder = tmp_path / "disposable-proof"
    shutil.copytree(ROOT / "docs/evidence/annual/run01", folder)
    name = "annual.json" if corruption == "route" else "financial.json"
    path = folder / name
    body = json.loads(path.read_bytes())
    if corruption == "summary":
        body["totals_after"]["bookings_minor"] += 100
    elif corruption == "source":
        body["source_events"][0]["body"]["amount_minor"] += 100
    else:
        body["browser"]["screenshots"][0]["observed_route"] = "unexecuted-view"
    path.write_bytes((json.dumps(body, indent=2) + "\n").encode())
    manifest = folder / "artifact-integrity.json"
    hashes = json.loads(manifest.read_bytes())
    hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.write_bytes((json.dumps(hashes, indent=2) + "\n").encode())
    with pytest.raises(AssertionError):
        check(folder)
