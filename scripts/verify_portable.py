"""Execute normal startup/restart and the optional browser image; publish sanitized proof only."""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from onboarding.sandbox import child_env  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, default=str) + "\n").encode())


def source_hashes():
    names = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True
    ).splitlines()
    return {
        n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
        for n in sorted(set(names))
        if n.startswith(("src/", "warehouse/", "scripts/", "tests/", ".github/"))
        or n
        in {
            "Dockerfile",
            ".dockerignore",
            "compose.yaml",
            "compose.acceptance.yaml",
            "requirements.lock",
            "pyproject.toml",
        }
    }


class Lane:
    def __init__(self, workspace, native=False):
        self.work, self.native = workspace, native
        self.state = workspace / "state"
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.project = "acqportable" + uuid4().hex[:10]
        self.process = self.log = None
        self.acceptance = False
        self.work.mkdir(parents=True)
        self.env = {**os.environ, "ACQUISITION_DEMO_PORT": str(self.port)}

    def compose(self, *args):
        files = ["-f", str(ROOT / "compose.yaml")]
        if self.acceptance:
            files += ["-f", str(ROOT / "compose.acceptance.yaml")]
        return ["docker", "compose", "-p", self.project, *files, *args]

    def run(self, command, name, timeout=900):
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if result.returncode:
            (self.work / (name + "-private.log")).write_bytes(result.stdout + result.stderr)
            raise RuntimeError(name + "_failed_inspect_private_log")
        return result.stdout

    def cli(self, *args):
        if self.native:
            return self.run(
                [sys.executable, "-m", "onboarding.portable", *args, "--state", str(self.state)],
                "private_cli",
            )
        return self.run(
            self.compose("exec", "-T", "demo", "python", "-m", "onboarding.portable", *args),
            "private_cli",
        )

    def start(self, acceptance=False):
        self.acceptance = acceptance
        if self.native:
            self.log = (self.work / "runtime-private.log").open("ab")
            command = [
                sys.executable,
                "-m",
                "onboarding.portable",
                "serve",
                "--state",
                str(self.state),
                "--port",
                str(self.port),
            ] + (["--acceptance"] if acceptance else [])
            extra = {
                "PYTHONPATH": str(ROOT / "src"),
                "PG_BIN": os.environ.get("PG_BIN", ""),
                "PLAYWRIGHT_BROWSERS_PATH": os.environ.get(
                    "PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".local/browsers")
                ),
            }
            self.process = subprocess.Popen(
                command, cwd=ROOT, env=child_env(extra), stdout=self.log, stderr=self.log
            )
        else:
            self.run(self.compose("build", "demo"), "image_build", timeout=1200)
            self.run(
                self.compose("up", "-d", "--wait", "--wait-timeout", "240", "demo"),
                "startup",
                timeout=270,
            )
        deadline = time.monotonic() + 240
        with httpx.Client(trust_env=False, timeout=2) as client:
            while time.monotonic() < deadline:
                if self.native and self.process.poll() is not None:
                    raise RuntimeError("native_startup_failed_inspect_private_log")
                try:
                    if client.get(self.url + "/health").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(1)
        raise RuntimeError("startup_deadline_exceeded")

    def credentials(self, user):
        return json.loads(self.cli("credentials", "--user", user))

    def inspect(self):
        return json.loads(self.cli("inspect"))

    def stop(self):
        if self.native:
            if self.process and self.process.poll() is None:
                self.cli("stop")
                self.process.wait(timeout=45)
            assert self.process.returncode == 0, "native_stop_failed"
            if self.log:
                self.log.close()
            result = json.loads((self.state / "shutdown.json").read_text())
        else:
            self.run(self.compose("stop", "--timeout", "45", "demo"), "stop", timeout=60)
            cid = (
                self.run(self.compose("ps", "--all", "--quiet", "demo"), "container_id")
                .decode()
                .strip()
            )
            info = json.loads(self.run(["docker", "inspect", cid], "stopped_inspection"))[0]
            assert not info["State"]["Running"] and info["State"]["ExitCode"] == 0
            target = self.work / "shutdown.json"
            self.run(["docker", "cp", cid + ":/state/shutdown.json", str(target)], "shutdown_copy")
            result = json.loads(target.read_text())
        assert result["owned_database_and_http_processes_stopped"]
        with httpx.Client(timeout=2, trust_env=False) as client:
            try:
                r = client.get(self.url + "/health")
            except httpx.HTTPError:
                pass
            else:
                assert r.status_code != 200, "stopped_console_still_ready"
        return {"clean_exit": True, "owned_services_stopped": True}

    def browser(self, output):
        if self.native:
            self.run(
                [
                    sys.executable,
                    "-m",
                    "onboarding.portable_acceptance",
                    "--state",
                    str(self.state),
                    "--output",
                    str(output / "browser.json"),
                ],
                "browser",
                timeout=240,
            )
        else:
            self.run(
                self.compose(
                    "exec",
                    "-T",
                    "demo",
                    "python",
                    "-m",
                    "onboarding.portable_acceptance",
                    "--output",
                    "/state/browser-proof/browser.json",
                ),
                "browser",
                timeout=240,
            )
            cid = self.run(self.compose("ps", "--quiet", "demo"), "container_id").decode().strip()
            output.mkdir(parents=True)
            self.run(["docker", "cp", cid + ":/state/browser-proof/.", str(output)], "browser_copy")
        return json.loads((output / "browser.json").read_text())

    def isolation(self):
        if self.native:
            return {"lane": "native_loopback; Docker controls not tested on this host"}
        cid = self.run(self.compose("ps", "--quiet", "demo"), "container_id").decode().strip()
        c = json.loads(self.run(["docker", "inspect", cid], "container_inspection"))[0]
        h = c["HostConfig"]
        assert c["Config"]["User"] == "10001:10001" and h["ReadonlyRootfs"]
        assert not h["Privileged"] and "ALL" in h["CapDrop"]
        assert any(x.startswith("no-new-privileges") for x in h["SecurityOpt"])
        assert set(h["PortBindings"]) == {"8080/tcp"}
        assert h["PortBindings"]["8080/tcp"] == [
            {"HostIp": "127.0.0.1", "HostPort": str(self.port)}
        ]
        networks = [
            json.loads(self.run(["docker", "network", "inspect", n], "network_inspection"))[0]
            for n in c["NetworkSettings"]["Networks"]
        ]
        assert all(n["Internal"] for n in networks)
        assert h["PidsLimit"] == 256 and h["Memory"] == 1536 * 1024**2
        return {
            "user": c["Config"]["User"],
            "read_only_root": True,
            "all_capabilities_dropped": True,
            "no_new_privileges": True,
            "loopback_console_only": True,
            "internal_network": True,
            "no_database_published": True,
            "memory_limit_bytes": h["Memory"],
            "pids_limit": h["PidsLimit"],
            "image_id": c["Image"],
        }

    def cleanup(self):
        if self.native:
            if self.process and self.process.poll() is None:
                try:
                    self.stop()
                except Exception:
                    self.process.terminate()
                    self.process.wait(timeout=10)
                    raise
            return {"owned_process_exited": self.process is None or self.process.poll() is not None}
        self.run(
            self.compose("down", "--volumes", "--remove-orphans", "--timeout", "45"),
            "teardown",
            timeout=90,
        )
        residual = {}
        for kind, command in {
            "containers": ["docker", "ps", "-aq"],
            "networks": ["docker", "network", "ls", "-q"],
            "volumes": ["docker", "volume", "ls", "-q"],
        }.items():
            residual[kind] = (
                self.run(
                    [*command, "--filter", "label=com.docker.compose.project=" + self.project],
                    "independent_inventory",
                )
                .decode()
                .splitlines()
            )
        assert not any(residual.values()), "residual_project_resources"
        return {"independent_label_inventory": residual, "verified_absent": True}


