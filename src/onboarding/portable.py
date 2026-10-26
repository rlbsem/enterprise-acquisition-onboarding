"""Disposable local demo using the original installer, financial engine and console."""

import argparse
import hashlib
import json
import os
import secrets
import signal
import threading
import traceback
import platform
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .db import connect
from .financial_demo import execute
from .portable_gateway import Gateway
from .sandbox import Sandbox


def private_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        json.dump(value, f, indent=2, default=str)
        f.write("\n")
    temporary.replace(path)


@contextmanager
def state_lock(state):
    state.mkdir(parents=True, exist_ok=True)
    if state.is_symlink():
        raise ValueError("owned_state_directory_required")
    if os.name != "nt":
        state.chmod(0o700)
    with (state / "owner.lock").open("a+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("demo_state_already_in_use") from error
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def current(state):
    record = json.loads((state / "ready-private.json").read_text(encoding="utf-8"))
    run = (state / record["run"]).resolve()
    if not run.is_relative_to(state.resolve()) or not run.is_dir():
        raise ValueError("invalid_owned_run")
    return record, run


def inspect(state):
    record, run = current(state)
    config = json.loads((run / "runtime-private.json").read_text())
    remote = json.loads((run / "receiver-private.json").read_text())
    with connect(config["console"]["read_dsn"]) as c:
        c.execute("SET TRANSACTION READ ONLY")
        companies = c.execute(
            "SELECT id,status,active_mapping FROM companies ORDER BY id"
        ).fetchall()
        reports = c.execute(
            "SELECT report_id FROM financial_publications ORDER BY report_id"
        ).fetchall()
        decisions = c.execute("SELECT count(*) n FROM review_decisions").fetchone()["n"]
        version = c.execute("SHOW server_version").fetchone()["server_version"]
        flags = c.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
    with connect(remote["dsn"]) as c:
        c.execute("SET TRANSACTION READ ONLY")
        effects = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
        posts = c.execute(
            "SELECT count(*) n FROM requests WHERE operation IN('apply','duplicate')"
        ).fetchone()["n"]
    root = Path(__file__).resolve().parents[2]
    sources = {}
    for folder in [root / "src", root / "warehouse"]:
        for p in sorted(folder.rglob("*")):
            if (
                p.is_file()
                and p.suffix in {".py", ".sql", ".html", ".js", ".css", ".yml"}
                and not any(x in p.parts for x in ["target", "logs"])
            ):
                sources[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {
        "run_id": record["run"],
        "companies": companies,
        "publications": reports,
        "review_decisions": decisions,
        "receiver_effects": effects,
        "receiver_posts": posts,
        "console_read_role_restricted": not any(flags.values()),
        "postgres": version,
        "python": platform.python_version(),
        "source_sha256": sources,
        "financial": json.loads((run / "financial-summary.json").read_text()),
        "private_modes": {
            p.name: oct(p.stat().st_mode & 0o777)
            for p in [run / "runtime-private.json", run / "console-credentials-private.json"]
        },
    }


def acceptance_config(stack):
    """Test-only expiry capability; no persisted PostgreSQL administrator password."""
    role = stack.tag + "_expiry"
    password = secrets.token_urlsafe(32)
    with psycopg.connect(stack.admin, autocommit=True) as c:
        c.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        c.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(stack.tag), sql.Identifier(role)
            )
        )
    stack.console_roles.append(role)
    with connect(stack.admin_dsn) as c:
        c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        c.execute(
            sql.SQL("GRANT SELECT(actor),UPDATE(expires_at) ON console_sessions TO {}").format(
                sql.Identifier(role)
            )
        )
    return {
        "dsn": stack.dsn,
        "receiver_admin": stack.receiver_dsn,
        "admin_dsn": make_conninfo(stack.admin_dsn, user=role, password=password),
        "console": stack.console,
        "console_credentials": stack.console_credentials,
    }


