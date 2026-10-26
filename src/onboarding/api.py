"""Loopback intake boundary. Source tokens cannot approve mappings or admit companies."""

import json
import os
import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .contracts import Message
from .engine import intake, admit, portfolio, Refused
from .db import connect
from .contracts import Closed
from pydantic import Field
from typing import Literal
from uuid import UUID
from . import governance, business, execution
from . import finance


class IdentityReview(Closed):
    quarantine_id: int = Field(ge=1)
    candidate: str = Field(pattern=r"^[0-9a-f-]{36}$")
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class MappingReview(Closed):
    contract: dict
    coverage: dict
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class Decision(Closed):
    result: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class Correction(Closed):
    quarantine_id: int = Field(ge=1)
    message_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class Handoff(Closed):
    canonical: str = Field(pattern=r"^[0-9a-f-]{36}$")
    references: dict


def create_app(config):
    app = FastAPI(
        title="Acquisition Admission - Local Synthetic Contracts",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def principal(token):
        for identity in config["identities"]:
            if secrets.compare_digest(token, identity["token"]):
                return identity
        raise HTTPException(401, "authorized_local_identity_required")

    def reviewer(token, company):
        identity = principal(token)
        if identity["role"] != "reviewer" or company not in identity["companies"]:
            raise HTTPException(403, "review_scope_denied")
        return identity["actor"]

    @app.middleware("http")
    async def bounded(request: Request, call_next):
        if request.method == "POST" and len(await request.body()) > 65536:
            return JSONResponse(status_code=413, content={"detail": "bounded_payload_required"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Refused)
    async def refused(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={"detail": "invalid_message_envelope"})

    @app.get("/health")
    def health():
        with connect(config["dsn"]) as c:
            c.execute("SELECT 1")
        return {"ready": True, "native_vendor_execution": False}

    @app.post("/v1/intake")
    def receive(body: Message, x_admission_token: str = Header(default="")):
        identity = principal(x_admission_token)
        if identity["role"] != "source" or (identity["company"], identity["source"]) != (
            body.company,
            body.source,
        ):
            raise HTTPException(403, "source_scope_denied")
        return intake(config["dsn"], body.model_dump())

    @app.post("/v1/admission/{company}")
    def accept(company: str, x_admission_token: str = Header(default="")):
        if principal(x_admission_token)["role"] != "controller":
            raise HTTPException(403, "admission_controller_required")
        return admit(config["dsn"], company)

    @app.get("/v1/portfolio")
    def read(x_admission_token: str = Header(default="")):
        if principal(x_admission_token)["role"] != "viewer":
            raise HTTPException(403, "sponsor_read_identity_required")
        return portfolio(config["dsn"])

    @app.get("/v1/reviews/{company}")
    def review_sources(company: str, x_admission_token: str = Header(default="")):
        reviewer(x_admission_token, company)
        return governance.inspect(config["reviewer_dsn"], company)

    @app.post("/v1/reviews/{company}/identity")
    def identity_review(
        company: str, body: IdentityReview, x_admission_token: str = Header(default="")
    ):
        actor = reviewer(x_admission_token, company)
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

    @app.post("/v1/reviews/{company}/mapping")
    def mapping_review(
        company: str, body: MappingReview, x_admission_token: str = Header(default="")
    ):
        actor = reviewer(x_admission_token, company)
        return {
            "review_id": governance.propose_mapping(
                config["reviewer_dsn"], company, body.contract, body.coverage, actor, body.reason
            )
        }

    @app.post("/v1/reviews/{company}/{identifier}/decision")
    def decide_review(
        company: str, identifier: UUID, body: Decision, x_admission_token: str = Header(default="")
    ):
        actor = reviewer(x_admission_token, company)
        return governance.decide(
            config["reviewer_dsn"], company, str(identifier), body.result, actor, body.reason
        )

    @app.post("/v1/reviews/{company}/correction")
    def corrected_source(
        company: str, body: Correction, x_admission_token: str = Header(default="")
    ):
        actor = reviewer(x_admission_token, company)
        return governance.resolve_corrected(
            config["reviewer_dsn"], company, body.quarantine_id, body.message_id, actor, body.reason
        )

    @app.post("/v1/business")
    def business_source(body: business.Business, x_admission_token: str = Header(default="")):
        identity = principal(x_admission_token)
        if identity["role"] != "source" or (identity["company"], identity["source"]) != (
            body.company,
            body.source,
        ):
            raise HTTPException(403, "source_scope_denied")
        return business.ingest(config["dsn"], body.model_dump())

    @app.post("/v1/handoff/{company}")
    def handoff(company: str, body: Handoff, x_admission_token: str = Header(default="")):
        if principal(x_admission_token)["role"] != "controller":
            raise HTTPException(403, "admission_controller_required")
        return execution.plan(config, company, body.canonical, body.references)

    @app.post("/v1/financial")
    def financial_source(body: finance.Financial, x_admission_token: str = Header(default="")):
        identity = principal(x_admission_token)
        if identity["role"] != "source" or (identity["company"], identity["source"]) != (
            body.company,
            body.source,
        ):
            raise HTTPException(403, "source_scope_denied")
        return finance.ingest(config["dsn"], body.model_dump())

    @app.post("/v1/outbound/{identifier}/step")
    def dispatch(identifier: UUID, x_admission_token: str = Header(default="")):
        if principal(x_admission_token)["role"] != "controller":
            raise HTTPException(403, "admission_controller_required")
        return {"state": execution.step(config, str(identifier))}

    if "console" in config:
        from .console import register

        register(app, config)
    return app


def factory():
    return create_app(
        json.loads(Path(os.environ["ONBOARDING_RUNTIME"]).read_text(encoding="utf-8"))
    )