def probe(lane):
    before = lane.inspect()
    assert len(before["companies"]) == 3 and len(before["publications"]) == 2
    assert before["receiver_posts"] == before["receiver_effects"] == 1
    assert before["console_read_role_restricted"] and before["review_decisions"] == 0
    assert before["financial"]["original"]["consolidated_invoice_minor"] == 36800000
    assert before["financial"]["restated"]["consolidated_invoice_minor"] == 38800000
    assert before["financial"]["restated"]["allocated_cash_minor"] == 23000000
    credential = lane.credentials("sponsor")
    with httpx.Client(
        base_url=lane.url, trust_env=False, timeout=10, headers={"Origin": lane.url}
    ) as client:
        assert client.get("/console").status_code == 303
        assert client.get("/console/api/overview").status_code == 401
        r = client.post(
            "/console/api/login", json={k: credential[k] for k in ["username", "password"]}
        )
        assert (
            r.status_code == 200
            and "HttpOnly" in r.headers["set-cookie"]
            and "SameSite=strict" in r.headers["set-cookie"]
        )
        assert len(client.get("/console/api/overview").json()["companies"]) == 3
        assert client.get("/console/api/session").headers["content-security-policy"]
        assert client.get("/console", headers={"Host": "attacker.example"}).status_code == 400
        for path in ["/ingest", "/api/config", "/dispatch", "/openapi.json"]:
            assert client.post(path, json={}).status_code == 404
        assert (
            client.post(
                "/console/api/login",
                json={k: credential[k] for k in ["username", "password"]},
                headers={"Origin": "http://attacker.example"},
            ).status_code
            == 403
        )
        old_cookie = client.cookies.get("acquisition_session")
    return before, credential, old_cookie


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--native", action="store_true")
    a = p.parse_args()
    if a.workspace.exists() or a.output.exists():
        raise ValueError("fresh_workspace_and_output_required")
    a.workspace.mkdir(parents=True)
    a.output.mkdir(parents=True)
    sources = source_hashes()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = {
        "source_commit": revision,
        "source_sha256": sources,
        "started_at": datetime.now(UTC).isoformat(),
        "lane": "native_local" if a.native else "actual_docker_compose",
        "native_vendor_calls": 0,
        "cloud_resources": False,
        "independent_architecture_audit": False,
        "phases": [],
        "cleanup": [],
    }
    if not a.native:
        version = subprocess.check_output(
            ["docker", "version", "--format", "{{.Server.Version}}"], text=True
        ).strip()
        assert int(version.split(".")[0]) >= 28, "Docker_Engine_28_or_newer_required"
        report["docker_engine"] = version
        report["compose"] = subprocess.check_output(
            ["docker", "compose", "version", "--short"], text=True
        ).strip()
    lanes = []
    try:
        normal = Lane(a.workspace / "normal", a.native)
        lanes.append(normal)
        normal.start()
        initial, credential, cookie = probe(normal)
        report["phases"].append(
            {"name": "normal_image", "inspection": initial, "isolation": normal.isolation()}
        )
        report["phases"].append({"name": "normal_shutdown", **normal.stop()})
        normal.start()
        fresh, fresh_credential, _ = probe(normal)
        assert (
            initial["run_id"] != fresh["run_id"]
            and credential["password"] != fresh_credential["password"]
        )
        assert initial["financial"] == fresh["financial"]
        with httpx.Client(
            base_url=normal.url, trust_env=False, headers={"Origin": normal.url}
        ) as client:
            assert (
                client.get(
                    "/console/api/overview", headers={"Cookie": "acquisition_session=" + cookie}
                ).status_code
                == 401
            )
            assert (
                client.post(
                    "/console/api/login", json={k: credential[k] for k in ["username", "password"]}
                ).status_code
                == 401
            )
        report["phases"].append(
            {
                "name": "fresh_restart",
                "new_private_credentials": True,
                "old_session_rejected": True,
                "old_credential_rejected": True,
                "financial_parity": True,
            }
        )
        report["phases"].append({"name": "restarted_shutdown", **normal.stop()})
        report["cleanup"].append(normal.cleanup())
        browser = Lane(a.workspace / "browser", a.native)
        lanes.append(browser)
        browser.start(acceptance=True)
        observed = browser.inspect()
        expected = {
            n: h
            for n, h in sources.items()
            if n.startswith(("src/", "warehouse/"))
            and Path(n).suffix in {".py", ".sql", ".html", ".js", ".css", ".yml"}
        }
        assert expected == observed["source_sha256"], "image_source_not_exact_checkout"
        proof = browser.browser(a.output / "browser")
        assert all(c["passed"] for c in proof["checks"])
        report["phases"].append(
            {
                "name": "packaged_browser",
                "checks": len(proof["checks"]),
                "accessibility_views": len(proof["accessibility"]),
                "screenshots": len(proof["screenshots"]),
                "downstream_posts_unchanged": proof["downstream_posts_before"]
                == proof["downstream_posts_after"]
                == 1,
                "isolation": browser.isolation(),
            }
        )
        report["phases"].append({"name": "browser_shutdown", **browser.stop()})
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        raise
    finally:
        for lane in lanes:
            try:
                cleanup = lane.cleanup()
                if cleanup not in report["cleanup"]:
                    report["cleanup"].append(cleanup)
            except Exception as error:
                report["status"] = "failed"
                report["cleanup"].append(
                    {"verified_absent": False, "error_type": type(error).__name__}
                )
        report["finished_at"] = datetime.now(UTC).isoformat()
        assert source_hashes() == sources, "source_changed_during_verification"
        write(a.output / "portable.json", report)
        hashes = {
            f.relative_to(a.output).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in a.output.rglob("*")
            if f.is_file() and f.name != "artifact-integrity.json"
        }
        write(a.output / "artifact-integrity.json", hashes)
    assert report["status"] == "passed", "portable_acceptance_or_cleanup_failed"
    print(
        json.dumps(
            {
                "status": report["status"],
                "lane": report["lane"],
                "browser_checks": len(proof["checks"]),
                "screenshots": len(proof["screenshots"]),
                "cleanup_verified": True,
            }
        )
    )


if __name__ == "__main__":
    main()
