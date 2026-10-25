"""Independent synthetic onboarding receiver with an atomic effect/receipt transaction."""

import json
import os
import secrets
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from .contracts import digest
from .db import connect

SCHEMA = """CREATE TABLE effects(id uuid PRIMARY KEY,payload jsonb NOT NULL,hash text NOT NULL,receipt jsonb NOT NULL);
CREATE TABLE records(id uuid PRIMARY KEY,body jsonb NOT NULL);
CREATE TABLE requests(id bigserial PRIMARY KEY,effect_id uuid,operation text NOT NULL,status integer NOT NULL,at timestamptz DEFAULT clock_timestamp());
CREATE TABLE faults(id uuid PRIMARY KEY,modes jsonb NOT NULL);
CREATE FUNCTION immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable_receiver_evidence'; END $$;
CREATE TRIGGER effects_immutable BEFORE UPDATE OR DELETE ON effects FOR EACH ROW EXECUTE FUNCTION immutable();
CREATE TRIGGER records_immutable BEFORE UPDATE OR DELETE ON records FOR EACH ROW EXECUTE FUNCTION immutable();"""


def record_for(payload):
    return {
        "id": str(uuid5(NAMESPACE_URL, payload["effect_id"] + ":workspace")),
        "kind": "internal_onboarding_handoff",
        **{
            k: payload[k]
            for k in [
                "company",
                "legal_entity",
                "canonical",
                "mapping_version",
                "admission_hash",
                "business",
            ]
        },
    }


def create_app(config):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def auth(x_receiver_token: str = Header(default="")):
        if not secrets.compare_digest(x_receiver_token, config["token"]):
            raise HTTPException(401, "receiver_identity_required")

    def inject(x_receiver_token: str = Header(default="")):
        if not secrets.compare_digest(x_receiver_token, config["injector"]):
            raise HTTPException(401, "fixture_injector_required")

    @app.get("/health")
    def health():
        return {"ready": True, "synthetic": True}

    @app.post("/test/faults", dependencies=[Depends(inject)])
    def fault(body: dict):
        if (
            not isinstance(body.get("modes"), list)
            or len(body["modes"]) > 5
            or any(m not in ["lost_ack", "unavailable"] for m in body["modes"])
        ):
            raise HTTPException(422, "finite_fault_modes_required")
        with connect(config["dsn"]) as c:
            c.execute(
                "INSERT INTO faults VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET modes=excluded.modes",
                (body["effect_id"], Jsonb(body["modes"])),
            )
        return {"configured": True}

    @app.post("/effects", dependencies=[Depends(auth)])
    def apply(body: dict, idempotency_key: str = Header(default="")):
        required = {
            "effect_id",
            "schema_version",
            "company",
            "legal_entity",
            "canonical",
            "mapping_version",
            "admission_hash",
            "sources",
            "business",
        }
        if (
            set(body) != required
            or body["schema_version"] != "onboarding-handoff.v1"
            or idempotency_key != body["effect_id"]
        ):
            raise HTTPException(422, "closed_handoff_contract_required")
        mode = "ok"
        with connect(config["dsn"]) as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,2))", (body["effect_id"],))
            old = c.execute("SELECT * FROM effects WHERE id=%s", (body["effect_id"],)).fetchone()
            if old:
                if old["payload"] != body or old["hash"] != digest(body):
                    raise HTTPException(409, "idempotency_content_conflict")
                c.execute(
                    "INSERT INTO requests(effect_id,operation,status) VALUES(%s,'duplicate',200)",
                    (body["effect_id"],),
                )
                return old["receipt"]
            fault = c.execute(
                "SELECT modes FROM faults WHERE id=%s", (body["effect_id"],)
            ).fetchone()
            if fault and fault["modes"]:
                mode = fault["modes"][0]
                c.execute(
                    "UPDATE faults SET modes=%s WHERE id=%s",
                    (Jsonb(fault["modes"][1:]), body["effect_id"]),
                )
            if mode != "unavailable":
                record = record_for(body)
                proof = {
                    "effect_id": body["effect_id"],
                    "payload": body,
                    "payload_hash": digest(body),
                    "record": record,
                    "record_hash": digest(record),
                }
                c.execute("INSERT INTO records VALUES(%s,%s)", (record["id"], Jsonb(record)))
                c.execute(
                    "INSERT INTO effects VALUES(%s,%s,%s,%s)",
                    (body["effect_id"], Jsonb(body), digest(body), Jsonb(proof)),
                )
            c.execute(
                "INSERT INTO requests(effect_id,operation,status) VALUES(%s,'apply',%s)",
                (body["effect_id"], 503 if mode == "unavailable" else 201),
            )
        if mode == "unavailable":
            return JSONResponse(
                status_code=503, content={"error": "fixture_unavailable_before_commit"}
            )
        if mode == "lost_ack":
            time.sleep(1.5)
        return proof

    @app.get("/effects/{identifier}", dependencies=[Depends(auth)])
    def receipt(identifier: str, company: str):
        with connect(config["dsn"]) as c:
            row = c.execute(
                "SELECT receipt FROM effects WHERE id=%s AND payload->>'company'=%s",
                (identifier, company),
            ).fetchone()
            c.execute(
                "INSERT INTO requests(effect_id,operation,status) VALUES(%s,'readback',%s)",
                (identifier, 200 if row else 404),
            )
        if not row:
            raise HTTPException(404, "effect_not_found_in_scope")
        return row["receipt"]

    @app.get("/records/{identifier}", dependencies=[Depends(auth)])
    def record(identifier: str, company: str):
        with connect(config["dsn"]) as c:
            row = c.execute(
                "SELECT body FROM records WHERE id=%s AND body->>'company'=%s",
                (identifier, company),
            ).fetchone()
        if not row:
            raise HTTPException(404, "record_not_found_in_scope")
        return row["body"]

    return app


def factory():
    return create_app(
        json.loads(Path(os.environ["ONBOARDING_RECEIVER_RUNTIME"]).read_text(encoding="utf-8"))
    )
