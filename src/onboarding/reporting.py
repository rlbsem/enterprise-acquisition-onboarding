"""Immutable source snapshots, real dbt builds and publish only after independent agreement."""

import json
import os
import secrets
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
from .contracts import digest
from .db import connect, lock
from .engine import require, inspect_gate, audit
from .sandbox import child_env
from .financial_oracle import calculate

ROOT = Path(__file__).resolve().parents[2]


def plain(v):
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        require(v == int(v), "noninteger_financial_result")
        return int(v)
    return v


def controls(c, policy):
    result = {}
    for company, member in sorted(policy["perimeter"].items()):
        lock(c, company)
        row = c.execute("SELECT * FROM companies WHERE id=%s", (company,)).fetchone()
        require(
            row
            and member["legal_entity"] == row["legal_entity"]
            and member["acquired_on"] == row["acquired_on"].isoformat(),
            "reporting_registry_policy_mismatch",
        )
        gate = inspect_gate(c, company)
        result[company] = {
            **member,
            "mapping_version": row["active_mapping"],
            "admitted": row["status"] == "portfolio_ready"
            and gate["passed"]
            and row["gate_hash"] == gate["input_hash"],
            "gate": gate,
        }
    return result


def selected(c, cutoff):
    return c.execute(
        """SELECT DISTINCT ON(company,body->>'kind',body->>'source_id') id AS event_id,body,hash
    FROM financial_events WHERE status='accepted' AND (body->>'observed_at')::timestamptz<=%s
    ORDER BY company,body->>'kind',body->>'source_id',(body->>'revision')::int DESC""",
        (cutoff,),
    ).fetchall()


def approve_policy(dsn, version, body):
    require(
        body["schema_version"] == "portfolio-financial-policy.v1" and body["currency"] == "USD",
        "unsupported_financial_policy",
    )
    require(body["actor"].strip() and body["reason"].strip(), "financial_policy_review_required")
    require(
        body["elimination"] == "one_exact_charge_and_independent_counterparty_acceptance.v1",
        "unsupported_elimination_policy",
    )
    require(
        body["basis"]
        == "document_and_allocation_dates; no_preacquisition_carryforward; no_recognized_revenue",
        "unsupported_financial_basis",
    )
    require(
        len(set(body["periods"])) == len(body["periods"])
        and all(date.fromisoformat(p).day == 1 for p in body["periods"]),
        "calendar_periods_required",
    )
    with connect(dsn) as c:
        controls(c, body)
        previous = c.execute(
            "SELECT coalesce(max(version),0) v FROM financial_policies"
        ).fetchone()["v"]
        require(version == previous + 1, "policy_version_must_advance")
        c.execute(
            "INSERT INTO financial_policies(version,body,hash,actor,reason) VALUES(%s,%s,%s,%s,%s)",
            (version, Jsonb(body), digest(body), body["actor"], body["reason"]),
        )
        for company in body["perimeter"]:
            audit(
                c,
                company,
                "financial_policy_approved",
                version,
                {"actor": body["actor"], "reason": body["reason"], "hash": digest(body)},
            )


