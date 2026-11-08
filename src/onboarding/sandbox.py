"""Owned ephemeral PostgreSQL and one real API process; trusted synthetic fixture installer."""

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from importlib.resources import files
import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from .fixtures import COMPANIES, mapping, seed
from .db import connect


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def child_env(extra=None):
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "HOME",
        "APPDATA",
        "LOCALAPPDATA",
        "PYTHONPATH",
        "PYTHONUTF8",
        "VIRTUAL_ENV",
    }
    return {**{k: v for k, v in os.environ.items() if k.upper() in allowed}, **(extra or {})}


class Sandbox:
    def __init__(self, workspace, scenario=None):
        self.scenario = scenario
        self.path = Path(workspace).resolve()
        if self.path.exists():
            raise ValueError("fresh_workspace_required")
        self.path.mkdir(parents=True)
        self.own = False
        self.process = None
        self.log = None
        self.created = False

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException:
            self.stop()
            raise

    def start(self):
        self.admin = os.environ.get("ONBOARDING_TEST_ADMIN_DSN")
        self.tag = "acq_" + secrets.token_hex(6)
        if not self.admin:
            suffix = ".exe" if os.name == "nt" else ""
            pg = Path(os.environ.get("PG_BIN", ""))
            initdb = shutil.which("initdb") or str(pg / ("initdb" + suffix))
            self.pg_ctl = shutil.which("pg_ctl") or str(pg / ("pg_ctl" + suffix))
            password = secrets.token_urlsafe(32)
            pw = self.path / "install-password"
            pw.write_text(password)
            if os.name != "nt":
                pw.chmod(0o600)
            with (self.path / "initdb.log").open("w") as log:
                subprocess.run(
                    [
                        initdb,
                        "-D",
                        str(self.path / "pgdata"),
                        "-U",
                        "postgres",
                        "-A",
                        "scram-sha-256",
                        "--pwfile",
                        str(pw),
                        "--encoding=UTF8",
                        "--locale=C",
                    ],
                    check=True,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            pw.unlink()
            p = port()
            subprocess.run(
                [
                    self.pg_ctl,
                    "-D",
                    str(self.path / "pgdata"),
                    "-l",
                    str(self.path / "postgres.log"),
                    "-o",
                    f"-h 127.0.0.1 -p {p} -c max_connections=30 -c shared_buffers=32MB",
                    "-w",
                    "start",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            self.own = True
            self.admin = make_conninfo(
                host="127.0.0.1", port=p, user="postgres", password=password, dbname="postgres"
            )
        self.role = self.tag + "_app"
        password = secrets.token_urlsafe(32)
        with psycopg.connect(self.admin, autocommit=True) as c:
            c.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(self.role), sql.Literal(password)
                )
            )
            self.created = True
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.tag)))
            c.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(self.tag)
                )
            )
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(self.tag), sql.Identifier(self.role)
                )
            )
        self.admin_dsn = make_conninfo(self.admin, dbname=self.tag)
        self.dsn = make_conninfo(self.admin_dsn, user=self.role, password=password)
        with connect(self.admin_dsn) as c:
            c.execute(files("onboarding").joinpath("schema.sql").read_text(encoding="utf-8"))
            c.execute(files("onboarding").joinpath("pass2.sql").read_text(encoding="utf-8"))
            c.execute(files("onboarding").joinpath("financial.sql").read_text(encoding="utf-8"))
            c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            role = sql.Identifier(self.role)
            c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            c.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role))
            c.execute(
                sql.SQL(
                    "GRANT INSERT ON messages,deliveries,quarantine,source_records,customer_fields,gate_runs,audit,business_events,business_heads,outbound,outbound_attempts,financial_events TO {}"
                ).format(role)
            )
            c.execute(sql.SQL("GRANT UPDATE(status,reason) ON messages TO {}").format(role))
            c.execute(sql.SQL("GRANT UPDATE(status,gate_hash) ON companies TO {}").format(role))
            c.execute(sql.SQL("GRANT UPDATE ON source_records,customer_fields TO {}").format(role))
            c.execute(sql.SQL("GRANT UPDATE ON business_heads TO {}").format(role))
            c.execute(
                sql.SQL(
                    "GRANT UPDATE(state,attempts,proof,detail,next_at) ON outbound TO {}"
                ).format(role)
            )
            c.execute(
                sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
            )
        self._receiver_and_reviewer()
        from .console_setup import setup as console_setup

        companies = self.scenario.companies if self.scenario else COMPANIES
        self.console = console_setup(self, companies)
        self.messages = (
            self.scenario.seed(self.admin_dsn) if self.scenario else seed(self.admin_dsn)
        )
        self.identities = [
            {
                "role": "source",
                "company": company,
                "source": source,
                "token": secrets.token_urlsafe(32),
            }
            for company, _, _, _, style in companies
            for source in mapping(style)["sources"]
        ]
        self.identities += [
            {"role": role, "token": secrets.token_urlsafe(32)} for role in ["viewer", "controller"]
        ]
        self.identities.append(
            {
                "role": "reviewer",
                "actor": "synthetic-reviewer",
                "companies": [x[0] for x in companies],
                "token": secrets.token_urlsafe(32),
            }
        )
        config = {
            "dsn": self.dsn,
            "identities": self.identities,
            "reviewer_dsn": self.reviewer_dsn,
            "receiver": self.receiver,
            "console": self.console,
        }
        self.config = config
        self.sender_config = {"dsn": self.dsn, "receiver": self.receiver}
        self.sender_path = self.path / "sender-private.json"
        self.sender_path.write_text(json.dumps(self.sender_config), encoding="utf-8")
        if os.name != "nt":
            self.sender_path.chmod(0o600)
        self.config_path = self.path / "runtime-private.json"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        if os.name != "nt":
            self.config_path.chmod(0o600)
        p = port()
        self.url = f"http://127.0.0.1:{p}"
        self.log = (self.path / "api.log").open("w")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "onboarding.api:factory",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(p),
                "--no-access-log",
            ],
            env=child_env({"ONBOARDING_RUNTIME": str(self.config_path)}),
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            if self.process.poll() is not None:
                raise RuntimeError("local_api_start_failed_see_private_log")
            try:
                if httpx.get(self.url + "/health", trust_env=False, timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("local_api_start_timeout")

    def client(self, role="source", company=None, source=None):
        identity = next(
            x
            for x in self.identities
            if x["role"] == role
            and (role != "source" or (x["company"], x["source"]) == (company, source))
        )
        return httpx.Client(
            base_url=self.url,
            headers={"X-Admission-Token": identity["token"]},
            trust_env=False,
            timeout=10,
        )

    def reset(self):
        with connect(self.admin_dsn) as c:
            c.execute("TRUNCATE console_sessions,console_login_attempts")
            c.execute(
                "TRUNCATE financial_publications,financial_inputs,financial_snapshots,financial_policies"
            )
        self.messages = (
            self.scenario.seed(self.admin_dsn) if self.scenario else seed(self.admin_dsn)
        )
        with connect(self.receiver_admin) as c:
            c.execute("TRUNCATE effects,records,requests,faults RESTART IDENTITY")

    def _receiver_and_reviewer(self):
        from .receiver import SCHEMA

        self.reviewer_role = self.tag + "_review"
        self.receiver_role = self.tag + "_receiver"
        self.receiver_database = self.tag + "_remote"
        review_password = secrets.token_urlsafe(32)
        remote_password = secrets.token_urlsafe(32)
        with psycopg.connect(self.admin, autocommit=True) as c:
            for role, password in [
                (self.reviewer_role, review_password),
                (self.receiver_role, remote_password),
            ]:
                c.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
            self.extra_roles_created = True
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.receiver_database)))
            c.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(self.receiver_database)
                )
            )
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(self.receiver_database), sql.Identifier(self.receiver_role)
                )
            )
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(self.tag), sql.Identifier(self.reviewer_role)
                )
            )
        self.reviewer_dsn = make_conninfo(
            self.admin_dsn, user=self.reviewer_role, password=review_password
        )
        with connect(self.admin_dsn) as c:
            role = sql.Identifier(self.reviewer_role)
            c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            c.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role))
            c.execute(
                sql.SQL(
                    "GRANT INSERT ON reviews,review_decisions,quarantine_resolutions,crosswalks,mapping_versions,baselines,source_records,customer_fields,gate_runs,audit,financial_policies,financial_snapshots,financial_inputs,financial_publications TO {}"
                ).format(role)
            )
            c.execute(
                sql.SQL("GRANT UPDATE(active_mapping,status,gate_hash) ON companies TO {}").format(
                    role
                )
            )
            c.execute(sql.SQL("GRANT UPDATE ON source_records,customer_fields TO {}").format(role))
            c.execute(
                sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
            )
        self.receiver_admin = make_conninfo(self.admin, dbname=self.receiver_database)
        self.receiver_dsn = make_conninfo(
            self.receiver_admin, user=self.receiver_role, password=remote_password
        )
        with connect(self.receiver_admin) as c:
            c.execute(SCHEMA)
            c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            role = sql.Identifier(self.receiver_role)
            c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            c.execute(
                sql.SQL("GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA public TO {}").format(role)
            )
            c.execute(sql.SQL("GRANT UPDATE(modes) ON faults TO {}").format(role))
            c.execute(
                sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
            )
        p = port()
        self.receiver_injector = secrets.token_urlsafe(32)
        token = secrets.token_urlsafe(32)
        self.receiver = {"url": f"http://127.0.0.1:{p}", "token": token}
        config = self.path / "receiver-private.json"
        config.write_text(
            json.dumps(
                {"dsn": self.receiver_dsn, "token": token, "injector": self.receiver_injector}
            ),
            encoding="utf-8",
        )
        if os.name != "nt":
            config.chmod(0o600)
        self.receiver_log = (self.path / "receiver.log").open("w")
        self.receiver_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "onboarding.receiver:factory",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(p),
                "--no-access-log",
            ],
            env=child_env({"ONBOARDING_RECEIVER_RUNTIME": str(config)}),
            stdout=self.receiver_log,
            stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            if self.receiver_process.poll() is not None:
                raise RuntimeError("receiver_start_failed_see_private_log")
            try:
                if (
                    httpx.get(
                        self.receiver["url"] + "/health", trust_env=False, timeout=1
                    ).status_code
                    == 200
                ):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("receiver_start_timeout")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
        receiver = getattr(self, "receiver_process", None)
        if receiver and receiver.poll() is None:
            receiver.terminate()
            receiver.wait(timeout=10)
        if getattr(self, "receiver_log", None):
            self.receiver_log.close()
        if getattr(self, "created", False):
            with psycopg.connect(self.admin, autocommit=True) as c:
                if getattr(self, "extra_roles_created", False):
                    c.execute(
                        sql.SQL("DROP DATABASE IF EXISTS {} WITH(FORCE)").format(
                            sql.Identifier(self.receiver_database)
                        )
                    )
                    for role in [self.receiver_role, self.reviewer_role]:
                        # Main database must be dropped before its reviewer grants disappear.
                        if role == self.receiver_role:
                            c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
                c.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH(FORCE)").format(
                        sql.Identifier(self.tag)
                    )
                )
                c.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(self.role)))
                if getattr(self, "extra_roles_created", False):
                    c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(self.reviewer_role)))
                if getattr(self, "warehouse_role", None):
                    c.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(self.warehouse_role)
                        )
                    )
                for role in getattr(self, "console_roles", []):
                    c.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        if self.own:
            subprocess.run(
                [self.pg_ctl, "-D", str(self.path / "pgdata"), "-m", "fast", "-w", "stop"],
                check=True,
                stdout=subprocess.DEVNULL,
            )

    def __exit__(self, *args):
        self.stop()
