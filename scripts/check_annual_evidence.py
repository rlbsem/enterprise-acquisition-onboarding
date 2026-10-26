"""Recalculate annual publications from hashed frozen sources and check actual browser evidence."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from onboarding.contracts import digest  # noqa: E402
from onboarding.financial_oracle import calculate  # noqa: E402
from onboarding.annual_fixtures import source_controls  # noqa: E402


def check(folder):
    hashes = json.loads((folder / "artifact-integrity.json").read_bytes())
    assert set(hashes) == {
        p.name for p in folder.iterdir() if p.is_file() and p.name != "artifact-integrity.json"
    }
    for name, expected in hashes.items():
        assert Path(name).name == name
        raw = (folder / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected, name
        if name.endswith(".json"):
            assert not re.search(r'"(?:dsn|token|password|access_token)"\s*:', raw.decode())
            assert not re.search(
                r"postgresql?://|-----BEGIN .*PRIVATE KEY|(?:AKIA|ASIA)[A-Z0-9]{16}", raw.decode()
            )
    report = json.loads((folder / "annual.json").read_bytes())
    assert re.fullmatch(r"[a-f0-9]{40}", report["source_commit"])
    assert (
        report["status"] == "passed"
        and report["native_vendor_calls"] == 0
        and not report["cloud_resources"]
    )
    for name, expected in report["source_sha256"].items():
        blob = subprocess.check_output(
            ["git", "show", report["source_commit"] + ":" + name], cwd=ROOT
        )
        assert hashlib.sha256(blob).hexdigest() == expected, name
    assert report["shutdown"]["clean_exit"] and report["shutdown"]["owned_services_stopped"]
    if report["lane"] == "actual_docker_compose":
        assert report["cleanup"]["verified_absent"] and not any(
            report["cleanup"]["independent_label_inventory"].values()
        )
        assert (
            report["isolation"]["loopback_console_only"]
            and report["isolation"]["no_database_published"]
        )
    else:
        assert report["cleanup"]["owned_process_exited"]
    financial = json.loads((folder / "financial.json").read_bytes())
    assert financial["synthetic"] and financial["native_vendor_calls"] == 0
    assert len(financial["periods"]) == 12 and len(financial["scenario"]["profiles"]) == 3
    events = {r["id"]: r for r in financial["source_events"]}
    assert len(events) == financial["source_event_count"]
    for r in events.values():
        assert digest(r["body"]) == r["hash"]
    assert financial["rejected_held_crm_bookings"] == 12
    assert (
        sum(
            r["status"] == "rejected"
            and r["body"]["company"] == "summit"
            and r["reason"] == "financial_identity_unresolved"
            for r in events.values()
        )
        == 12
    )
    snapshots = {r["id"]: r for r in financial["records"]["financial_snapshots"]}
    policies = {r["version"]: r["body"] for r in financial["records"]["financial_policies"]}

    def independent(identifier):
        snap = snapshots[identifier]
        inputs = [
            r for r in financial["records"]["financial_inputs"] if r["report_id"] == identifier
        ]
        for row in inputs:
            event = events[row["event_id"]]
            assert (
                event["status"] == "accepted"
                and row["body"] == event["body"]
                and row["hash"] == event["hash"]
            )
        previous = (
            independent(snap["previous_id"])["portfolio_totals"] if snap["previous_id"] else None
        )
        return calculate(inputs, snap["control"], policies[snap["policy_version"]], previous)

    def canonical(rows):
        return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))

    for name in ["original", "restated"]:
        observed = financial[name]
        expected = independent(name)
        assert set(observed["results"]) == set(expected)
        for model, rows in expected.items():
            assert canonical(rows) == canonical(observed["results"][model]), model
        assert observed["dbt"]["return_code"] == 0
        assert sum(n["id"].startswith("model.") for n in observed["dbt"]["results"]) == 9
        assert sum(n["id"].startswith("test.") for n in observed["dbt"]["results"]) == 9
        assert len(observed["dbt"]["results"]) == 18 and all(
            n["status"] in ["success", "pass"] for n in observed["dbt"]["results"]
        )
        assert len(observed["comparisons"]) == 7 and all(
            r["row_differences"] == 0
            and r["exact_content_match"]
            and r["sha256"] == r["observed_sha256"]
            for r in observed["comparisons"]
        )
        summary = financial["totals_before" if name == "original" else "totals_after"]
        assert summary == {k: sum(r[k] for r in expected["portfolio_totals"]) for k in summary}
        inputs = [
            r["body"] for r in financial["records"]["financial_inputs"] if r["report_id"] == name
        ]
        assert source_controls(inputs) == financial["source_controls_" + name]
        assert not any(r["company"] == "summit" for r in observed["results"]["fct_invoices"])
        assert not any(
            r["company"] == "meridian" and r["period"] == "2026-01-01"
            for r in observed["results"]["fct_invoices"]
        )
        assert {
            (r["code"], r["amount_minor"]) for r in observed["results"]["reconciliation_variances"]
        } == {("erp_posting_difference", 2500000), ("intercompany_unresolved", 4000000)}
    assert independent("original-cutoff-replay") == independent("original")
    assert (
        financial["original_report_unchanged"] and not financial["blocked_candidate"]["published"]
    )
    assert financial["blocked_candidate"]["dbt"]["return_code"] != 0
    assert any(
        n["status"] == "fail" and "financial_amount_controls" in n["id"]
        for n in financial["blocked_candidate"]["dbt"]["results"]
    )
    assert all(r["response"]["status"] == "rejected" for r in financial["rejected_updates"])
    assert financial["downstream_effects"] == financial["downstream_posts"] == 1
    b = report["browser"]
    assert b["engine"]["name"] == "chromium" and b["engine"]["version"]
    assert b["engine"]["playwright"] == "1.64.1"
    assert len(b["checks"]) >= 20 and all(
        c["passed"] and c["expected"] == c["observed"] for c in b["checks"]
    )
    assert len(b["screenshots"]) == 4 and len(b["accessibility"]) == 2
    assert all(not s["violations"] and not s["incomplete"] for s in b["accessibility"])
    for shot in b["screenshots"]:
        assert shot["capture"] == "real_chromium_page_screenshot"
        assert shot["observed_route"] == shot["route"] and shot["role"] == "sponsor"
        assert (
            shot["rendered_heading"]
            == {
                "portfolio": "Which acquisitions are ready to report?",
                "finance": "Financial reconciliation",
            }[shot["route"]]
        )
        assert shot["captured_at"]
        assert hashlib.sha256((folder / shot["file"]).read_bytes()).hexdigest() == shot["sha256"]
    return dict(
        status="passed",
        source_commit=report["source_commit"],
        lane=report["lane"],
        source_events=len(events),
        browser_checks=len(b["checks"]),
        totals=financial["totals_after"],
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.folder)))