def freeze(dsn, report, version, cutoff, previous=None):
    require(re.fullmatch(r"[a-z0-9_-]{1,64}", report), "bounded_report_identifier_required")
    cutoff_time = datetime.fromisoformat(cutoff)
    require(cutoff_time.utcoffset() is not None, "aware_reporting_cutoff_required")
    cutoff = cutoff_time.astimezone(UTC).isoformat()
    with connect(dsn) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        policy = c.execute(
            "SELECT body FROM financial_policies WHERE version=%s", (version,)
        ).fetchone()["body"]
        control = controls(c, policy)
        inputs = selected(c, cutoff)
        actual = {company: {} for company in policy["perimeter"]}
        for row in inputs:
            b = row["body"]
            require(b["company"] in actual, "source_outside_policy_perimeter")
            actual[b["company"]].setdefault(b["kind"], []).append(b["source_id"])
            require(
                b["mapping_version"] == control[b["company"]]["mapping_version"],
                "financial_mapping_requires_resnapshot",
            )
            require(row["hash"] == digest(b), "financial_source_hash_mismatch")
        expected = {
            company: {k: sorted(ids) for k, ids in kinds.items()}
            for company, kinds in policy["inventory"].items()
        }
        require(actual == expected, "financial_inventory_incomplete_or_unreviewed")
        if previous:
            before = c.execute(
                "SELECT s.*,p.report_id AS published FROM financial_snapshots s LEFT JOIN financial_publications p ON p.report_id=s.id WHERE s.id=%s",
                (previous,),
            ).fetchone()
            require(
                before and before["published"] and cutoff_time > before["cutoff"],
                "published_earlier_report_required",
            )
        fingerprint = digest(
            {"control": control, "policy": policy, "cutoff": cutoff, "inputs": inputs}
        )
        c.execute(
            "INSERT INTO financial_snapshots(id,policy_version,cutoff,previous_id,control,input_hash) VALUES(%s,%s,%s,%s,%s,%s)",
            (report, version, cutoff, previous, Jsonb(control), fingerprint),
        )
        for r in inputs:
            c.execute(
                "INSERT INTO financial_inputs VALUES(%s,%s,%s,%s)",
                (report, r["event_id"], Jsonb(r["body"]), r["hash"]),
            )
        for company in control:
            audit(
                c,
                company,
                "financial_snapshot_frozen",
                report,
                {"input_hash": fingerprint, "policy_version": version},
            )
    return {
        "id": report,
        "input_hash": fingerprint,
        "source_records": len(inputs),
        "control": control,
    }


def oracle(c, report):
    snapshot = c.execute("SELECT * FROM financial_snapshots WHERE id=%s", (report,)).fetchone()
    policy = c.execute(
        "SELECT body FROM financial_policies WHERE version=%s", (snapshot["policy_version"],)
    ).fetchone()["body"]
    inputs = c.execute(
        "SELECT event_id,body,hash FROM financial_inputs WHERE report_id=%s ORDER BY event_id",
        (report,),
    ).fetchall()
    previous = (
        oracle(c, snapshot["previous_id"])["portfolio_totals"] if snapshot["previous_id"] else None
    )
    return calculate(inputs, snapshot["control"], policy, previous)


def sorted_rows(rows):
    return sorted(plain(rows), key=lambda row: json.dumps(row, sort_keys=True))


def compare(expected, actual):
    require(set(expected) == set(actual), "financial_model_inventory_mismatch")
    outcomes = []
    for name, rows in expected.items():
        require(sorted_rows(rows) == sorted_rows(actual[name]), "financial_oracle_mismatch:" + name)
        outcomes.append(
            {
                "model": name,
                "expected_rows": len(rows),
                "observed_rows": len(actual[name]),
                "exact_content_match": True,
                "sha256": digest(sorted_rows(rows)),
                "observed_sha256": digest(sorted_rows(actual[name])),
                "row_differences": 0,
            }
        )
    return outcomes


def warehouse(stack):
    if getattr(stack, "warehouse_role", None):
        return stack.warehouse_dsn
    stack.warehouse_role = stack.tag + "_analytics"
    password = secrets.token_urlsafe(32)
    with psycopg.connect(stack.admin, autocommit=True) as c:
        c.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(stack.warehouse_role), sql.Literal(password)
            )
        )
        c.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(stack.tag), sql.Identifier(stack.warehouse_role)
            )
        )
    with connect(stack.admin_dsn) as c:
        role = sql.Identifier(stack.warehouse_role)
        c.execute(sql.SQL("CREATE SCHEMA analytics AUTHORIZATION {}").format(role))
        c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        c.execute(
            sql.SQL(
                "GRANT SELECT ON financial_inputs,financial_snapshots,financial_policies,financial_publications TO {}"
            ).format(role)
        )
    stack.warehouse_dsn = make_conninfo(
        stack.admin_dsn, user=stack.warehouse_role, password=password
    )
    return stack.warehouse_dsn


