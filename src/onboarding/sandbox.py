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


class Sandbox:
    def __init__(self, workspace):
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
            c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            role = sql.Identifier(self.role)
            c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            c.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role))
            c.execute(
                sql.SQL(
                    "GRANT INSERT ON messages,deliveries,quarantine,source_records,customer_fields,gate_runs,audit TO {}"
                ).format(role)
            )
            c.execute(sql.SQL("GRANT UPDATE(status,reason) ON messages TO {}").format(role))
            c.execute(sql.SQL("GRANT UPDATE(status,gate_hash) ON companies TO {}").format(role))
            c.execute(sql.SQL("GRANT UPDATE ON source_records,customer_fields TO {}").format(role))
            c.execute(
                sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
            )
        self.messages = seed(self.admin_dsn)
        self.identities = [
            {
                "role": "source",
                "company": company,
                "source": source,
                "token": secrets.token_urlsafe(32),
            }
            for company, _, _, _, style in COMPANIES
            for source in mapping(style)["sources"]
        ]
        self.identities += [
            {"role": role, "token": secrets.token_urlsafe(32)} for role in ["viewer", "controller"]
        ]
        config = {"dsn": self.dsn, "identities": self.identities}
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
            env={**os.environ, "ONBOARDING_RUNTIME": str(self.config_path)},
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
        self.messages = seed(self.admin_dsn)

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
        if getattr(self, "created", False):
            with psycopg.connect(self.admin, autocommit=True) as c:
                c.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH(FORCE)").format(
                        sql.Identifier(self.tag)
                    )
                )
                c.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(self.role)))
        if self.own:
            subprocess.run(
                [self.pg_ctl, "-D", str(self.path / "pgdata"), "-m", "fast", "-w", "stop"],
                check=True,
                stdout=subprocess.DEVNULL,
            )

    def __exit__(self, *args):
        self.stop()
