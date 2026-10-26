"""Verify portable proof against exact Git source, domain results and image hashes."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def check(folder, failed=False, working_tree=False):
    manifest = json.loads((folder / "artifact-integrity.json").read_bytes())
    actual = {
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and p.name != "artifact-integrity.json"
    }
    assert actual == set(manifest), "portable_artifact_inventory_mismatch"
    for name, expected in manifest.items():
        assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected, name
        if name.endswith(".json"):
            raw = (folder / name).read_text(encoding="utf-8")
            assert not re.search(r'"(?:dsn|token|password|access_token)"\s*:', raw)
            assert not re.search(
                r"postgresql?://|-----BEGIN .*PRIVATE KEY|(?:AKIA|ASIA)[A-Z0-9]{16}", raw
            )
    p = json.loads((folder / "portable.json").read_bytes())
    assert re.fullmatch(r"[a-f0-9]{40}", p["source_commit"])
    for name, expected in p["source_sha256"].items():
        blob = subprocess.check_output(["git", "show", p["source_commit"] + ":" + name], cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest() == expected, name
    if working_tree:
        from verify_portable import source_hashes

        assert p["source_sha256"] == source_hashes(), "portable_current_source_mismatch"
    assert p["native_vendor_calls"] == 0 and not p["cloud_resources"]
    assert not p["independent_architecture_audit"]
    docker = p["lane"] == "actual_docker_compose"
    for c in p["cleanup"]:
        if docker:
            assert c["verified_absent"] and not any(c["independent_label_inventory"].values())
        else:
            assert c["owned_process_exited"]
    if failed:
        assert p["status"] == "failed"
        return {"status": "preserved_failure", "source_commit": p["source_commit"]}
    assert p["status"] == "passed" and p["cleanup"]
    phases = {r["name"]: r for r in p["phases"]}
    assert all(
        phases["fresh_restart"][k]
        for k in [
            "new_private_credentials",
            "old_session_rejected",
            "old_credential_rejected",
            "financial_parity",
        ]
    )
    for name in ["normal_shutdown", "restarted_shutdown", "browser_shutdown"]:
        assert phases[name]["clean_exit"] and phases[name]["owned_services_stopped"]
    if docker:
        for name in ["normal_image", "packaged_browser"]:
            i = phases[name]["isolation"]
            assert i["user"] == "10001:10001"
            assert all(
                i[k]
                for k in [
                    "read_only_root",
                    "all_capabilities_dropped",
                    "no_new_privileges",
                    "loopback_console_only",
                    "no_database_published",
                    "dedicated_bridge_loopback_default",
                    "intercontainer_communication_disabled",
                ]
            )
            assert not i["runtime_egress_firewall"]
    b = json.loads((folder / "browser/browser.json").read_bytes())
    assert len(b["checks"]) >= 53 and all(
        c["passed"] and c["observed"] == c["expected"] for c in b["checks"]
    )
    assert len(b["screenshots"]) == 7 and len(b["accessibility"]) == 7
    assert all(not a["violations"] and not a["incomplete"] for a in b["accessibility"])
    assert b["downstream_posts_before"] == b["downstream_posts_after"] == b["receiver_effects"] == 1
    assert b["packaged_gateway"] and b["test_expiry_role_is_restricted"]
    for name, expected in b["image_sha256"].items():
        assert hashlib.sha256((folder / "browser" / name).read_bytes()).hexdigest() == expected
    summary = b["financial_summary"]
    assert summary["original"]["consolidated_invoice_minor"] == 36800000
    assert summary["restated"]["consolidated_invoice_minor"] == 38800000
    assert summary["restated"]["allocated_cash_minor"] == 23000000
    assert summary["restated"]["elimination_minor"] == 2000000
    assert summary["original_report_unchanged"] and not summary["blocked_candidate_published"]
    assert {(r["code"], r["amount_minor"]) for r in summary["open_variances"]} == {
        ("erp_posting_difference", 500000),
        ("intercompany_unresolved", 800000),
    }
    for report in summary["builds"].values():
        nodes = report["dbt"]["results"]
        assert report["dbt"]["return_code"] == 0
        assert len([n for n in nodes if n["id"].startswith("model.")]) == 9
        assert len([n for n in nodes if n["id"].startswith("test.")]) == 9
        assert all(n["status"] in ["success", "pass"] for n in nodes)
        assert len(report["comparisons"]) == 7 and all(
            c["row_differences"] == 0 and c["exact_content_match"] for c in report["comparisons"]
        )
    return {
        "status": "passed",
        "lane": p["lane"],
        "browser_checks": len(b["checks"]),
        "screenshots": len(b["screenshots"]),
        "source_commit": p["source_commit"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--failed", action="store_true")
    parser.add_argument("--working-tree", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.folder, args.failed, args.working_tree)))
