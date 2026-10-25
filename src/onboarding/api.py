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

    return app


def factory():
    return create_app(
        json.loads(Path(os.environ["ONBOARDING_RUNTIME"]).read_text(encoding="utf-8"))
    )
