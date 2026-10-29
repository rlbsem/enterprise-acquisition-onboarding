"""Measured real PostgreSQL/HTTP/dbt portfolio acceptance, with independent source witnesses."""

import argparse
import copy
import json
import os
import platform
import statistics
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from psycopg.conninfo import conninfo_to_dict
import httpx
import psycopg
from .sandbox import Sandbox
from .portfolio_fixtures import Portfolio, ORIGINAL, RESTATED
from .portfolio_sources import Sources
from .portfolio_oracle import verify, identity
from .db import connect
from .contracts import digest
from .fixtures import canonical
from .business import fixtures as business_fixtures
from .execution import step
from .reporting import approve_policy, freeze, build, plain
from .engine import Refused


def save(path, body):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes((json.dumps(plain(body), indent=2, default=str) + "\n").encode())


def request(stack, route, body, company=None, source=None, expected=200, role="source"):
    with stack.client(role, company, source) as c:
        response = c.post(route, json=body)
    assert response.status_code == expected, (route, response.status_code)
    return response.json()


def intake_company(stack, sources, spec, index, started, recover=False):
    company = spec.companies[index][0]
    began = time.perf_counter()
    result = dict(
        company=company,
        started_seconds=began - started,
        source_errors=[],
        sent=0,
        deferred=[],
        withheld=[],
    )
    for domain in ["crm", "operations", "finance"]:
        try:
            documents = sources.fetch(company, domain)
        except httpx.TransportError as exc:
            result["source_errors"].append(dict(domain=domain, failure=type(exc).__name__))
            continue
        token_source = next(
            s for s, r in spec.contract(index)["sources"].items() if r["domain"] == domain
        )
        with stack.client("source", company, token_source) as c:
            for document in documents:
                body = document["body"]
                if (
                    spec.mode(index) == "coverage_held"
                    and domain == "operations"
                    and document["route"] == "/v1/intake"
                    and body["data"][spec.contract(index)["sources"][token_source]["id"]]
                    == str(99 + spec.customer_count(index))
                ):
                    continue
                if body.get("kind") == "intercompany_acceptance":
                    result["deferred"].append(body)
                    continue
                if (
                    not recover
                    and index == spec.count - 1
                    and body.get("kind") == "allocation"
                    and body["source_id"] == "A-100-01"
                ):
                    result["withheld"].append(body)
                    continue
                response = c.post(document["route"], json=body)
                assert response.status_code == 200, (
                    company,
                    document["route"],
                    response.status_code,
                )
                if document["route"] == "/v1/financial":
                    assert response.json()["status"] == "accepted", (
                        company,
                        body["source_id"],
                        response.json()["reason"],
                    )
                result["sent"] += 1
    admission_start = time.perf_counter()
    if spec.mode(index) != "pending_review":
        result["admission"] = request(stack, "/v1/admission/" + company, {}, role="controller")
    else:
        result["admission"] = {"passed": False, "not_requested": True}
    result["admission_seconds"] = time.perf_counter() - admission_start
    result["finished_seconds"] = time.perf_counter() - started
    return result


