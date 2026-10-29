"""Verify immutable multi-company records, source revisions and independent recorded arithmetic."""

import argparse
import hashlib
import json
import subprocess
import statistics
from pathlib import Path
from onboarding.portfolio_fixtures import Portfolio, ORIGINAL, RESTATED, PERIODS
from onboarding.portfolio_oracle import calculate

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    p.add_argument("--require-scale", action="store_true")
    a = p.parse_args()
    folder = a.folder.resolve()
    inventory = json.loads((folder / "artifact-integrity.json").read_bytes())
    actual = {
        f.relative_to(folder).as_posix()
        for f in folder.rglob("*")
        if f.is_file() and f.name != "artifact-integrity.json"
    }
    assert set(inventory) == actual
    for name, value in inventory.items():
        path = (folder / name).resolve()
        assert path.is_relative_to(folder)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == value, name
    summary = json.loads((folder / "summary.json").read_bytes())
    binding = summary["source_binding"]
    for name, value in binding["source_hashes"].items():
        assert (
            hashlib.sha256(
                subprocess.check_output(
                    ["git", "show", binding["source_commit"] + ":" + name], cwd=ROOT
                )
            ).hexdigest()
            == value
        ), name
    sizes = set()
    runs = 0
    witnesses = 0
    for file in folder.glob("companies-*.json"):
        r = json.loads(file.read_bytes())
        spec = Portfolio(r["company_count"])
        assert r["source_binding"] == binding and r["synthetic"] and r["native_vendor_calls"] == 0
        assert r["owned_resources_cleaned"] and r["teardown"]["remaining_listeners"] == 0
        assert r["contention_probe"]["healthy_admission_completed_while_other_lock_held"]
        assert r["original_publication_unchanged"] and r["original_input_membership_unchanged"]
        assert r["identity"]["cross_company_collisions"] == 0
        assert r["identity"]["companies_reusing_local_100"] == r["company_count"]
        request_samples = [
            c["admission_seconds"]
            for c in r["companies"]
            if not c["admission"].get("not_requested")
        ]
        assert r["metrics"]["admission_latency_seconds"] == request_samples
        assert r["metrics"]["admission_request_count"] == len(request_samples)
        assert r["metrics"]["admission_latency_median"] == statistics.median(request_samples)
        assert r["metrics"]["pending_without_admission_request"] == r["company_count"] - len(
            request_samples
        )
        assert r["healthy_companies_completed_before_source_restart"] == sum(
            spec.expected_admitted(i) for i in range(spec.count)
        )
        for name in ["original_oracle", "restated_oracle"]:
            assert (
                r[name]["status"] == "passed"
                and r[name]["incorrect_amounts"] == r[name]["incorrect_source_memberships"] == 0
            )
        if r["company_count"] >= 10:
            assert r["delivery"]["exhausted_queues"] == 1 and r["delivery"]["healthy_confirmed"] > 0
            assert (
                r["delivery"]["lost_ack_exercised"]
                and r["original_oracle"]["supported_eliminations"] > 0
            )
        if r["source_observations"] is not None:
            witnesses += 1
            documents = r["source_observations"]

            def keys(rows):
                return {(b["company"], b["kind"], b["source_id"], b["revision"]): b for b in rows}

            assert keys([d["body"] for d in documents]) == keys(
                [*spec.financial(), *spec.corrections()]
            )
            for d in documents:
                assert (
                    hashlib.sha256(
                        json.dumps(
                            d["body"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
                        ).encode()
                    ).hexdigest()
                    == d["hash"]
                )
            for name, cutoff, recovered in [
                ("original", ORIGINAL, False),
                ("restated", RESTATED, True),
            ]:
                expected = calculate(
                    documents,
                    cutoff,
                    spec.companies,
                    {
                        c[0]: spec.expected_admitted(i, recovered)
                        for i, c in enumerate(spec.companies)
                    },
                    PERIODS,
                )
                assert (
                    expected["totals"]
                    == r[name]["results"]["portfolio_totals"]
                    == r[name + "_oracle"]["totals"]
                )
                ledger = {
                    (x["company"], x["kind"], x["source_id"], x["revision"]): x
                    for x in r["control_financial_membership"]
                    if x["status"] == "accepted"
                }

                def ids(bodies):
                    return sorted(
                        ledger[(b["company"], b["kind"], b["source_id"], b["revision"])]["id"]
                        for b in bodies
                    )

                expected_invoices = [
                    {**row, "source_event_ids": ids(bodies)} for row, bodies in expected["invoices"]
                ]

                def canonical(rows):
                    return sorted(rows, key=lambda x: json.dumps(x, sort_keys=True))

                assert canonical(expected_invoices) == canonical(r[name]["results"]["fct_invoices"])
        if "browser" in r:
            assert not r["browser"]["script_errors"] and all(
                c["passed"] for c in r["browser"]["checks"]
            )
            assert all(
                not s["violations"] and s["unresolved_checks"] == 0
                for s in r["browser"]["accessibility"]
            )
        sizes.add(spec.count)
        runs += 1
    if a.require_scale:
        assert sizes >= {3, 10, 25, 50} and witnesses > 0
    preserved = json.loads((ROOT / "docs/evidence/multi-company/preserved-files.json").read_bytes())
    for name, value in preserved.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value, (
            "historical_evidence_changed:" + name
        )
    print(
        json.dumps(
            dict(
                status="passed",
                runs=runs,
                sizes=sorted(sizes),
                source_witnesses=witnesses,
                artifacts=len(inventory),
                preserved_files=len(preserved),
            )
        )
    )


if __name__ == "__main__":
    main()
