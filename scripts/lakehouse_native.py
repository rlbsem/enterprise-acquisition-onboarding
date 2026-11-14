"""Bounded, exact-source native Jobs driver. Credentials remain in protected CLI storage."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import UTC, datetime

from onboarding.lakehouse_plan import export_fixture, sha, job_spec, namespace, credit_projection
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
    p.add_argument("action", choices=["prepare", "upload", "submit", "observe"])
    p.add_argument("--work", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--schema")
    p.add_argument("--companies", type=int, default=3)
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
        path = "/Shared/acquisition-lakehouse/" + a.schema + "/acceptance"
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
    elif a.action == "submit":
        preflight = json.loads(Path(cfg["preflight_record"]).read_bytes())
        gate = native_gate(preflight, cfg["owner_observation"], cfg["cost_plan"], datetime.now(UTC))
        if not gate["eligible_for_separately_authorized_bounded_pilot"]:
            raise ValueError("native_preflight_gate_closed:" + ",".join(gate["reasons"]))
        if a.phase not in ["pilot", "observer", "cleanup"]:
            pilot = json.loads((work / "pilot-submitted.json").read_bytes())["run_id"]
            observation = json.loads((work / f"run-{pilot}-observation.json").read_bytes())
            if observation.get("state", {}).get("result_state") != "SUCCESS":
                raise ValueError("pilot_acceptance_required_before_expansion")
        spec = job_spec(
            m["notebook_path"],
            m["schema"],
            a.phase,
            m["source_commit"],
            m["fixture_sha256"],
            seconds=300 if a.phase in ["observer", "cleanup"] else 900,
        )
        spec["idempotency_token"] = sha([m["schema"], a.phase, m["source_commit"]])
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
