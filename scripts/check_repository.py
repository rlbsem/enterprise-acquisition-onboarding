"""Offline original-byte, source revision, domain evidence and public-content checks."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
count = 0
for mf in (ROOT / "docs/evidence").rglob("manifest.json"):
    inventory = json.loads(mf.read_bytes())
    actual = {
        p.name
        for p in mf.parent.iterdir()
        if p.is_file() and p.name not in ["manifest.json", "README.md"]
    }
    assert set(inventory) == actual, "evidence inventory mismatch"
    for name, h in inventory.items():
        assert hashlib.sha256((mf.parent / name).read_bytes()).hexdigest() == h
        count += 1
    r = json.loads((mf.parent / "verification.json").read_bytes())
    assert r["tests"] > 0 and not any(r[k] for k in ["failures", "errors", "skipped"])
    for name, h in r["source_sha256"].items():
        data = subprocess.check_output(["git", "show", r["source_commit"] + ":" + name], cwd=ROOT)
        assert hashlib.sha256(data).hexdigest() == h, "source fingerprint mismatch:" + name
    d = json.loads((mf.parent / "demo.json").read_bytes())
    assert [g["passed"] for g in d["readiness_gates"]] == [True, True, False]
    assert d["scenarios"]["B_ambiguity"]["observed"] == "ambiguous_identity"
    assert (
        d["scenarios"]["C_readiness_gate"]["invalid_legal_entity_response"]["reason"]
        == "incorrect_legal_entity"
    )
    assert d["scenarios"]["D_replay"]["before"] == d["scenarios"]["D_replay"]["after"] == 8
    assert (
        sum(
            c["gate"]["reconciled_customer_accounts"]
            for c in d["portfolio"]["companies"]
            if c["included"]
        )
        == d["portfolio"]["included_customer_accounts"]
        == 2
    )
    assert d["native_vendor_calls"] == 0 and d["owned_resources_cleaned"]
    for c in d["portfolio"]["companies"]:
        for source in c["source_records"]:
            assert source["raw"] and source["normalized"] and source["source_id"] == "100"
links = 0
for doc in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
    for target in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
        if "://" in target or target.startswith("#"):
            continue
        path = (doc.parent / target.split("#")[0]).resolve()
        assert path.is_relative_to(ROOT) and path.exists(), target
        links += 1
names = subprocess.check_output(
    ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True
).splitlines()
for name in names:
    assert not any(p in name.split("/") for p in [".local", ".venv", "__pycache__"]), name
    data = (ROOT / name).read_bytes().decode("utf-8", errors="ignore")
    assert not re.search(r"-----BEGIN (?:RSA )?PRIVATE KEY|(?:AKIA|ASIA)[A-Z0-9]{16}", data), name
    if name.startswith("docs/evidence/") and name.endswith(".json"):
        assert not re.search(r'"(?:dsn|token|password|access_token)"\s*:', data), name
        assert not re.search(r"[A-Za-z]:\\\\Users\\\\", data), name
print(
    json.dumps(
        {
            "evidence_artifacts": count,
            "local_markdown_links": links,
            "public_content_check": "passed",
        }
    )
)