def build(stack, report, work, expect_success=True):
    dsn = warehouse(stack)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    cfg = conninfo_to_dict(dsn)
    profile = {
        "acquisition_finance": {
            "target": "local",
            "outputs": {
                "local": {
                    "type": "postgres",
                    "host": cfg["host"],
                    "port": int(cfg["port"]),
                    "user": cfg["user"],
                    "password": "{{ env_var('DBT_ENV_SECRET_LOCAL_PASSWORD') }}",
                    "dbname": cfg["dbname"],
                    "schema": "analytics",
                    "threads": 1,
                    "sslmode": "disable",
                }
            },
        }
    }
    # JSON is valid YAML. Credentials remain in a child environment, not in dbt artifacts.
    profile_path = work / "profiles.yml"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    if os.name != "nt":
        profile_path.chmod(0o600)
    args = [
        sys.executable,
        "-c",
        "from dbt.cli.main import cli; cli()",
        "build",
        "--project-dir",
        str(ROOT / "warehouse"),
        "--profiles-dir",
        str(work),
        "--target-path",
        str(work / "target"),
        "--log-path",
        str(work / "logs"),
        "--vars",
        json.dumps({"report_id": report}),
        "--no-partial-parse",
    ]
    env = child_env(
        {
            "DBT_ENV_SECRET_LOCAL_PASSWORD": cfg["password"],
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            "DO_NOT_TRACK": "1",
        }
    )
    with (work / "dbt-private.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    require(
        result.returncode == 0 if expect_success else result.returncode != 0,
        "unexpected_dbt_build_outcome; inspect private log",
    )
    raw = json.loads((work / "target/run_results.json").read_text(encoding="utf-8"))
    summary = {
        "dbt_version": raw["metadata"]["dbt_version"],
        "return_code": result.returncode,
        "results": [
            {
                "id": r["unique_id"],
                "status": r["status"],
                "failures": r.get("failures"),
                "execution_seconds": r["execution_time"],
            }
            for r in raw["results"]
        ],
    }
    if not expect_success:
        return summary
    require(
        all(r["status"] in ["success", "pass"] for r in summary["results"]),
        "dbt_required_nodes_not_passed",
    )
    with connect(stack.warehouse_dsn) as c:
        expected = oracle_snapshot(stack, report)
        actual = {
            name: plain(
                c.execute(
                    sql.SQL("SELECT * FROM analytics.{}").format(sql.Identifier(name))
                ).fetchall()
            )
            for name in expected
        }
        exclusions = plain(
            c.execute(
                "SELECT event_id,company,source_id,kind,amount_minor,inclusion_reason FROM analytics.stg_financial WHERE NOT eligible ORDER BY event_id"
            ).fetchall()
        )
    outcomes = compare(expected, actual)
    with connect(stack.reviewer_dsn) as c:
        snapshot = c.execute("SELECT * FROM financial_snapshots WHERE id=%s", (report,)).fetchone()
        policy = c.execute(
            "SELECT body FROM financial_policies WHERE version=%s", (snapshot["policy_version"],)
        ).fetchone()["body"]
        require(
            controls(c, policy) == snapshot["control"],
            "reporting_control_changed_before_publication",
        )
        current = selected(c, snapshot["cutoff"])
        original = c.execute(
            "SELECT event_id,body,hash FROM financial_inputs WHERE report_id=%s ORDER BY event_id",
            (report,),
        ).fetchall()
        require(
            sorted_rows(current) == sorted_rows(original),
            "reporting_sources_changed_before_publication",
        )
        require(
            snapshot["input_hash"]
            == digest(
                {
                    "control": snapshot["control"],
                    "policy": policy,
                    "cutoff": snapshot["cutoff"].astimezone(UTC).isoformat(),
                    "inputs": current,
                }
            ),
            "financial_frozen_manifest_mismatch",
        )
        c.execute(
            "INSERT INTO financial_publications(report_id,results,comparisons,bridge) VALUES(%s,%s,%s,%s)",
            (report, Jsonb(actual), Jsonb(outcomes), Jsonb(actual["restatement_bridge"])),
        )
        for company in snapshot["control"]:
            audit(
                c,
                company,
                "financial_report_published",
                report,
                {
                    "policy_version": snapshot["policy_version"],
                    "open_variances": len(actual["reconciliation_variances"]),
                    "result_hash": digest(actual),
                },
            )
    return {
        "report_id": report,
        "status": "reconciled_with_open_variances"
        if actual["reconciliation_variances"]
        else "reconciled",
        "dbt": summary,
        "comparisons": outcomes,
        "results": actual,
        "excluded_source_records": exclusions,
    }


def oracle_snapshot(stack, report):
    with connect(stack.reviewer_dsn) as c:
        return oracle(c, report)