def serve(state, port, container=False, acceptance=False):
    if any(
        os.environ.get(k)
        for k in ["ONBOARDING_TEST_ADMIN_DSN", "ONBOARDING_RUNTIME", "ONBOARDING_RECEIVER_RUNTIME"]
    ):
        raise ValueError("portable_demo_refuses_external_runtime")
    if container and not Path("/.dockerenv").exists():
        raise ValueError("container_binding_requires_docker")
    stop, ready = threading.Event(), threading.Event()
    old_handlers = {}
    for name in [signal.SIGINT, signal.SIGTERM]:
        old_handlers[name] = signal.signal(name, lambda *_: stop.set())
    gateway = thread = None
    pointer = state / "ready-private.json"

    def close_gateway():
        ready.clear()
        pointer.unlink(missing_ok=True)
        if gateway:
            if thread and thread.is_alive():
                gateway.shutdown()
            gateway.server_close()
        if thread:
            thread.join(timeout=5)

    try:
        with state_lock(state):
            pointer.unlink(missing_ok=True)
            run_id = "run-" + secrets.token_hex(8)
            with ExitStack() as scope:
                stack = scope.enter_context(Sandbox(state / run_id))
                scope.callback(close_gateway)
                financial = execute(stack, stack.path / "financial")
                if stop.is_set():
                    return
                upstream = urlsplit(stack.url)
                gateway = Gateway(
                    ("0.0.0.0" if container else "127.0.0.1", port),
                    ("127.0.0.1", upstream.port),
                    ready,
                )
                stack.gateway_url = f"http://127.0.0.1:{gateway.server_port}"
                if acceptance:
                    private_json(stack.path / "acceptance-private.json", acceptance_config(stack))
                private_json(
                    stack.path / "financial-summary.json",
                    {
                        "original": financial["totals_before"],
                        "restated": financial["totals_after"],
                        "original_report_unchanged": financial["original_report_unchanged"],
                        "blocked_candidate_published": financial["blocked_candidate"]["published"],
                    },
                )
                ready.set()
                private_json(
                    pointer, {"run": run_id, "url": stack.gateway_url, "acceptance": acceptance}
                )
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                print(
                    json.dumps(
                        {
                            "event": "ready",
                            "url": stack.gateway_url + "/console",
                            "credentials": "Use the private credentials command; never paste credentials into issues.",
                        }
                    ),
                    flush=True,
                )
                while not stop.wait(2):
                    request = state / "stop-private.json"
                    if request.exists():
                        try:
                            if json.loads(request.read_text())["run"] == run_id:
                                request.unlink()
                                break
                        except (ValueError, KeyError):
                            pass
                    if (
                        stack.process.poll() is not None
                        or stack.receiver_process.poll() is not None
                    ):
                        raise RuntimeError("owned_http_service_exited")
                    for dsn in [stack.dsn, stack.receiver_dsn]:
                        with connect(dsn) as c:
                            c.execute("SELECT 1")
            private_json(
                state / "shutdown.json",
                {
                    "stopped_at": datetime.now(UTC).isoformat(),
                    "owned_database_and_http_processes_stopped": True,
                },
            )
    finally:
        for name, handler in old_handlers.items():
            signal.signal(name, handler)
    print(json.dumps({"event": "stopped"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("serve")
    start.add_argument("--state", type=Path, default=Path("/state"))
    start.add_argument("--port", type=int, default=8592)
    start.add_argument("--container", action="store_true")
    start.add_argument("--acceptance", action="store_true")
    credentials = sub.add_parser("credentials")
    credentials.add_argument("--state", type=Path, default=Path("/state"))
    credentials.add_argument(
        "--user",
        choices=["sponsor", "cedar-leader", "meridian-leader", "summit-leader", "reviewer"],
        default="sponsor",
    )
    shutdown = sub.add_parser("stop")
    shutdown.add_argument("--state", type=Path, required=True)
    snapshot = sub.add_parser("inspect")
    snapshot.add_argument("--state", type=Path, default=Path("/state"))
    health = sub.add_parser("health")
    health.add_argument("--port", type=int, default=8080)
    a = parser.parse_args()
    if a.command == "health":
        try:
            r = httpx.get(f"http://127.0.0.1:{a.port}/health", timeout=3, trust_env=False)
            raise SystemExit(0 if r.status_code == 200 else 1)
        except httpx.HTTPError:
            raise SystemExit(1) from None
    if a.command == "credentials":
        _, run = current(a.state.resolve())
        users = json.loads((run / "console-credentials-private.json").read_text())
        print(json.dumps(users[a.user]))
        return
    if a.command == "stop":
        record, _ = current(a.state.resolve())
        private_json(a.state / "stop-private.json", {"run": record["run"]})
        return
    if a.command == "inspect":
        print(json.dumps(inspect(a.state.resolve()), default=str))
        return
    state = a.state.absolute()
    try:
        serve(state, a.port, a.container, a.acceptance)
    except Exception:
        # Only explicitly private state receives the traceback; compose logs stay sanitized.
        if state.is_dir():
            path = state / "failure-private.txt"
            path.write_text(traceback.format_exc(), encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o600)
        print(
            json.dumps(
                {
                    "event": "failed",
                    "detail": "Inspect private state; no external configuration is accepted.",
                }
            ),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
