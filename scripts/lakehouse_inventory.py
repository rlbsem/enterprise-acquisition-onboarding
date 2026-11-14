"""Fresh management-only residual inspection, separate from cleanup mutations."""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from lakehouse_native import CLI, ROOT, write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    work = Path(a.work).resolve()
    if ROOT / ".local" not in work.parents or Path(a.output).exists():
        raise ValueError("private_workspace_and_fresh_output_required")
    cfg = json.loads(Path(a.config).read_bytes())
    ledger = json.loads(Path(cfg["credit_ledger"]).read_bytes())
    principal = json.loads((work / "principal.private.json").read_bytes())
    manifest = json.loads((work / "manifest.json").read_bytes())
    cli = CLI(cfg, work)
    meta = cli.call(["metastores", "current"], "inventory-metastore")
    assert str(meta["workspace_id"]) == str(cfg["target"]["workspace_id"]), "workspace_pin_mismatch"
    schemas = cli.call(["schemas", "list", "workspace"], "inventory-schemas")
    remaining = [
        r["name"] for r in schemas if r["name"] in [manifest["schema"], "acq_lh_20261114a"]
    ]
    ws_principals = cli.call(["service-principals", "list"], "inventory-workspace-principals")
    account_principals = cli.call(
        ["account", "service-principals", "list"], "inventory-account-principals", account=True
    )

    def found(rows):
        return any(
            str(r.get("id")) == str(principal["id"])
            or r.get("applicationId") == principal["applicationId"]
            for r in rows
        )

    run_states = []
    for entry in ledger["submissions"]:
        state = cli.call(
            ["jobs", "get-run", str(entry["run_id"])], "inventory-run-" + str(entry["run_id"])
        )
        run_states.append(
            dict(
                run_id=entry["run_id"],
                life_cycle_state=state["state"]["life_cycle_state"],
                result_state=state["state"].get("result_state"),
            )
        )
    active = cli.call(
        ["jobs", "list-runs", "--active-only", "--limit", "20"], "inventory-active-runs"
    )
    saved = cli.call(["jobs", "list", "--limit", "20"], "inventory-saved-jobs")
    assets = cli.call(
        ["workspace", "list", "/Shared/acquisition-lakehouse"], "inventory-notebook-parent"
    )
    warehouses = cli.call(["warehouses", "list"], "inventory-warehouses")
    clusters = cli.call(["clusters", "list"], "inventory-classic-clusters")
    prefixes = [manifest["schema"], "acq_lh_20261114a"]
    owned_active = [
        r["run_id"] for r in active if any(r.get("run_name", "").startswith(n) for n in prefixes)
    ]
    owned_saved = [
        r["job_id"]
        for r in saved
        if any(r.get("settings", {}).get("name", "").startswith(n) for n in prefixes)
    ]
    owned_assets = [
        r["path"].rsplit("/", 1)[-1] for r in assets if r["path"].rsplit("/", 1)[-1] in prefixes
    ]
    success = (
        not remaining
        and not found(ws_principals)
        and not found(account_principals)
        and not owned_active
        and not owned_saved
        and not owned_assets
        and all(
            r["life_cycle_state"] in {"TERMINATED", "INTERNAL_ERROR", "SKIPPED"} for r in run_states
        )
    )
    report = dict(
        schema="lakehouse-post-teardown.v1",
        source_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        observed_at_utc=datetime.now(UTC).isoformat(),
        read_only=True,
        compute_started=False,
        logical_owned_resources_absent=success,
        remaining_owned_schemas=remaining,
        owned_workspace_principal_present=found(ws_principals),
        owned_account_principal_present=found(account_principals),
        active_owned_runs=owned_active,
        saved_owned_jobs=owned_saved,
        remaining_owned_notebook_directories=owned_assets,
        run_states=run_states,
        existing_warehouses=[
            dict(
                state=w.get("state"),
                active_clusters=w.get("num_clusters"),
                serverless=w.get("enable_serverless_compute"),
            )
            for w in warehouses
        ],
        classic_cluster_count=len(clusters),
        empty_shared_parent_retained=not assets,
        physical_storage_erasure_verified=False,
        billing_clearance=False,
    )
    write(Path(a.output), report)
    print(
        json.dumps(
            dict(
                logical_owned_resources_absent=success,
                known_runs=len(run_states),
                compute_started=False,
                billing_clearance=False,
            )
        )
    )
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