def authorization(stack, sources, spec):
    a, b = [x[0] for x in spec.companies[:2]]
    message = spec.messages(1)[0]
    with stack.client("source", a, spec.messages(0)[0]["source"]) as c:
        forged = c.post("/v1/intake", json=message)
        assert forged.status_code == 403
    # A genuine company leader cannot read or review another company's state.
    login = stack.console_credentials[a + "-leader"]
    with httpx.Client(base_url=stack.url, headers={"Origin": stack.url}, trust_env=False) as c:
        response = c.post(
            "/console/api/login",
            json={"username": login["username"], "password": login["password"]},
        )
        assert response.status_code == 200
        c.headers["X-CSRF-Token"] = response.json()["csrf"]
        assert c.get("/console/api/companies/" + b).status_code == 403
        assert (
            c.post(
                "/console/api/companies/" + b + "/admission",
                json={"reason": "Cross-company attempt"},
            ).status_code
            == 403
        )
    with httpx.Client(trust_env=False) as c:
        assert (
            c.get(
                sources.urls["shared"] + f"/companies/{b}/crm",
                headers={"X-Source-Token": sources.tokens[a]},
            ).status_code
            == 403
        )
    with connect(stack.console["read_dsn"]) as c:
        before = c.execute("SELECT id,status,gate_hash FROM companies ORDER BY id").fetchall()
    try:
        with connect(stack.console["read_dsn"]) as c:
            c.execute("UPDATE companies SET status='portfolio_ready' WHERE id=%s", (b,))
        raise AssertionError("read_identity_mutation_not_denied")
    except psycopg.errors.InsufficientPrivilege as exc:
        assert exc.sqlstate == "42501"
    wrong_entity = copy.deepcopy(message)
    rule = spec.contract(1)["sources"][message["source"]]
    wrong_entity["event_id"] = "controlled-wrong-entity"
    wrong_entity["data"][rule["entity"]] = spec.companies[0][2]
    denied = request(stack, "/v1/intake", wrong_entity, b, wrong_entity["source"])
    assert denied["status"] == "quarantined" and denied["reason"] == "incorrect_legal_entity"
    with connect(stack.console["read_dsn"]) as c:
        after = c.execute("SELECT id,status,gate_hash FROM companies ORDER BY id").fetchall()
    assert before == after
    return dict(
        cross_company_source_http=403,
        cross_company_console_read_http=403,
        cross_company_console_write_http=403,
        cross_company_feed_http=403,
        restricted_sql_mutation="42501",
        wrong_legal_entity="quarantined",
        company_state_unchanged=True,
        per_company_database_RLS=False,
    )


def handoffs(stack, spec, workers):
    with connect(stack.console["read_dsn"]) as c:
        ready = {
            r["id"] for r in c.execute("SELECT id FROM companies WHERE status='portfolio_ready'")
        }
    effects = []
    for i, (company, _, entity, _, _) in enumerate(spec.companies):
        if company not in ready:
            continue
        refs = {}
        for record in business_fixtures(
            company, entity, list(spec.contract(i)["sources"]), spec.version(i)
        ):
            record["event_id"] = "same-local-" + record["kind"]
            record["record_id"] = "LOCAL-" + record["kind"]
            if record["kind"] == "work_order":
                record["commercial_reference"] = "LOCAL-opportunity"
            assert (
                request(stack, "/v1/business", record, company, record["source"])["status"]
                == "accepted"
            )
            refs[record["kind"]] = record["record_id"]
        planned = request(
            stack,
            "/v1/handoff/" + company,
            {"canonical": canonical(company), "references": refs},
            role="controller",
        )
        effects.append((company, planned["effect_id"]))
    fault = effects[0][1] if len(effects) > 1 else None
    lost = effects[1][1] if len(effects) > 1 else None
    with httpx.Client(
        base_url=stack.receiver["url"],
        headers={"X-Receiver-Token": stack.receiver_injector},
        trust_env=False,
    ) as c:
        for effect, modes in [(fault, ["unavailable"] * 3), (lost, ["lost_ack"])]:
            if effect:
                assert (
                    c.post("/test/faults", json={"effect_id": effect, "modes": modes}).status_code
                    == 200
                )
    rounds = []
    for round_number in range(4):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            states = list(
                pool.map(
                    lambda item: step(
                        stack.sender_config,
                        item[1],
                        timeout=0.2 if item[1] == lost else 2,
                        respect_due=False,
                    ),
                    effects,
                )
            )
        rounds.append(
            dict(
                round=round_number + 1,
                states=dict(zip([c for c, _ in effects], states, strict=True)),
            )
        )
    with connect(stack.console["read_dsn"]) as c:
        persisted = c.execute(
            "SELECT effect_id,company,state,attempts,proof FROM outbound ORDER BY company"
        ).fetchall()
    with connect(stack.receiver_dsn) as c:
        receipts = c.execute("SELECT id,payload,hash,receipt FROM effects ORDER BY id").fetchall()
        records = c.execute("SELECT body FROM records ORDER BY id").fetchall()
        requests = c.execute(
            "SELECT effect_id,operation,status FROM requests ORDER BY id"
        ).fetchall()
    assert len(receipts) == len(effects) - (1 if fault else 0)
    assert len(records) == len(receipts)
    for row in persisted:
        if str(row["effect_id"]) == fault:
            assert row["state"] == "exhausted" and row["attempts"] == 3 and row["proof"] is None
        else:
            assert row["state"] == "confirmed" and row["attempts"] == 1
            remote = next(r for r in receipts if r["id"] == row["effect_id"])
            assert remote["receipt"] == row["proof"] and remote["hash"] == digest(remote["payload"])
            assert any(r["body"] == row["proof"]["record"] for r in records)
    assert sum(r["operation"] == "apply" and r["status"] == 201 for r in requests) == len(receipts)
    if lost:
        assert rounds[0]["states"][effects[1][0]] == "uncertain"
    return plain(
        dict(
            rounds=rounds,
            outbound=persisted,
            independent_receiver_receipts=receipts,
            independent_receiver_records=records,
            request_journal=requests,
            exhausted_queues=sum(r["state"] == "exhausted" for r in persisted),
            healthy_confirmed=len(receipts),
            lost_ack_exercised=bool(lost),
            same_local_business_ids=True,
            duplicate_business_effects=0,
            shared_receiver_failure_domain=True,
        )
    )


