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


def check_pass3(folder):
    from onboarding.financial_oracle import calculate

    p = json.loads((folder / "pass3.json").read_bytes())
    assert p["currency"] == "USD" and p["money_unit"] == "integer_minor_units"
    events = {r["id"]: r for r in p["source_events"]}
    for r in events.values():
        assert digest(r["body"]) == r["hash"] and type(r["body"]["amount_minor"]) is int
    snapshots = {r["id"]: r for r in p["records"]["financial_snapshots"]}
    policies = {r["version"]: r["body"] for r in p["records"]["financial_policies"]}

    def independent(report):
        snapshot = snapshots[report]
        inputs = [r for r in p["records"]["financial_inputs"] if r["report_id"] == report]
        for r in inputs:
            assert events[r["event_id"]]["status"] == "accepted"
            assert r["body"] == events[r["event_id"]]["body"] and r["hash"] == digest(r["body"])
        previous = (
            independent(snapshot["previous_id"])["portfolio_totals"]
            if snapshot["previous_id"]
            else None
        )
        return calculate(
            inputs, snapshot["control"], policies[snapshot["policy_version"]], previous
        )

    for name in ["original", "restated"]:
        result = p[name]
        expected = independent(name)
        for model, rows in expected.items():

            def key(r):
                return json.dumps(r, sort_keys=True)

            assert sorted(rows, key=key) == sorted(result["results"][model], key=key), model
        assert len(result["comparisons"]) == 7 and all(
            c["exact_content_match"]
            and c["row_differences"] == 0
            and c["sha256"] == c["observed_sha256"]
            for c in result["comparisons"]
        )
        nodes = result["dbt"]["results"]
        assert len([n for n in nodes if n["id"].startswith("model.")]) == 9
        assert len([n for n in nodes if n["id"].startswith("test.")]) == 9
        assert result["dbt"]["return_code"] == 0 and all(
            n["status"] in ["success", "pass"] for n in nodes
        )
        assert result["status"] == "reconciled_with_open_variances"
    assert independent("original-cutoff-replay") == independent("original")
    assert p["totals_before"]["consolidated_invoice_minor"] == 36800000
    assert p["totals_after"]["consolidated_invoice_minor"] == 38800000
    assert (
        p["totals_before"]["allocated_cash_minor"]
        == p["totals_after"]["allocated_cash_minor"]
        == 23000000
    )
    assert len(p["changed_bridge"]) == 5 and all(
        r["delta_minor"] == 2000000 and r["period"] == "2026-01-01" for r in p["changed_bridge"]
    )
    assert not snapshots["original"]["control"]["summit"]["admitted"]
    assert {
        (r["code"], r["amount_minor"]) for r in p["restated"]["results"]["reconciliation_variances"]
    } == {("erp_posting_difference", 500000), ("intercompany_unresolved", 800000)}
    assert all(r["response"]["status"] == "rejected" for r in p["rejected_updates"])
    blocked = p["blocked_candidate"]
    assert not blocked["published"] and blocked["dbt"]["return_code"] != 0
    assert any(
        n["status"] == "fail" and "financial_amount_controls" in n["id"]
        for n in blocked["dbt"]["results"]
    )
    assert {r["report_id"] for r in p["records"]["financial_publications"]} == {
        "original",
        "restated",
    }
    assert (
        p["downstream_effects_before"]
        == p["downstream_effects_after"]
        == p["downstream_posts_before"]
        == p["downstream_posts_after"]
        == 1
    )
    assert p["original_report_unchanged"] and p["original_cutoff_replay_equal"]
    assert p["native_vendor_calls"] == 0 and p["owned_resources_cleaned"]


def check_pass4(folder):
    import struct

    p = json.loads((folder / "pass4.json").read_bytes())
    assert p["browser"]["name"] == "chromium" and p["browser"]["playwright"] == "1.64.1"
    checks = {r["case"]: r for r in p["checks"]}
    # The same sign-in assertion executes in separate desktop/mobile contexts.
    # Validate every recorded observation, not only one record per check name.
    assert len(p["checks"]) >= 52 and all(
        r["passed"] and r["expected"] == r["observed"] for r in p["checks"]
    )
    for key in [
        "A_sponsor_company_scope",
        "B_operator_single_scope",
        "B_cross_company_source_denied",
        "C_sponsor_write_denied",
        "C_operator_write_denied",
        "D_actual_decision_results",
        "E_original_january_usd",
        "E_restated_january_usd",
        "F_variance_categories",
        "G_held_and_effective_exclusions",
        "H_no_new_business_posts",
        "I_mobile_no_page_overflow",
        "session_expiration_browser_redirect",
        "logout_revokes_browser_session",
    ]:
        assert key in checks, key
    assert len(p["accessibility"]) == 7
    assert all(
        not a["violations"] and not a["incomplete"] and a["version"] == "4.11.0"
        for a in p["accessibility"]
    )
    assert len(p["screenshots"]) == 7
    for shot in p["screenshots"]:
        data = (folder / shot["file"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        assert width == shot["viewport"]["width"] and height >= shot["viewport"]["height"]
        assert shot["full_page"] and shot["capture"] == "real_chromium_page_screenshot"
        assert (
            shot["role"] in ["sponsor", "operator", "reviewer"]
            and shot["publication"] == "restated"
        )
    assert [d["result"] for d in p["review_decisions"]] == ["rejected", "approved", "approved"]
    assert all(
        d["company"] == "summit" and d["actor"] == "acquisition-reviewer" and d["reason"]
        for d in p["review_decisions"]
    )
    assert {d["review_id"] for d in p["review_decisions"]} == set(p["review_ids"].values())
    assert any(
        a["action"] == "review_approved" and a["detail"]["actor"] == "acquisition-reviewer"
        for a in p["audit"]
    )
    f = json.loads((folder / "pass3.json").read_bytes())
    for name in ["totals_before", "totals_after"]:
        assert p["financial_publication_checks"][name] == f[name]
    for report in ["original", "restated"]:
        r = p["financial_execution"][report]
        assert r["dbt"]["return_code"] == 0 and all(
            n["status"] in ["success", "pass"] for n in r["dbt"]["results"]
        )
        assert len(r["comparisons"]) == 7 and all(
            c["row_differences"] == 0 for c in r["comparisons"]
        )
    assert p["downstream_posts_before"] == p["downstream_posts_after"] == p["receiver_effects"] == 1
    assert p["owned_resources_cleaned"] and p["native_vendor_calls"] == 0


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
    if "pass3.json" in inventory:
        check_pass3(mf.parent)
    if "pass4.json" in inventory:
        check_pass4(mf.parent)
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
