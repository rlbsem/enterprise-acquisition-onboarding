"""Ownership-checked Unity Catalog API cleanup; never starts compute."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from onboarding.lakehouse_plan import validate_schema_retirement
from lakehouse_native import CLI, ROOT, write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    work = Path(a.work).resolve()
    if ROOT / ".local" not in work.parents:
        raise ValueError("private_workspace_required")
    cfg = json.loads(Path(a.config).read_bytes())
    manifest = json.loads((work / "manifest.json").read_bytes())
    ledger = json.loads(Path(cfg["credit_ledger"]).read_bytes())
    cli = CLI(cfg, work)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for name in [
        "scripts/lakehouse_retire.py",
        "scripts/lakehouse_native.py",
        "src/onboarding/lakehouse_plan.py",
    ]:
        if (
            subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT)
            != (ROOT / name).read_bytes()
        ):
            raise ValueError("committed_cleanup_source_required")
    evidence = Path(a.evidence)
    archived = set()
    for path in evidence.glob("[0-9]*.json"):
        relative = path.resolve().relative_to(ROOT).as_posix()
        if (
            subprocess.check_output(["git", "show", revision + ":" + relative], cwd=ROOT)
            != path.read_bytes()
        ):
            raise ValueError("committed_native_evidence_required")
        archived.add(json.loads(path.read_bytes())["run_id"])
    for entry in ledger["submissions"]:
        if entry["run_id"] not in archived:
            raise ValueError("native_run_not_exported:" + str(entry["run_id"]))
        state = cli.call(
            ["jobs", "get-run", str(entry["run_id"])], "retire-run-" + str(entry["run_id"])
        )
        if state.get("state", {}).get("life_cycle_state") not in {
            "TERMINATED",
            "INTERNAL_ERROR",
            "SKIPPED",
        }:
            raise ValueError("active_native_run_refuses_teardown")
    metastore = cli.call(["metastores", "current"], "retire-metastore")
    if str(metastore["workspace_id"]) != str(cfg["target"]["workspace_id"]):
        raise ValueError("workspace_pin_mismatch")
    actor = cli.call(["current-user", "me"], "retire-actor")
    schema = cli.call(["schemas", "get", "workspace." + manifest["schema"]], "retire-schema-before")
    tables = cli.call(["tables", "list", "workspace", manifest["schema"]], "retire-tables-before")
    volumes = cli.call(
        ["volumes", "list", "workspace", manifest["schema"]], "retire-volumes-before"
    )
    ns = validate_schema_retirement(manifest, schema, actor, tables, volumes)
    report = dict(
        schema="lakehouse-retirement.v1",
        source_commit=revision,
        fixture_sha256=manifest["fixture_sha256"],
        namespace=ns,
        observed_at_utc=datetime.now(UTC).isoformat(),
        tables=[dict(name=t["name"], type=t["table_type"]) for t in tables],
        volumes=[dict(name=v["name"], type=v["volume_type"]) for v in volumes],
        all_submitted_runs_terminal=True,
        all_submitted_runs_exported=True,
        compute_started=False,
        deleted=False,
        physical_storage_erasure_verified=False,
        billing_clearance=False,
    )
    if a.execute:
        if (work / "schema-retirement.json").exists():
            raise ValueError("fresh_retirement_record_required")
        cli.call(["schemas", "delete", ns, "--force"], "retire-exact-schema")
        after = cli.call(["schemas", "list", "workspace"], "retire-schemas-independent-after")
        assert all(s["name"] != manifest["schema"] for s in after), "schema_still_listed"
        report.update(
            deleted=True,
            independent_namespace_absence_verified=True,
            remaining_workspace_schemas=len(after),
        )
    report["private_schema_response_sha256"] = hashlib.sha256(
        (work / "retire-schema-before.stdout.private").read_bytes()
    ).hexdigest()
    write(
        work / ("schema-retirement.json" if a.execute else "schema-retirement-review.json"), report
    )
    print(json.dumps(dict(deleted=report["deleted"], compute_started=False, namespace=ns)))


if __name__ == "__main__":
    main()
