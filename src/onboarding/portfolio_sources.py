"""Real, company-authenticated HTTP feeds over a separate persisted synthetic source database."""

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Header, HTTPException
from .contracts import digest
from .db import connect
from .sandbox import port, child_env


def factory():
    cfg = json.loads(Path(os.environ["PORTFOLIO_SOURCE_CONFIG"]).read_text())
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health():
        with connect(cfg["dsn"]) as c:
            c.execute("SELECT 1")
        return {"synthetic": True, "ready": True}

    @app.get("/companies/{company}/{domain}")
    def feed(company: str, domain: str, x_source_token: str = Header(default="")):
        expected = cfg["tokens"].get(company)
        if not expected or not secrets.compare_digest(expected, x_source_token):
            raise HTTPException(403, "source_company_scope_denied")
        if (cfg["dedicated"] and (company != cfg["outage_company"] or domain != "operations")) or (
            not cfg["dedicated"] and company == cfg["outage_company"] and domain == "operations"
        ):
            raise HTTPException(403, "source_service_scope_denied")
        if domain not in ["crm", "operations", "finance"]:
            raise HTTPException(404, "unknown_source_domain")
        with connect(cfg["dsn"]) as c:
            rows = c.execute(
                "SELECT route,body,hash FROM source_documents WHERE company=%s AND domain=%s ORDER BY sequence",
                (company, domain),
            ).fetchall()
        return {"company": company, "domain": domain, "documents": rows, "synthetic": True}

    return app


class Sources:
    def __init__(self, stack, portfolio):
        self.stack, self.portfolio = stack, portfolio
        self.database, self.role = stack.tag + "_sources", stack.tag + "_source_read"
        self.tokens = {c[0]: secrets.token_urlsafe(32) for c in portfolio.companies}
        self.processes, self.logs = {}, []
        self.urls, self.configs = {}, {}

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def start(self):
        password = secrets.token_urlsafe(32)
        with psycopg.connect(self.stack.admin, autocommit=True) as c:
            c.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(self.role), sql.Literal(password)
                )
            )
            self.created_role = True
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database)))
            self.created_database = True
            c.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(self.database)
                )
            )
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(self.database), sql.Identifier(self.role)
                )
            )
        admin = make_conninfo(self.stack.admin, dbname=self.database)
        self.dsn = make_conninfo(admin, user=self.role, password=password)
        with connect(admin) as c:
            c.execute(
                "CREATE TABLE source_documents(company text NOT NULL,domain text NOT NULL,sequence integer NOT NULL,route text NOT NULL,body jsonb NOT NULL,hash text NOT NULL,PRIMARY KEY(company,sequence))"
            )
            c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            c.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(self.role))
            )
            c.execute(
                sql.SQL("GRANT SELECT ON source_documents TO {}").format(sql.Identifier(self.role))
            )
        self.admin = admin
        self.append(self.portfolio.financial(), "/v1/financial")
        for i in range(self.portfolio.count):
            self.append(self.portfolio.messages(i), "/v1/intake")
        for dedicated in [False, True]:
            lane = "dedicated" if dedicated else "shared"
            self.urls[lane] = f"http://127.0.0.1:{port()}"
            cfg = self.stack.path / (lane + "-source-private.json")
            cfg.write_text(
                json.dumps(
                    dict(
                        dsn=self.dsn,
                        tokens=self.tokens,
                        dedicated=dedicated,
                        outage_company=self.portfolio.companies[0][0],
                    )
                ),
                encoding="utf-8",
            )
            if os.name != "nt":
                cfg.chmod(0o600)
            self.configs[lane] = cfg
            self.launch(lane)

    def append(self, documents, route):
        with connect(self.admin) as c:
            for body in documents:
                company = body["company"]
                if route == "/v1/financial":
                    domain = body["owner"]
                else:
                    index = next(
                        i for i, x in enumerate(self.portfolio.companies) if x[0] == company
                    )
                    domain = self.portfolio.contract(index)["sources"][body["source"]]["domain"]
                sequence = c.execute(
                    "SELECT coalesce(max(sequence),0)+1 n FROM source_documents WHERE company=%s",
                    (company,),
                ).fetchone()["n"]
                c.execute(
                    "INSERT INTO source_documents VALUES(%s,%s,%s,%s,%s,%s)",
                    (company, domain, sequence, route, Jsonb(body), digest(body)),
                )

    def launch(self, lane):
        log = (self.stack.path / (lane + "-feed-private.log")).open("a")
        self.logs.append(log)
        self.processes[lane] = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "onboarding.portfolio_sources:factory",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                self.urls[lane].rsplit(":", 1)[1],
                "--no-access-log",
            ],
            env=child_env({"PORTFOLIO_SOURCE_CONFIG": str(self.configs[lane])}),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            if self.processes[lane].poll() is not None:
                raise RuntimeError("synthetic_source_process_start_failed")
            try:
                if (
                    httpx.get(self.urls[lane] + "/health", trust_env=False, timeout=1).status_code
                    == 200
                ):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise RuntimeError("synthetic_source_start_timeout")

    def stop_company(self):
        self.processes["dedicated"].terminate()
        self.processes["dedicated"].wait(timeout=10)

    def fetch(self, company, domain):
        lane = (
            "dedicated"
            if company == self.portfolio.companies[0][0] and domain == "operations"
            else "shared"
        )
        with httpx.Client(trust_env=False, timeout=2) as c:
            response = c.get(
                self.urls[lane] + f"/companies/{company}/{domain}",
                headers={"X-Source-Token": self.tokens[company]},
            )
            response.raise_for_status()
        result = response.json()["documents"]
        assert all(digest(r["body"]) == r["hash"] for r in result)
        # Customer contracts must arrive before their financial records.
        return sorted(result, key=lambda r: r["route"] != "/v1/intake")

    def financial(self):
        with connect(self.dsn) as c:
            return c.execute(
                "SELECT body,hash FROM source_documents WHERE route='/v1/financial' ORDER BY company,sequence"
            ).fetchall()

    def __exit__(self, *_):
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        for log in self.logs:
            log.close()
        with psycopg.connect(self.stack.admin, autocommit=True) as c:
            if getattr(self, "created_database", False):
                c.execute(
                    sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(self.database))
                )
            if getattr(self, "created_role", False):
                c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(self.role)))
            assert (
                c.execute(
                    "SELECT count(*) FROM pg_database WHERE datname=%s", (self.database,)
                ).fetchone()[0]
                == 0
            )
