"""Session-authenticated, scope-checked views over control state and validated publications."""

import hashlib
import secrets
from importlib.resources import files
from uuid import UUID
from fastapi import Request, HTTPException, Depends
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from psycopg.types.json import Jsonb
from .contracts import Closed
from .console_setup import password_hash
from .db import connect
from .engine import inspect_gate, admit, audit
from . import governance
from .reporting import plain

COOKIE = "acquisition_session"


class Login(Closed):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-z-]+$")
    password: str = Field(min_length=1, max_length=200)


class Reason(Closed):
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class Preview(Closed):
    contract: dict


def register(app, config):
    from .api import IdentityReview, MappingReview, Decision, Correction

    cfg = config["console"]
    assets = files("onboarding").joinpath("web")
    app.mount("/console/assets", StaticFiles(directory=str(assets)), name="console_assets")

    def origin(request):
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if request.headers.get("origin") != expected:
            raise HTTPException(403, "same_origin_required")

    def session(request: Request):
        token = request.cookies.get(COOKIE, "")
        if len(token) > 200:
            raise HTTPException(401, "session_required")
        h = hashlib.sha256(token.encode()).hexdigest()
        with connect(cfg["auth_dsn"]) as c:
            u = c.execute(
                "SELECT * FROM console_sessions WHERE session_hash=%s AND expires_at>clock_timestamp()",
                (h,),
            ).fetchone()
        if not u:
            raise HTTPException(401, "session_required")
        return u

    def scope(u, company):
        if company not in u["companies"]:
            raise HTTPException(403, "company_scope_denied")
        return company

    def writer(request, u, company):
        origin(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), u["csrf"]):
            raise HTTPException(403, "csrf_required")
        if u["role"] != "reviewer":
            raise HTTPException(403, "reviewer_required")
        scope(u, company)
        return u["actor"]

    def public(u):
        return plain(
            {k: u[k] for k in ["actor", "role", "companies", "expires_at"]} | {"csrf": u["csrf"]}
        )

    def companies(c, u):
        rows = c.execute(
            "SELECT id,name,legal_entity,acquired_on,status,active_mapping,gate_hash FROM companies WHERE id=ANY(%s) ORDER BY id",
            (u["companies"],),
        ).fetchall()
        for r in rows:
            gate = inspect_gate(c, r["id"])
            r["gate"] = gate
            r["admitted"] = (
                r["status"] == "portfolio_ready"
                and gate["passed"]
                and r["gate_hash"] == gate["input_hash"]
            )
        return rows

    @app.middleware("http")
    async def console_headers(request, call_next):
        if request.url.path.startswith("/console") and request.url.hostname not in [
            "127.0.0.1",
            "localhost",
        ]:
            return JSONResponse(status_code=400, content={"detail": "loopback_host_required"})
        response = await call_next(request)
        if request.url.path.startswith("/console"):
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                }
            )
        return response

    @app.get("/console/login")
    def login_page():
        return FileResponse(str(assets.joinpath("login.html")))

    @app.get("/console")
    @app.get("/console/")
    def shell(request: Request):
        try:
            session(request)
        except HTTPException:
            return RedirectResponse("/console/login", status_code=303)
        return FileResponse(str(assets.joinpath("index.html")))

    @app.post("/console/api/login")
    def login(body: Login, request: Request):
        origin(request)
        key = hashlib.sha256(body.username.encode()).hexdigest()
        with connect(cfg["auth_dsn"]) as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,9))", (key,))
            c.execute(
                "DELETE FROM console_login_attempts WHERE started_at<clock_timestamp()-interval '10 minutes'"
            )
            n = c.execute(
                "SELECT attempts FROM console_login_attempts WHERE key=%s", (key,)
            ).fetchone()
            if n and n["attempts"] >= 5:
                return JSONResponse(
                    status_code=429, content={"detail": "login_temporarily_limited"}
                )
            user = next((u for u in cfg["users"] if u["username"] == body.username), None)
            reference = user["password_hash"] if user else cfg["dummy_hash"]
            matched = secrets.compare_digest(
                password_hash(body.password, reference.split(":")[0]), reference
            )
            if not user or not matched:
                c.execute(
                    "INSERT INTO console_login_attempts(key,attempts) VALUES(%s,1) ON CONFLICT(key) DO UPDATE SET attempts=console_login_attempts.attempts+1",
                    (key,),
                )
                return JSONResponse(
                    status_code=401, content={"detail": "invalid_local_credentials"}
                )
            c.execute("DELETE FROM console_login_attempts WHERE key=%s", (key,))
            c.execute("DELETE FROM console_sessions WHERE expires_at<=clock_timestamp()")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            row = c.execute(
                "INSERT INTO console_sessions(session_hash,actor,role,companies,csrf,expires_at) VALUES(%s,%s,%s,%s,%s,clock_timestamp()+interval '30 minutes') RETURNING *",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    user["actor"],
                    user["role"],
                    Jsonb(user["companies"]),
                    csrf,
                ),
            ).fetchone()
        response = JSONResponse(public(row))
        response.set_cookie(
            COOKIE,
            token,
            max_age=1800,
            path="/console",
            httponly=True,
            samesite="strict",
            secure=False,
        )
        return response

    @app.get("/console/api/session")
    def who(u=Depends(session)):
        return public(u)

    @app.post("/console/api/logout")
    def logout(request: Request, u=Depends(session)):
        origin(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), u["csrf"]):
            raise HTTPException(403, "csrf_required")
        with connect(cfg["auth_dsn"]) as c:
            c.execute("DELETE FROM console_sessions WHERE session_hash=%s", (u["session_hash"],))
        response = JSONResponse({"logged_out": True})
        response.delete_cookie(COOKIE, path="/console")
        return response

    @app.get("/console/api/overview")
    def overview(u=Depends(session)):
        with connect(cfg["read_dsn"]) as c:
            opcos = companies(c, u)
            reports = c.execute(
                "SELECT p.report_id,p.published_at,s.cutoff,s.previous_id FROM financial_publications p JOIN financial_snapshots s ON s.id=p.report_id WHERE s.control ?| %s::text[] ORDER BY s.cutoff",
                (u["companies"],),
            ).fetchall()
        return plain({"companies": opcos, "reports": reports})

    @app.get("/console/api/companies/{company}")
    def company_view(company: str, u=Depends(session)):
        scope(u, company)
        with connect(cfg["read_dsn"]) as c:
            narrowed = {**u, "companies": [company]}
            opco = companies(c, narrowed)
            if not opco:
                raise HTTPException(404, "company_not_found")
            systems = c.execute(
                "SELECT * FROM systems WHERE company=%s ORDER BY source", (company,)
            ).fetchall()
            versions = c.execute(
                "SELECT * FROM mapping_versions WHERE company=%s ORDER BY version", (company,)
            ).fetchall()
            sources = c.execute(
                "SELECT * FROM source_records WHERE company=%s ORDER BY source", (company,)
            ).fetchall()
            outbox = c.execute(
                "SELECT * FROM outbound WHERE company=%s ORDER BY created_at", (company,)
            ).fetchall()
            history = c.execute(
                "SELECT * FROM source_record_history WHERE company=%s ORDER BY id", (company,)
            ).fetchall()
            logs = c.execute(
                "SELECT * FROM audit WHERE company=%s AND action NOT LIKE 'financial_%%' ORDER BY id DESC LIMIT 40",
                (company,),
            ).fetchall()
            decisions = c.execute(
                "SELECT * FROM review_decisions WHERE company=%s ORDER BY decided_at", (company,)
            ).fetchall()
        view = governance.inspect(cfg["read_dsn"], company)
        try:
            with connect(cfg["read_dsn"]) as c:
                _, _, coverage = governance.inventory(c, company, view["contract"])
        except ValueError:
            coverage = None
        return plain(
            {
                "company": opco[0],
                "systems": systems,
                "mapping_versions": versions,
                "source_records": sources,
                "source_history": history,
                "outbound": outbox,
                "audit": logs,
                "decisions": decisions,
                "governance": view,
                "coverage": coverage,
            }
        )

    def publication(c, identifier):
        row = c.execute(
            "SELECT p.*,s.cutoff,s.previous_id,s.control,s.input_hash,f.body AS policy FROM financial_publications p JOIN financial_snapshots s ON s.id=p.report_id JOIN financial_policies f ON f.version=s.policy_version WHERE p.report_id=%s",
            (identifier,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "validated_publication_not_found")
        return row

    @app.get("/console/api/reports/{identifier}")
    def report(identifier: str, company: str | None = None, u=Depends(session)):
        if company and company != "all":
            allowed = [scope(u, company)]
        elif u["role"] == "sponsor":
            allowed = u["companies"]
        elif company == "all":
            raise HTTPException(403, "company_scope_denied")
        else:
            allowed = u["companies"]
        with connect(cfg["read_dsn"]) as c:
            row = publication(c, identifier)
            allowed = [key for key in allowed if key in row["control"]]
            if not allowed:
                raise HTTPException(404, "validated_publication_not_found_in_scope")
            source = c.execute(
                "SELECT event_id,body,hash FROM financial_inputs WHERE report_id=%s AND body->>'company'=ANY(%s) ORDER BY event_id",
                (identifier, allowed),
            ).fetchall()
            previous = publication(c, row["previous_id"]) if row["previous_id"] else None
        results = row["results"]
        datasets = {
            key: [r.copy() for r in results[key] if r["company"] in allowed]
            for key in [
                "fct_invoices",
                "fct_allocations",
                "intercompany_eliminations",
                "reconciliation_variances",
                "legal_entity_totals",
            ]
        }
        owned = {r["event_id"] for r in source}
        for key in ["fct_invoices", "fct_allocations", "intercompany_eliminations"]:
            for r in datasets[key]:
                for field in ["source_event_ids", "charge_event_ids", "acceptance_event_ids"]:
                    if field in r:
                        r[field] = [i for i in (r[field] or []) if i in owned]
        measures = [key for key in results["portfolio_totals"][0] if key.endswith("_minor")]

        def rollup(rows):
            return [
                {
                    "period": period,
                    "currency": row["policy"]["currency"],
                    **{
                        m: sum(
                            r[m] for r in rows if r["period"] == period and r["company"] in allowed
                        )
                        for m in measures
                    },
                }
                for period in row["policy"]["periods"]
            ]

        totals = rollup(results["legal_entity_totals"])
        bridge = []
        if previous:
            old = {r["period"]: r for r in rollup(previous["results"]["legal_entity_totals"])}
            bridge = [
                {
                    "period": r["period"],
                    "metric": m,
                    "before_minor": old[r["period"]][m],
                    "after_minor": r[m],
                    "delta_minor": r[m] - old[r["period"]][m],
                }
                for r in totals
                for m in measures
            ]
        exclusions = []
        for entry in source:
            b = entry["body"]
            state = row["control"][b["company"]]
            if b["kind"] == "invoice" and (
                not state["admitted"] or b["transaction_date"] < state["acquired_on"]
            ):
                exclusions.append(
                    {
                        "company": b["company"],
                        "legal_entity": b["legal_entity"],
                        "source_id": b["source_id"],
                        "amount_minor": b["amount_minor"],
                        "reason": "admission_held" if not state["admitted"] else "pre_acquisition",
                        "event_id": entry["event_id"],
                    }
                )
        return plain(
            {
                "id": identifier,
                "cutoff": row["cutoff"],
                "published_at": row["published_at"],
                "previous_id": row["previous_id"],
                "currency": row["policy"]["currency"],
                "periods": row["policy"]["periods"],
                "scenario": {
                    "id": row["policy"]
                    .get("scenario", {})
                    .get("id", "selected-period-correctness"),
                    "profiles": {
                        key: amount
                        for key, amount in row["policy"]
                        .get("scenario", {})
                        .get("profiles", {})
                        .items()
                        if key in allowed
                    },
                },
                "scope": allowed,
                "control": {k: v for k, v in row["control"].items() if k in allowed},
                "input_hash": row["input_hash"] if u["role"] == "sponsor" else None,
                "status": "reconciled_with_open_variances"
                if datasets["reconciliation_variances"]
                else "scope_excluded"
                if not any(row["control"][key]["admitted"] for key in allowed)
                else "reconciled",
                "totals": totals,
                "datasets": datasets,
                "bridge": bridge,
                "exclusions": exclusions,
                "sources": [
                    {
                        "event_id": r["event_id"],
                        "company": r["body"]["company"],
                        "kind": r["body"]["kind"],
                        "source_id": r["body"]["source_id"],
                        "hash": r["hash"],
                    }
                    for r in source
                ],
            }
        )

    @app.get("/console/api/reports/{identifier}/sources/{event_id}")
    def source_record(identifier: str, event_id: int, u=Depends(session)):
        with connect(cfg["read_dsn"]) as c:
            publication(c, identifier)
            row = c.execute(
                "SELECT event_id,body,hash FROM financial_inputs WHERE report_id=%s AND event_id=%s AND body->>'company'=ANY(%s)",
                (identifier, event_id, u["companies"]),
            ).fetchone()
        if not row:
            raise HTTPException(404, "source_not_found_in_scope")
        return row

    @app.post("/console/api/companies/{company}/identity")
    def propose(company: str, body: IdentityReview, request: Request, u=Depends(session)):
        actor = writer(request, u, company)
        return {
            "review_id": governance.propose_identity(
                config["reviewer_dsn"],
                company,
                body.quarantine_id,
                body.candidate,
                actor,
                body.reason,
            )
        }

    @app.post("/console/api/companies/{company}/mapping-preview")
    def preview(company: str, body: Preview, request: Request, u=Depends(session)):
        writer(request, u, company)
        from .contracts import validate_contract
        from .engine import Refused

        try:
            validate_contract(body.contract)
        except ValueError as exc:
            raise Refused("invalid_mapping_contract") from exc
        with connect(cfg["read_dsn"]) as c:
            _, _, coverage = governance.inventory(c, company, body.contract)
        return {"coverage": coverage}

    @app.post("/console/api/companies/{company}/mapping")
    def mapping(company: str, body: MappingReview, request: Request, u=Depends(session)):
        actor = writer(request, u, company)
        return {
            "review_id": governance.propose_mapping(
                config["reviewer_dsn"], company, body.contract, body.coverage, actor, body.reason
            )
        }

    @app.post("/console/api/companies/{company}/reviews/{identifier}/decision")
    def decision(
        company: str, identifier: UUID, body: Decision, request: Request, u=Depends(session)
    ):
        actor = writer(request, u, company)
        return governance.decide(
            config["reviewer_dsn"], company, str(identifier), body.result, actor, body.reason
        )

    @app.post("/console/api/companies/{company}/correction")
    def correction(company: str, body: Correction, request: Request, u=Depends(session)):
        actor = writer(request, u, company)
        return governance.resolve_corrected(
            config["reviewer_dsn"], company, body.quarantine_id, body.message_id, actor, body.reason
        )

    @app.post("/console/api/companies/{company}/admission")
    def recompute(company: str, body: Reason, request: Request, u=Depends(session)):
        actor = writer(request, u, company)
        gate = admit(config["dsn"], company)
        with connect(config["reviewer_dsn"]) as c:
            audit(
                c,
                company,
                "console_admission_requested",
                gate["input_hash"],
                {"actor": actor, "reason": body.reason, "passed": gate["passed"]},
            )
        return gate
