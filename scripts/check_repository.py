"""Offline original-byte, source revision, domain evidence and public-content checks."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def check_pass2(folder):
    p = json.loads((folder / "pass2.json").read_bytes())
    assert not p["A_identity"]["before_passed"] and p["A_identity"]["after_passed"]
    assert not p["B_wrong_entity"]["admission_passed"]
    assert p["B_wrong_entity"]["source_correction"]["status"] == "accepted"
    gate = p["C_resnapshot"]["final_gate"]
    assert gate["passed"] and gate["mapping_version"] == 2
    delivery = p["D_E_delivery"]
    assert delivery["uncertain"] == "uncertain" and delivery["recovered"] == "confirmed"
    assert delivery["independently_observed_effects_before_recovery"] == 1
    assert delivery["duplicate_plan"] and delivery["conflicting_payload_http_status"] == 409
    assert len(p["receiver"]["effects"]) == len(p["receiver"]["records"]) == 1
    intent = p["control"]["outbound"][0]
    remote = p["receiver"]["effects"][0]
    record = p["receiver"]["records"][0]
    assert intent["state"] == "confirmed" and intent["attempts"] == 1
    assert intent["effect_id"] == remote["id"] == delivery["effect_id"]
    assert intent["payload"] == remote["payload"] == intent["proof"]["payload"]
    assert digest(intent["payload"]) == remote["hash"] == intent["hash"]
    assert record["body"] == remote["receipt"]["record"] == intent["proof"]["record"]
    assert digest(record["body"]) == remote["receipt"]["record_hash"]
    assert sum(row["operation"] == "apply" for row in p["receiver"]["requests"]) == 1
    assert {row["version"] for row in p["control"]["mapping_versions"]} == {1, 2}
    assert {row["body"]["version"] for row in p["control"]["source_record_history"]} == {1, 2}
    assert len(p["control"]["quarantine"]) == len(p["control"]["quarantine_resolutions"]) == 3
    original = [m for m in p["control"]["messages"] if m["source"] == "legacy-crm"]
    assert len(original) == 1 and original[0]["status"] == "quarantined"
    decisions = {d["review_id"]: d for d in p["control"]["review_decisions"]}
    assert decisions[p["A_identity"]["rejected_review"]]["result"] == "rejected"
    assert decisions[p["A_identity"]["approved_review"]]["result"] == "approved"
    for change in ["admission", "mapping", "business", "source_revision"]:
        check = json.loads((folder / ("authorization-" + change + ".json")).read_bytes())
        assert (
            check["expected"] == check["observed"] == {"state": "blocked", "effects": 0, "posts": 0}
        )
    exhausted = json.loads((folder / "exhaustion.json").read_bytes())
    assert (
        exhausted["expected"]
        == exhausted["observed"]
        == {"state": "exhausted", "attempts": 3, "effects": 0}
    )
    killed = json.loads((folder / "process-death.json").read_bytes())
    assert killed["actual_process_terminated"] and killed["child_exit_code"] != 0
    assert killed["confirmed_after_restart"] and killed["competing_worker"] == "busy"
    assert killed["receiver_effects"] == killed["receiver_posts"] == 1
    assert p["native_vendor_calls"] == 0 and p["owned_resources_cleaned"]


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
    if "pass2.json" in inventory:
        check_pass2(mf.parent)
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
