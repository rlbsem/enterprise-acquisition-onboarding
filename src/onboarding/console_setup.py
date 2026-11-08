"""Owned local console users and restricted SQL identities; credentials never enter UI assets."""

import hashlib
import json
import os
import secrets
from importlib.resources import files
from psycopg import sql
from psycopg.conninfo import make_conninfo
import psycopg
from .db import connect
from .fixtures import COMPANIES


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + value


def setup(stack, companies=COMPANIES):
    stack.console_roles = []
    dsns = {}
    for kind in ["auth", "read"]:
        role = stack.tag + "_web_" + kind
        password = secrets.token_urlsafe(32)
        with psycopg.connect(stack.admin, autocommit=True) as c:
            c.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
            stack.console_roles.append(role)
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(stack.tag), sql.Identifier(role)
                )
            )
        dsns[kind] = make_conninfo(stack.admin_dsn, user=role, password=password)
    with connect(stack.admin_dsn) as c:
        c.execute(files("onboarding").joinpath("console.sql").read_text(encoding="utf-8"))
        for role in stack.console_roles:
            c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        c.execute(
            sql.SQL("GRANT SELECT,INSERT,DELETE ON console_sessions TO {}").format(
                sql.Identifier(stack.console_roles[0])
            )
        )
        c.execute(
            sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON console_login_attempts TO {}").format(
                sql.Identifier(stack.console_roles[0])
            )
        )
        c.execute(
            sql.SQL(
                "GRANT SELECT ON companies,systems,mapping_versions,customers,crosswalks,baselines,messages,quarantine,quarantine_resolutions,source_records,customer_fields,gate_runs,audit,reviews,review_decisions,source_record_history,business_events,business_heads,outbound,outbound_attempts,financial_snapshots,financial_inputs,financial_publications,financial_policies TO {}"
            ).format(sql.Identifier(stack.console_roles[1]))
        )
    definitions = [
        ("sponsor", "sponsor", [c[0] for c in companies], "portfolio-executive"),
        *((c + "-leader", "operator", [c], c + "-leader") for c, *_ in companies),
        (
            "reviewer",
            "reviewer",
            ["summit"] if companies == COMPANIES else [companies[0][0]],
            "acquisition-reviewer",
        ),
    ]
    users = []
    stack.console_credentials = {}
    for name, role, companies, actor in definitions:
        password = secrets.token_urlsafe(18)
        stack.console_credentials[name] = {
            "username": name,
            "password": password,
            "role": role,
            "companies": companies,
        }
        users.append(
            {
                "username": name,
                "password_hash": password_hash(password),
                "role": role,
                "companies": companies,
                "actor": actor,
            }
        )
    path = stack.path / "console-credentials-private.json"
    path.write_text(json.dumps(stack.console_credentials, indent=2), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return {
        "auth_dsn": dsns["auth"],
        "read_dsn": dsns["read"],
        "users": users,
        "dummy_hash": password_hash(secrets.token_urlsafe(18)),
    }
