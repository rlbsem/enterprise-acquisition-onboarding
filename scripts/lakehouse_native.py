"""Bounded, exact-source native Jobs driver. Credentials remain in protected CLI storage."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from decimal import Decimal
from datetime import UTC, datetime

from onboarding.lakehouse_plan import (
    export_fixture,
    sha,
    job_spec,
    namespace,
    credit_projection,
    admit_credit_step,
)
from onboarding.lakehouse_preflight import native_gate

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def source_revision():
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for name in [
        "scripts/lakehouse_native.py",
        "scripts/lakehouse_notebook.py",
        "src/onboarding/lakehouse_plan.py",
        "src/onboarding/portfolio_oracle.py",
        "src/onboarding/portfolio_fixtures.py",
    ]:
        original = subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT)
        if original != (ROOT / name).read_bytes():
            raise ValueError("committed_source_required:" + name)
    return revision


class CLI:
    def __init__(self, config, work):
        self.config, self.work = config, work
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("DATABRICKS_")}
        self.env.update(
            DATABRICKS_AUTH_STORAGE="secure", DATABRICKS_CONFIG_FILE=config["config_file"]
        )

    def call(self, args, label, account=False):
        # Raw diagnostics are private; no auth token/env/secret commands are used.
        result = subprocess.run(
            [
                self.config["cli"],
                *args,
                "--profile",
                self.config["account_profile" if account else "workspace_profile"],
                "--output",
                "json",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=100,
        )
        (self.work / (label + ".stdout.private")).write_text(result.stdout, encoding="utf-8")
        (self.work / (label + ".stderr.private")).write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("native_cli_failed:" + label + "; inspect private diagnostics")
        return json.loads(result.stdout) if result.stdout.strip() else {}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=[
            "prepare",
            "upload",
            "submit",
            "observe",
            "governance-setup",
            "governance-retire",
            "notebook-retire",
        ],
    )
    p.add_argument("--work", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--schema")
    p.add_argument("--companies", type=int, default=3)
    p.add_argument("--from-pilot")
    p.add_argument(
        "--phase",
        choices=["pilot", "fault", "observer", "recovery", "governance", "scale", "cleanup"],
        default="pilot",
    )
    p.add_argument("--run-id", type=int)
    a = p.parse_args()
    work = Path(a.work).resolve()
    if ROOT / ".local" not in work.parents:
        raise ValueError("private_workspace_must_be_under_ignored_local")
    cfg = json.loads(Path(a.config).read_bytes())
    work.mkdir(parents=True, exist_ok=True)
    if a.action == "prepare":
        namespace(a.schema)
        if (work / "manifest.json").exists():
            raise ValueError("fresh_run_required")
        revision = source_revision()
        fixture = export_fixture(a.companies)
        notebook = (ROOT / "scripts/lakehouse_notebook.py").read_text(encoding="utf-8")
        encoded = base64.b64encode(json.dumps(fixture).encode()).decode()
        notebook = notebook.replace(
            "import hashlib",
            f"import base64\nimport json\nFIXTURE = json.loads(base64.b64decode('{encoded}'))\nimport hashlib",
            1,
        )
        path = "/Shared/acquisition-lakehouse/" + a.schema + "/acceptance-" + revision[:12]
        write(work / "fixture.json", fixture)
        (work / "notebook.py").write_text(notebook, encoding="utf-8", newline="\n")
        write(
            work / "manifest.json",
            dict(
                schema=a.schema,
                notebook_path=path,
                source_commit=revision,
                fixture_sha256=sha(fixture),
                notebook_sha256=hashlib.sha256(notebook.encode()).hexdigest(),
                pilot_credit_allowance_usd=20,
                total_credit_allowance_usd=300,
                pilot_timeout_projection_usd=credit_projection(1200),
                no_payment_method_owner_confirmed=True,
                created_at_utc=datetime.now(UTC).isoformat(),
            ),
        )
        if a.from_pilot:
            parent = Path(a.from_pilot).resolve()
            prior = json.loads((parent / "manifest.json").read_bytes())
            if prior["schema"] != a.schema or prior["fixture_sha256"] != sha(fixture):
                raise ValueError("parent_pilot_fixture_mismatch")
            submission = json.loads((parent / "pilot-submitted.json").read_bytes())
            observed = json.loads(
                (parent / f"run-{submission['run_id']}-observation.json").read_bytes()
            )
            if observed["state"].get("result_state") != "SUCCESS" or not all(
                t.get("result", {}).get("fixture_sha256") == sha(fixture) for t in observed["tasks"]
            ):
                raise ValueError("parent_pilot_not_accepted")
            write(work / "pilot-submitted.json", submission)
            write(work / f"run-{submission['run_id']}-observation.json", observed)
        print(json.dumps(dict(status="prepared", source=revision, namespace=a.schema)))
        return
    m = json.loads((work / "manifest.json").read_bytes())
    namespace(m["schema"])
    if hashlib.sha256((work / "notebook.py").read_bytes()).hexdigest() != m["notebook_sha256"]:
        raise ValueError("uploaded_notebook_changed")
    cli = CLI(cfg, work)
    if a.action == "upload":
        cli.call(
            ["workspace", "mkdirs", str(Path(m["notebook_path"]).parent).replace("\\", "/")],
            "mkdir",
        )
        cli.call(
            [
                "workspace",
                "import",
                m["notebook_path"],
                "--file",
                str(work / "notebook.py"),
                "--format",
                "SOURCE",
                "--language",
                "PYTHON",
            ],
            "upload",
        )
        print('{"status":"uploaded_no_compute_started"}')
    elif a.action == "governance-setup":
        pilot = json.loads((work / "pilot-submitted.json").read_bytes())["run_id"]
        observed = json.loads((work / f"run-{pilot}-observation.json").read_bytes())
        if observed.get("state", {}).get("result_state") != "SUCCESS":
            raise ValueError("pilot_acceptance_required")
        principal_path = work / "principal.private.json"
        if principal_path.exists():
            raise ValueError("dedicated_principal_already_recorded")
        principal = cli.call(
            [
                "service-principals",
                "create",
                "--display-name",
                m["schema"] + "-consumer",
                "--active",
            ],
            "create-consumer",
        )
        write(principal_path, principal)
        app = principal["applicationId"]
        for kind, name, privileges in [
            ("catalog", "workspace", ["USE_CATALOG"]),
            ("schema", namespace(m["schema"]), ["USE_SCHEMA"]),
            ("table", namespace(m["schema"]) + ".company_view", ["SELECT"]),
        ]:
            request = work / ("grant-" + kind + ".private.json")
            write(request, dict(changes=[dict(principal=app, add=privileges)]))
            cli.call(
                ["grants", "update", kind, name, "--json", "@" + str(request)], "grant-" + kind
            )
        info = cli.call(["workspace", "get-status", m["notebook_path"]], "notebook-status")
        request = work / "notebook-permission.private.json"
        write(
            request,
            dict(
                access_control_list=[dict(service_principal_name=app, permission_level="CAN_READ")]
            ),
        )
        cli.call(
            [
                "permissions",
                "update",
                "notebooks",
                str(info["object_id"]),
                "--json",
                "@" + str(request),
            ],
            "grant-notebook",
        )
        print('{"dedicated_consumer_created":true,"scope":"catalog-use/schema-use/one-view-read"}')
    elif a.action == "governance-retire":
        principal = json.loads((work / "principal.private.json").read_bytes())
        actual = cli.call(
            ["service-principals", "get", str(principal["id"])], "consumer-before-retire"
        )
        if (
            actual.get("displayName") != m["schema"] + "-consumer"
            or actual.get("applicationId") != principal["applicationId"]
        ):
            raise ValueError("principal_ownership_mismatch")
        request = work / "revoke-catalog.private.json"
        write(
            request,
            dict(changes=[dict(principal=principal["applicationId"], remove=["USE_CATALOG"])]),
        )
        cli.call(
            ["grants", "update", "catalog", "workspace", "--json", "@" + str(request)],
            "revoke-catalog",
        )
        cli.call(["service-principals", "delete", str(principal["id"])], "retire-consumer")
        remaining = cli.call(["service-principals", "list"], "consumer-after-retire")
        assert all(r["id"] != principal["id"] for r in remaining), "consumer_still_present"
        print(
            '{"dedicated_workspace_consumer_absent":true,"account_identity_absence_not_assumed":true}'
        )
    elif a.action == "notebook-retire":
        # Only the exact run directory, after evidence export and namespace teardown.
        directory = m["notebook_path"].rsplit("/", 1)[0]
        assert directory == "/Shared/acquisition-lakehouse/" + m["schema"]
        cli.call(["workspace", "delete", directory, "--recursive"], "retire-notebook")
        listing = cli.call(
            ["workspace", "list", "/Shared/acquisition-lakehouse"], "notebook-after-retire"
        )
        assert all(r["path"] != directory for r in listing), "notebook_directory_still_present"
        print('{"exact_notebook_directory_absent":true}')
    elif a.action == "submit":
        ledger = json.loads(Path(cfg["credit_ledger"]).read_bytes())
        expansion = (
            a.phase == "scale"
            or json.loads((work / "fixture.json").read_bytes())["company_count"] > 3
        )
        seconds = 300 if a.phase in ["observer", "cleanup", "fault", "governance"] else 900
        reserve = credit_projection(seconds, reserve="0")
        admit_credit_step(ledger, reserve, expansion=expansion)
        preflight = json.loads(Path(cfg["preflight_record"]).read_bytes())
        gate = native_gate(preflight, cfg["owner_observation"], cfg["cost_plan"], datetime.now(UTC))
        if not gate["eligible_for_separately_authorized_bounded_pilot"]:
            raise ValueError("native_preflight_gate_closed:" + ",".join(gate["reasons"]))
        if a.phase not in ["pilot", "observer", "cleanup"]:
            pilot = json.loads((work / "pilot-submitted.json").read_bytes())["run_id"]
            observation = json.loads((work / f"run-{pilot}-observation.json").read_bytes())
            if observation.get("state", {}).get("result_state") != "SUCCESS":
                raise ValueError("pilot_acceptance_required_before_expansion")
            remote = cli.call(["jobs", "get-run", str(pilot)], "verify-parent-pilot")
            if remote.get("state", {}).get("result_state") != "SUCCESS":
                raise ValueError("native_parent_pilot_not_successful")
        spec = job_spec(
            m["notebook_path"],
            m["schema"],
            a.phase,
            m["source_commit"],
            m["fixture_sha256"],
            seconds=seconds,
        )
        spec["idempotency_token"] = sha([m["schema"], a.phase, m["source_commit"]])
        if a.phase == "governance":
            principal = json.loads((work / "principal.private.json").read_bytes())
            spec["run_as"] = dict(service_principal_name=principal["applicationId"])
        destination = work / (a.phase + "-submitted.json")
        if destination.exists():
            raise ValueError("run_already_submitted_observe_existing_id")
        write(work / (a.phase + "-request.json"), spec)
        response = cli.call(
            [
                "jobs",
                "submit",
                "--json",
                "@" + str(work / (a.phase + "-request.json")),
                "--no-wait",
            ],
            a.phase + "-submit",
        )
        write(destination, response)
        ledger["pending_reserved_usd"] = str(
            Decimal(str(ledger["pending_reserved_usd"])) + Decimal(reserve)
        )
        ledger.setdefault("submissions", []).append(
            dict(run_id=response["run_id"], phase=a.phase, reserved_usd=reserve)
        )
        write(Path(cfg["credit_ledger"]), ledger)
        print(json.dumps(dict(phase=a.phase, run_id=response["run_id"])))
    else:
        if not a.run_id:
            raise ValueError("existing_run_id_required")
        state = cli.call(["jobs", "get-run", str(a.run_id)], "run-" + str(a.run_id))
        public = dict(
            run_id=a.run_id, state=state.get("state"), source_commit=m["source_commit"], tasks=[]
        )
        for t in state.get("tasks", []):
            task = dict(
                task_key=t["task_key"],
                run_id=t["run_id"],
                state=t.get("state"),
                execution_duration_ms=t.get("execution_duration"),
                setup_duration_ms=t.get("setup_duration"),
            )
            if t.get("state", {}).get("life_cycle_state") in [
                "TERMINATED",
                "SKIPPED",
                "INTERNAL_ERROR",
            ]:
                result = cli.call(
                    ["jobs", "get-run-output", str(t["run_id"])], "output-" + str(t["run_id"])
                )
                if "result" in result.get("notebook_output", {}):
                    task["result"] = json.loads(result["notebook_output"]["result"])
                else:
                    task["error"] = result.get("error", "no_notebook_result")
            public["tasks"].append(task)
        write(work / ("run-" + str(a.run_id) + "-observation.json"), public)
        print(
            json.dumps(
                dict(
                    run_id=a.run_id,
                    state=state.get("state"),
                    task_results=[
                        t.get("result", {}).get("status", t.get("error")) for t in public["tasks"]
                    ],
                )
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