def lock_isolation(stack, spec):
    """Hold a genuine company lock; establish an actual blocked backend before the healthy request."""
    blocked, healthy = spec.companies[1][0], spec.companies[2][0]
    with connect(stack.admin_dsn) as blocker:
        blocker.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (blocked,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(request, stack, "/v1/admission/" + blocked, {}, role="controller")
            try:
                deadline = time.monotonic() + 5
                waiting = 0
                while time.monotonic() < deadline:
                    with connect(stack.admin_dsn) as observer:
                        waiting = observer.execute(
                            "SELECT count(*) n FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))",
                            (blocker.info.backend_pid,),
                        ).fetchone()["n"]
                    if waiting:
                        break
                    time.sleep(0.02)
                assert waiting > 0 and not future.done(), "native_company_lock_wait_not_established"
                began = time.perf_counter()
                result = request(stack, "/v1/admission/" + healthy, {}, role="controller")
                duration = time.perf_counter() - began
                assert result["passed"] and not future.done()
            finally:
                blocker.commit()
            assert not future.result(timeout=10)["passed"]
    return dict(
        actual_blocked_backends=waiting,
        healthy_admission_completed_while_other_lock_held=True,
        healthy_admission_seconds=duration,
        shared_server_isolation=False,
    )


def resources(stack, sources):
    import ctypes

    physical = None
    if os.name == "nt":

        class Memory(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                *[
                    (name, ctypes.c_ulonglong)
                    for name in [
                        "total",
                        "available",
                        "page_total",
                        "page_available",
                        "virtual_total",
                        "virtual_available",
                        "extended",
                    ]
                ],
            ]

        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            physical = memory.total
    elif Path("/proc/meminfo").exists():
        physical = int(Path("/proc/meminfo").read_text().split("MemTotal:")[1].split()[0]) * 1024
    with connect(stack.admin) as c:
        storage = {
            name: c.execute("SELECT pg_database_size(%s) n", (db,)).fetchone()["n"]
            for name, db in [
                ("control", stack.tag),
                ("receiver", stack.receiver_database),
                ("source", sources.database),
            ]
        }
        counters = c.execute(
            "SELECT xact_commit,xact_rollback,blks_read,blks_hit,temp_bytes,deadlocks FROM pg_stat_database WHERE datname=%s",
            (stack.tag,),
        ).fetchone()
        settings = {
            k: c.execute("SHOW " + k).fetchone()[k]
            for k in ["max_connections", "shared_buffers", "track_io_timing"]
        }
    return dict(
        host_physical_memory_bytes=physical,
        database_storage_bytes=storage,
        database_counters_snapshot=counters,
        PostgreSQL_settings=settings,
        container_memory_peak_bytes=read_limit("/sys/fs/cgroup/memory.peak"),
        measurement_scope="Separate database sizes and owned database statistics; orchestrator CPU excludes PostgreSQL and dbt child CPU; cgroup peak is container lifetime when available",
    )


def execute(stack, sources, spec, work, workers=4, keep_sources=False):
    began = time.perf_counter()
    cpu_started = time.process_time()
    sources.stop_company()
    submitted = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(intake_company, stack, sources, spec, i, submitted)
            for i in range(spec.count)
        ]
        runs = [f.result() for f in as_completed(futures)]
    runs.sort(key=lambda r: r["company"])
    assert len([r for r in runs if r["source_errors"]]) == 1
    for r in runs:
        for body in r.pop("deferred"):
            assert (
                request(stack, "/v1/financial", body, body["company"], body["source"])["status"]
                == "accepted"
            )
    # Same event identity with changed content holds only its company.
    duplicate = spec.messages(1)[0]
    assert request(stack, "/v1/intake", duplicate, duplicate["company"], duplicate["source"])[
        "duplicate"
    ]
    conflict = copy.deepcopy(duplicate)
    rule = spec.contract(1)["sources"][conflict["source"]]
    display = next(k for k, v in rule["fields"].items() if v == "display_name")
    conflict["data"][display] = "Conflicting Synthetic Name"
    rejected = request(stack, "/v1/intake", conflict, conflict["company"], conflict["source"])
    assert rejected["reason"] == "event_identity_content_conflict"
    scope = authorization(stack, sources, spec)
    locks = lock_isolation(stack, spec)
    ingestion_seconds = time.perf_counter() - began
    delivery = handoffs(stack, spec, workers)
    assert sources.processes["dedicated"].poll() is not None
    healthy = [
        r for i, r in enumerate(runs) if spec.expected_admitted(i) and r["admission"]["passed"]
    ]
    admission_requests = [
        r["admission_seconds"] for r in runs if not r["admission"].get("not_requested")
    ]
    assert healthy, "no_healthy_company_progress"
    expected = spec.financial()
    approve_policy(stack.reviewer_dsn, 1, spec.policy(expected))
    try:
        freeze(stack.reviewer_dsn, "coverage-gap", 1, ORIGINAL)
        raise AssertionError("incomplete_financial_snapshot_admitted")
    except Refused as exc:
        assert str(exc) == "financial_inventory_incomplete_or_unreviewed"
    with connect(stack.console["read_dsn"]) as c:
        assert (
            c.execute(
                "SELECT count(*) n FROM financial_snapshots WHERE id='coverage-gap'"
            ).fetchone()["n"]
            == 0
        )
    for r in runs:
        for body in r.pop("withheld"):
            assert (
                request(stack, "/v1/financial", body, body["company"], body["source"])["status"]
                == "accepted"
            )
    publication_start = time.perf_counter()
    freeze_start = time.perf_counter()
    freeze(stack.reviewer_dsn, "original", 1, ORIGINAL)
    freeze_seconds = time.perf_counter() - freeze_start
    original = build(stack, "original", Path(work) / "original")
    original_oracle = verify(stack, sources, spec, original, ORIGINAL)
    publication_seconds = time.perf_counter() - publication_start
    original_hash = digest(original["results"])
    with connect(stack.console["read_dsn"]) as c:
        original_inputs = c.execute(
            "SELECT event_id,hash FROM financial_inputs WHERE report_id='original' ORDER BY event_id"
        ).fetchall()
    sources.launch("dedicated")
    recovered = intake_company(stack, sources, spec, 0, submitted, recover=True)
    assert recovered["admission"]["passed"] and not recovered["source_errors"]
    for row in spec.corrections():
        sources.append([row], "/v1/financial")
    # Fetch corrections from the running persisted source feed, not generator-to-control insertion.
    correction_rows = [
        d["body"]
        for d in sources.fetch(spec.companies[2][0], "finance")
        if d["body"].get("revision") == 2
    ]
    assert len(correction_rows) == 3
    for body in correction_rows:
        assert (
            request(stack, "/v1/financial", body, body["company"], body["source"])["status"]
            == "accepted"
        )
    second_start = time.perf_counter()
    freeze(stack.reviewer_dsn, "restated", 1, RESTATED, "original")
    restated = build(stack, "restated", Path(work) / "restated")
    restated_oracle = verify(stack, sources, spec, restated, RESTATED, recovered=True)
    restatement_seconds = time.perf_counter() - second_start
    with connect(stack.reviewer_dsn) as c:
        c.execute("SET TRANSACTION READ ONLY")
        saved = c.execute(
            "SELECT results FROM financial_publications WHERE report_id='original'"
        ).fetchone()["results"]
        assert digest(saved) == original_hash
        assert (
            c.execute(
                "SELECT event_id,hash FROM financial_inputs WHERE report_id='original' ORDER BY event_id"
            ).fetchall()
            == original_inputs
        )
        stats = c.execute("SELECT pg_database_size(current_database()) database_bytes").fetchone()
        counts = {
            table: c.execute("SELECT count(*) n FROM " + table).fetchone()["n"]
            for table in [
                "messages",
                "source_records",
                "customer_fields",
                "financial_events",
                "outbound",
                "quarantine",
                "financial_publications",
            ]
        }
        statuses = c.execute(
            "SELECT id,status,active_mapping FROM companies ORDER BY id"
        ).fetchall()
        membership = (
            c.execute(
                "SELECT id,company,source,event_id,body->>'kind' kind,body->>'source_id' source_id,(body->>'revision')::int revision,hash,status FROM financial_events ORDER BY id"
            ).fetchall()
            if keep_sources
            else None
        )
    return plain(
        dict(
            schema_version="multi-company-execution.v1",
            synthetic=True,
            native_vendor_calls=0,
            company_count=spec.count,
            workers=workers,
            source_services=2,
            logical_databases=3,
            source_service_down_during_healthy_progress=True,
            healthy_companies_completed_before_source_restart=len(healthy),
            companies=runs,
            current_status=statuses,
            authorization=scope,
            contention_probe=locks,
            resource_observations=resources(stack, sources),
            duplicate_event=rejected,
            identity=identity(stack, spec),
            delivery=delivery,
            financial_inventory_gap=dict(
                rejected=True, partial_snapshot_rows=0, repaired_before_publication=True
            ),
            original_oracle=original_oracle,
            restated_oracle=restated_oracle,
            original_publication_hash=original_hash,
            original_publication_unchanged=True,
            original_input_membership_unchanged=True,
            original=original
            if keep_sources
            else {"dbt": original["dbt"], "status": original["status"]},
            restated=restated
            if keep_sources
            else {"dbt": restated["dbt"], "status": restated["status"]},
            source_observations=sources.financial() if keep_sources else None,
            control_financial_membership=membership,
            metrics=dict(
                ingestion_and_admission_seconds=ingestion_seconds,
                admission_latency_seconds=admission_requests,
                admission_request_count=len(admission_requests),
                pending_without_admission_request=spec.count - len(admission_requests),
                admission_latency_median=statistics.median(admission_requests),
                max_work_queue_delay_seconds=max(r["started_seconds"] for r in runs),
                healthy_admission_per_second=len(healthy) / ingestion_seconds,
                freeze_seconds=freeze_seconds,
                publication_seconds=publication_seconds,
                restatement_seconds=restatement_seconds,
                total_seconds=time.perf_counter() - began,
                orchestrator_cpu_seconds=time.process_time() - cpu_started,
                **stats,
                **counts,
            ),
            financial_definition="Separate bookings, invoice headers/lines, ERP postings, credits and payment allocations; no recognized revenue",
            shared_failure_domains=[
                "PostgreSQL server",
                "control API threads",
                "receiver HTTP process",
                "source database",
                "analytics schema",
            ],
            storage_partitioning_or_scheduler_change=False,
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--sizes", nargs="+", type=int, default=[3, 10, 25, 50])
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--serve", action="store_true")
    p.add_argument("--browser", action="store_true")
    p.add_argument("--binding-file", type=Path)
    args = p.parse_args()
    work, out = Path(args.workspace).resolve(), Path(args.output).resolve()
    if work.exists() or out.exists() or not 1 <= args.repeats <= 3 or not 1 <= args.workers <= 6:
        raise ValueError("fresh_paths_and_bounded_run_configuration_required")
    work.mkdir(parents=True)
    out.mkdir(parents=True)
    reports = []
    stamp = (
        json.loads(args.binding_file.read_bytes())
        if args.binding_file
        else {"qualification": "development_working_tree_not_source_bound"}
    )
    for size in args.sizes:
        for repeat in range(args.repeats):
            spec = Portfolio(size)
            name = f"companies-{size:03}-run-{repeat + 1:02}"
            with Sandbox(work / name, scenario=spec) as stack:
                with Sources(stack, spec) as sources:
                    result = execute(
                        stack,
                        sources,
                        spec,
                        work / name / "builds",
                        args.workers,
                        keep_sources=size == max(args.sizes) and repeat == 0,
                    )
                    result["runtime"] = dict(
                        PostgreSQL=stack_client_version(stack),
                        python=platform.python_version(),
                        os=platform.platform(),
                        cpu_count=os.cpu_count(),
                        container_memory_limit=read_limit("/sys/fs/cgroup/memory.max"),
                        container_cpu_limit=read_limit("/sys/fs/cgroup/cpu.max"),
                    )
                    result["source_binding"] = stamp
                    if args.browser and size == max(args.sizes) and repeat == 0:
                        from .portfolio_browser import capture

                        result["browser"] = capture(stack, spec, out / "browser")
                    save(out / (name + ".json"), result)
                    if args.serve:
                        print(
                            json.dumps(
                                {
                                    "url": stack.url + "/console",
                                    "private_credentials_path": str(
                                        stack.path / "console-credentials-private.json"
                                    ),
                                }
                            ),
                            flush=True,
                        )
                        try:
                            while True:
                                time.sleep(1)
                        except KeyboardInterrupt:
                            pass
                    owned_ports = [
                        urlsplit(url).port
                        for url in [stack.url, stack.receiver["url"], *sources.urls.values()]
                    ]
                    if stack.own:
                        owned_ports.append(int(conninfo_to_dict(stack.admin)["port"]))
            for port in owned_ports:
                with socket.socket() as connection:
                    connection.settimeout(0.3)
                    assert connection.connect_ex(("127.0.0.1", port)) != 0, (
                        "owned_listener_remains_after_teardown"
                    )
            assert all(
                p.poll() is not None
                for p in [stack.process, stack.receiver_process, *sources.processes.values()]
            )
            if stack.own:
                status = subprocess.run(
                    [stack.pg_ctl, "-D", str(stack.path / "pgdata"), "status"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                assert status.returncode == 3, "owned_PostgreSQL_not_independently_stopped"
            else:
                with psycopg.connect(stack.admin, autocommit=True) as observer:
                    assert (
                        observer.execute(
                            "SELECT count(*) FROM pg_database WHERE left(datname,%s)=%s",
                            (len(stack.tag), stack.tag),
                        ).fetchone()[0]
                        == 0
                    )
                    assert (
                        observer.execute(
                            "SELECT count(*) FROM pg_roles WHERE left(rolname,%s)=%s",
                            (len(stack.tag), stack.tag),
                        ).fetchone()[0]
                        == 0
                    )
            result["teardown"] = dict(
                independent_listener_checks=len(owned_ports),
                remaining_listeners=0,
                owned_processes_stopped=True,
                owned_PostgreSQL_stopped=stack.own,
                owned_database_and_roles_absence_checked=not stack.own,
            )
            result["owned_resources_cleaned"] = True
            save(out / (name + ".json"), result)
            reports.append(
                {
                    k: result[k]
                    for k in ["company_count", "metrics", "identity", "owned_resources_cleaned"]
                }
            )
            print(
                json.dumps(
                    {
                        "company_count": size,
                        "repeat": repeat + 1,
                        "status": "passed",
                        "seconds": result["metrics"]["total_seconds"],
                    }
                ),
                flush=True,
            )
    save(
        out / "summary.json",
        dict(
            executed_at=datetime.now(UTC).isoformat(),
            runs=reports,
            source_binding=stamp,
            native_vendor_calls=0,
            synthetic=True,
        ),
    )


def read_limit(path):
    return Path(path).read_text().strip() if Path(path).exists() else "unavailable_not_a_container"


def stack_client_version(stack):
    with connect(stack.console["read_dsn"]) as c:
        return c.execute("SHOW server_version").fetchone()["server_version"]


if __name__ == "__main__":
    main()
