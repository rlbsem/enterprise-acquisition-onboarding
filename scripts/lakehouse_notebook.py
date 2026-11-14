# Databricks notebook source
"""Native Spark/Delta acceptance. Uploaded with a frozen, independently calculated fixture."""

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone

UTC = timezone.utc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def run(spark, dbutils, fixture):
    for name in ["schema", "phase", "revision", "fixture_hash"]:
        dbutils.widgets.text(name, "")
    schema, phase, revision, expected_hash = [
        dbutils.widgets.get(n) for n in ["schema", "phase", "revision", "fixture_hash"]
    ]
    assert re.fullmatch(r"acq_lh_[a-z0-9]{8,28}", schema), "namespace_refused"
    assert sha(fixture) == expected_hash, "fixture_content_changed"
    ns = "workspace." + schema
    out = dict(
        schema="lakehouse-native.v1",
        phase=phase,
        source_commit=revision,
        fixture_sha256=expected_hash,
        synthetic=True,
        observations=[],
        started_at_utc=datetime.now(UTC).isoformat(),
    )
    out["runtime"] = dict(python=sys.version, spark=spark.version)

    def sql(query):
        return spark.sql(query.replace("{ns}", ns))

    def rows(query):
        return [r.asDict(recursive=True) for r in sql(query).collect()]

    def observe(name, value):
        out["observations"].append(dict(check=name, result=value))

    def version(table):
        return rows(f"DESCRIBE HISTORY {{ns}}.{table} LIMIT 1")[0]["version"]

    def require(name, actual, expected):
        assert actual == expected, name
        observe(name, dict(equal=True, actual=actual, expected=expected))

    if phase != "pilot":
        properties = {
            r["database_description_item"]: r["database_description_value"]
            for r in rows("DESCRIBE SCHEMA EXTENDED {ns}")
        }
        assert expected_hash in properties.get("Comment", ""), "exact_run_ownership_required"

    if phase == "observer":
        observe("published", rows("SELECT * FROM {ns}.publications ORDER BY publication_id"))
        observe(
            "history",
            {
                t: [
                    dict(
                        version=r["version"],
                        operation=r["operation"],
                        metrics=r["operationMetrics"],
                    )
                    for r in rows(f"DESCRIBE HISTORY {{ns}}.{t}")
                ]
                for t in ["bronze", "candidates", "publications"]
            },
        )
        observe("bronze_rows", rows("SELECT count(*) n FROM {ns}.bronze")[0]["n"])
        for label, expected in fixture["expected"].items():
            r = rows(f"SELECT result_json FROM {{ns}}.publications WHERE publication_id='{label}'")
            if r:
                require(label + "_independent_readback", json.loads(r[0]["result_json"]), expected)
        for name, query in [
            (
                "usage",
                "SELECT sku_name,usage_unit,sum(usage_quantity) quantity FROM system.billing.usage WHERE usage_date >= current_date()-1 GROUP BY sku_name,usage_unit",
            ),
            (
                "rates",
                "SELECT sku_name,currency_code,usage_unit,cast(pricing.default as string) default_price,price_start_time,price_end_time FROM system.billing.list_prices WHERE cloud='AWS' AND sku_name LIKE '%SERVERLESS%JOBS%' AND price_end_time IS NULL",
            ),
            (
                "lineage",
                f"SELECT source_table_full_name,target_table_full_name FROM system.access.table_lineage WHERE target_table_schema='{schema}' OR source_table_schema='{schema}' LIMIT 100",
            ),
        ]:
            try:
                observe(name, rows(query))
            except Exception as e:
                observe(name, dict(available=False, error_class=type(e).__name__))
    elif phase == "cleanup":
        props = {
            r["database_description_item"]: r["database_description_value"]
            for r in rows("DESCRIBE SCHEMA EXTENDED {ns}")
        }
        assert expected_hash in props.get("Comment", ""), "cleanup_ownership_mismatch"
        sql("DROP SCHEMA {ns} CASCADE").collect()
        require("namespace_absent", rows(f"SHOW SCHEMAS IN workspace LIKE '{schema}'"), [])
        observe("billing_clearance", False)
    elif phase == "governance":
        observe(
            "executing_principal_sha256",
            sha(rows("SELECT current_user() principal")[0]["principal"]),
        )
        visible = rows("SELECT DISTINCT company, legal_entity FROM {ns}.company_view")
        require(
            "company_scoped_read",
            visible,
            [{k: fixture["controls"][0][k] for k in ["company", "legal_entity"]}],
        )
        for name, query in [
            ("raw_read_denied", "SELECT * FROM {ns}.bronze LIMIT 1"),
            ("write_denied", "DELETE FROM {ns}.publications WHERE publication_id='never'"),
            ("schema_create_denied", "CREATE VIEW {ns}.unapproved AS SELECT 1 n"),
        ]:
            try:
                sql(query).collect()
            except Exception as e:
                code = e.getErrorClass() if hasattr(e, "getErrorClass") else type(e).__name__
                assert any(
                    s in str(e)
                    for s in [
                        "INSUFFICIENT_PERMISSIONS",
                        "PERMISSION_DENIED",
                        "does not have",
                        "not authorized",
                    ]
                ), "unrelated_error_not_permission_proof"
                observe(name, dict(denied=True, error_class=code))
            else:
                raise AssertionError(name + "_unexpectedly_allowed")
    elif phase == "fault":
        require(
            "original_still_published",
            rows("SELECT publication_id FROM {ns}.publications ORDER BY publication_id"),
            [dict(publication_id="original")],
        )
        sql(
            "CREATE TABLE {ns}.fault_journal USING DELTA AS SELECT 'committed_before_task_failure' boundary"
        ).collect()
        raise RuntimeError("controlled_task_failure_after_delta_commit")
    elif phase == "scale":
        metrics = []
        for size in [100_000, 1_000_000]:
            start = time.monotonic()
            # Distributed synthetic financial facts; bounded values and independently derived totals.
            df = spark.range(size).selectExpr(
                "id",
                "concat('company-',cast(id%50 as string)) company",
                "cast(10000+id%1000 as bigint) amount_minor",
            )
            df.write.format("delta").mode("overwrite").saveAsTable(ns + ".scale_facts")
            summary = rows(
                "SELECT count(*) n,sum(amount_minor) total,count(DISTINCT company) companies FROM {ns}.scale_facts"
            )[0]
            require(
                f"scale_{size}_financial",
                summary,
                dict(n=size, total=(size // 1000) * (1000 * 10000 + 999 * 1000 // 2), companies=50),
            )
            grouped = rows(
                "SELECT company,sum(amount_minor) total FROM {ns}.scale_facts GROUP BY company ORDER BY company"
            )
            expected_groups = sorted(
                [dict(company=f"company-{c}", total=(size // 50) * (10475 + c)) for c in range(50)],
                key=lambda r: r["company"],
            )
            require(f"scale_{size}_company_separation", grouped, expected_groups)
            plan = "\n".join(
                r[0]
                for r in sql(
                    "EXPLAIN FORMATTED SELECT company,sum(amount_minor) FROM {ns}.scale_facts GROUP BY company"
                ).collect()
            )
            plan = re.sub(r"(?:s3[a-z0-9]*|abfss|gs)://[^\s\]\)]+", "[managed-storage-path]", plan)
            metrics.append(
                dict(
                    rows=size,
                    seconds=time.monotonic() - start,
                    measurement_scope="Delta write, independent financial checks and plan capture; not an ingestion-only benchmark",
                    plan=plan,
                    table_version=version("scale_facts"),
                )
            )
        observe("scale_measurements", metrics)
    else:
        if phase == "pilot":
            sql(
                f"CREATE SCHEMA {{ns}} COMMENT 'synthetic acquisition acceptance {expected_hash}'"
            ).collect()
            sql("ALTER SCHEMA {ns} DISABLE PREDICTIVE OPTIMIZATION").collect()
            props = rows("DESCRIBE SCHEMA EXTENDED {ns}")
            optimization = [
                r for r in props if "predictive" in r["database_description_item"].lower()
            ]
            observe("predictive_optimization", optimization)
            sql(
                "CREATE TABLE {ns}.publications(publication_id STRING, result_json STRING, source_hash STRING) USING DELTA"
            ).collect()
            sql(
                "CREATE TABLE {ns}.candidates(publication_id STRING, result_json STRING, source_hash STRING) USING DELTA"
            ).collect()
            sql("CREATE VOLUME {ns}.checkpoints").collect()
            controls = spark.createDataFrame(fixture["controls"])
            controls.write.format("delta").saveAsTable(ns + ".controls")

        field_types = {
            k: ("long" if k in ["revision", "mapping_version", "amount_minor"] else "string")
            for k in fixture["baseline"][0]
        }
        fields = list(field_types) + ["event_hash"]
        types = ",".join(f"{k} {field_types.get(k, 'string')}" for k in fields)

        def ingest(bodies):
            records = [tuple([b.get(k) for k in fields[:-1]] + [sha(b)]) for b in bodies]
            frame = spark.createDataFrame(records, types)
            frame.createOrReplaceTempView("incoming")
            # Authority is checked independently of supplied owner labels; no cross-company joins.
            sql(
                """CREATE OR REPLACE TEMP VIEW valid_input AS SELECT i.* FROM incoming i JOIN {ns}.controls c ON i.company=c.company AND i.legal_entity=c.legal_entity AND i.mapping_version=c.mapping_version WHERE i.currency='USD' AND ((i.kind='booking' AND i.owner='crm' AND i.source=c.crm) OR (i.kind<>'booking' AND i.owner='finance' AND i.source=c.finance)) AND i.amount_minor<>0 AND (i.amount_minor>0 OR i.kind='erp_posting')"""
            ).collect()
            rejected = frame.count() - sql("SELECT * FROM valid_input").count()
            if not spark.catalog.tableExists(ns + ".bronze"):
                sql(
                    "CREATE TABLE {ns}.bronze USING DELTA TBLPROPERTIES(delta.enableChangeDataFeed=true) AS SELECT * FROM valid_input WHERE false"
                ).collect()
                sql(
                    "ALTER TABLE {ns}.bronze ADD CONSTRAINT nonnull_amount CHECK (amount_minor IS NOT NULL)"
                ).collect()
            conflicts = rows(
                """SELECT count(*) n FROM (SELECT company,source,kind,source_id,revision FROM (SELECT * FROM {ns}.bronze UNION ALL SELECT * FROM valid_input) GROUP BY company,source,kind,source_id,revision HAVING count(DISTINCT event_hash)>1)"""
            )[0]["n"]
            if conflicts:
                raise ValueError("same_revision_content_conflict")
            sql(
                """MERGE INTO {ns}.bronze t USING (SELECT DISTINCT * FROM valid_input) s ON t.company=s.company AND t.source=s.source AND t.kind=s.kind AND t.source_id=s.source_id AND t.revision=s.revision WHEN NOT MATCHED THEN INSERT *"""
            ).collect()
            return rejected

        def project(label):
            cutoff = fixture["cutoffs"][label]
            require(
                "frozen_control_unchanged",
                rows("SELECT * FROM {ns}.controls ORDER BY company"),
                sorted(fixture["controls"], key=lambda r: r["company"]),
            )
            sql(
                f"""CREATE OR REPLACE TEMP VIEW latest_snapshot AS SELECT * EXCEPT(rn) FROM (SELECT b.*,row_number() OVER(PARTITION BY company,kind,source_id ORDER BY revision DESC) rn FROM {{ns}}.bronze b WHERE observed_at<='{cutoff}') WHERE rn=1"""
            ).collect()
            if not spark.catalog.tableExists(ns + ".silver"):
                sql(
                    "CREATE TABLE {ns}.silver USING DELTA AS SELECT * FROM latest_snapshot WHERE false"
                ).collect()
            sql(
                "MERGE INTO {ns}.silver t USING latest_snapshot s ON t.company=s.company AND t.kind=s.kind AND t.source_id=s.source_id WHEN MATCHED AND s.revision>t.revision THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *"
            ).collect()
            difference = rows(
                "SELECT count(*) n FROM ((SELECT * FROM latest_snapshot EXCEPT ALL SELECT * FROM {ns}.silver) UNION ALL (SELECT * FROM {ns}.silver EXCEPT ALL SELECT * FROM latest_snapshot))"
            )[0]["n"]
            require(label + "_incremental_full_snapshot_parity", difference, 0)
            sql(
                """CREATE OR REPLACE TEMP VIEW base AS SELECT b.* FROM {ns}.silver b JOIN {ns}.controls c ON b.company=c.company AND b.legal_entity=c.legal_entity WHERE c.admitted AND b.transaction_date>=c.acquired_on AND substring(b.transaction_date,1,7) IN ('2026-01','2026-10')"""
            ).collect()
            sql(
                """CREATE OR REPLACE TABLE {ns}.eligible USING DELTA AS SELECT b.* FROM base b WHERE (b.invoice_id IS NULL OR EXISTS(SELECT 1 FROM base i WHERE i.company=CASE WHEN b.kind='intercompany_acceptance' THEN b.counterparty_company ELSE b.company END AND i.kind='invoice' AND i.source_id=b.invoice_id)) AND (b.payment_id IS NULL OR EXISTS(SELECT 1 FROM base p WHERE p.company=b.company AND p.kind='payment' AND p.source_id=b.payment_id))"""
            ).collect()
            sql(
                """CREATE OR REPLACE TABLE {ns}.invoices USING DELTA AS SELECT h.company,h.legal_entity,h.source_id invoice_id,concat(substring(h.transaction_date,1,7),'-01') period,h.currency,h.amount_minor gross_minor,h.counterparty_company,h.counterparty_entity,coalesce(sum(CASE WHEN c.kind='invoice_line' THEN c.amount_minor END),0) lines_minor,coalesce(sum(CASE WHEN c.kind='credit' THEN c.amount_minor END),0) credits_minor,h.amount_minor-coalesce(sum(CASE WHEN c.kind='credit' THEN c.amount_minor END),0) net_minor,coalesce(sum(CASE WHEN c.kind='erp_posting' THEN c.amount_minor END),0) erp_minor,count(CASE WHEN c.kind='erp_posting' THEN 1 END) erp_count FROM {ns}.eligible h LEFT JOIN {ns}.eligible c ON h.company=c.company AND h.source_id=c.invoice_id AND c.kind IN ('invoice_line','credit','erp_posting') WHERE h.kind='invoice' GROUP BY ALL"""
            ).collect()
            sql(
                """CREATE OR REPLACE TABLE {ns}.eliminations USING DELTA AS SELECT i.company,i.invoice_id,i.period,i.net_minor,CASE WHEN i.erp_minor=i.net_minor AND (SELECT count(*) FROM {ns}.eligible a WHERE a.company=i.company AND a.kind='allocation' AND a.invoice_id=i.invoice_id)=0 AND (SELECT count(*) FROM {ns}.eligible c JOIN {ns}.eligible a ON a.company=i.counterparty_company AND a.kind='intercompany_acceptance' AND a.invoice_id=i.invoice_id AND a.counterparty_company=i.company AND a.counterparty_entity=i.legal_entity AND a.link_id=c.link_id AND a.amount_minor=i.net_minor AND a.currency=i.currency WHERE c.company=i.company AND c.kind='intercompany_charge' AND c.invoice_id=i.invoice_id AND c.counterparty_company=i.counterparty_company AND c.counterparty_entity=i.counterparty_entity AND c.amount_minor=i.net_minor AND c.currency=i.currency)=1 THEN i.net_minor ELSE 0 END elimination_minor FROM {ns}.invoices i WHERE i.counterparty_company IS NOT NULL"""
            ).collect()
            # Every legal entity/period is retained, including excluded zero rows.
            sql(
                """CREATE OR REPLACE TABLE {ns}.gold USING DELTA AS WITH amounts AS (SELECT company,concat(substring(transaction_date,1,7),'-01') period,sum(CASE WHEN kind='booking' THEN amount_minor ELSE 0 END) bookings_minor,sum(CASE WHEN kind='erp_posting' THEN amount_minor ELSE 0 END) erp_posted_minor,sum(CASE WHEN kind='allocation' THEN amount_minor ELSE 0 END) allocated_cash_minor FROM {ns}.eligible GROUP BY ALL), inv AS (SELECT company,period,sum(gross_minor) gross_invoice_minor,sum(credits_minor) credits_minor,sum(net_minor) net_invoice_minor FROM {ns}.invoices GROUP BY ALL), elim AS (SELECT company,period,sum(elimination_minor) elimination_minor FROM {ns}.eliminations GROUP BY ALL) SELECT c.company,c.legal_entity,p.period,'USD' currency,coalesce(a.bookings_minor,0) bookings_minor,coalesce(i.gross_invoice_minor,0) gross_invoice_minor,coalesce(i.credits_minor,0) credits_minor,coalesce(i.net_invoice_minor,0) net_invoice_minor,coalesce(a.erp_posted_minor,0) erp_posted_minor,coalesce(a.allocated_cash_minor,0) allocated_cash_minor,coalesce(e.elimination_minor,0) elimination_minor,coalesce(i.net_invoice_minor,0)-coalesce(e.elimination_minor,0) consolidated_invoice_minor,coalesce(a.erp_posted_minor,0)-coalesce(e.elimination_minor,0) consolidated_erp_minor FROM {ns}.controls c CROSS JOIN (SELECT explode(array('2026-01-01','2026-10-01')) period) p LEFT JOIN amounts a ON c.company=a.company AND p.period=a.period LEFT JOIN inv i ON c.company=i.company AND p.period=i.period LEFT JOIN elim e ON c.company=e.company AND p.period=e.period"""
            ).collect()
            metrics = list(fixture["expected"][label]["totals"][0].keys())
            totals = rows(
                "SELECT period,currency,"
                + ",".join(f"sum({m}) {m}" for m in metrics if m not in ["period", "currency"])
                + " FROM {ns}.gold GROUP BY period,currency ORDER BY period"
            )
            variances = sql(
                """SELECT company,invoice_id id,CASE WHEN erp_count=0 THEN 'erp_posting_missing' ELSE 'erp_posting_difference' END code,net_minor-erp_minor amount FROM {ns}.invoices WHERE net_minor<>erp_minor OR erp_count=0 UNION ALL SELECT company,invoice_id,'intercompany_unresolved',net_minor FROM {ns}.eliminations WHERE elimination_minor=0 UNION ALL SELECT p.company,p.source_id,'unallocated_payment',p.amount_minor-coalesce(sum(a.amount_minor),0) FROM {ns}.eligible p LEFT JOIN {ns}.eligible a ON p.company=a.company AND a.kind='allocation' AND a.payment_id=p.source_id WHERE p.kind='payment' GROUP BY p.company,p.source_id,p.amount_minor HAVING p.amount_minor<>coalesce(sum(a.amount_minor),0)"""
            ).collect()
            result = dict(
                legal=rows("SELECT * FROM {ns}.gold ORDER BY company,period"),
                totals=totals,
                variances=sorted([list(v) for v in variances]),
            )
            require(
                "invoice_lines_balance",
                rows("SELECT count(*) n FROM {ns}.invoices WHERE gross_minor<>lines_minor")[0]["n"],
                0,
            )
            require(
                "no_payment_overallocation",
                rows(
                    "SELECT count(*) n FROM (SELECT p.company,p.source_id,p.amount_minor FROM {ns}.eligible p JOIN {ns}.eligible a ON p.company=a.company AND a.kind='allocation' AND a.payment_id=p.source_id WHERE p.kind='payment' GROUP BY p.company,p.source_id,p.amount_minor HAVING sum(a.amount_minor)>p.amount_minor)"
                )[0]["n"],
                0,
            )
            require(label + "_full_financial_oracle", result, fixture["expected"][label])
            result_json = canonical(result)
            source_hash = sha(
                rows("SELECT * FROM {ns}.bronze ORDER BY company,kind,source_id,revision")
            )
            spark.createDataFrame(
                [(label, result_json, source_hash)],
                "publication_id string,result_json string,source_hash string",
            ).createOrReplaceTempView("candidate")
            sql(
                "MERGE INTO {ns}.candidates t USING candidate s ON t.publication_id=s.publication_id WHEN NOT MATCHED THEN INSERT *"
            ).collect()
            # Independently compare committed candidate bytes before exposing its immutable marker.
            actual = rows(
                f"SELECT result_json FROM {{ns}}.candidates WHERE publication_id='{label}'"
            )
            require(label + "_candidate_readback", actual, [dict(result_json=result_json)])
            return result

        def publish(label):
            sql(
                f"MERGE INTO {{ns}}.publications t USING (SELECT * FROM {{ns}}.candidates WHERE publication_id='{label}') s ON t.publication_id=s.publication_id WHEN NOT MATCHED THEN INSERT *"
            ).collect()

        if phase == "pilot":
            require("baseline_authority_rejections", ingest(fixture["baseline"]), 0)
            original_version = version("bronze")
            initial_count = rows("SELECT count(*) n FROM {ns}.bronze")[0]["n"]
            ingest(list(reversed(fixture["baseline"])) + fixture["baseline"][:3])
            require(
                "duplicate_reordered_rows",
                rows("SELECT count(*) n FROM {ns}.bronze")[0]["n"],
                initial_count,
            )
            project("original")
            publish("original")
            ingest(fixture["corrections"])
            project("restated")
            # Controlled failure boundary: candidate committed; deliberately withhold publication.
            require(
                "failed_publication_not_visible",
                rows("SELECT publication_id FROM {ns}.publications ORDER BY publication_id"),
                [dict(publication_id="original")],
            )
            observe(
                "injected_fault",
                "after_candidate_commit_before_publication; task exits normally to preserve checkpoint",
            )
            require(
                "time_travel_baseline",
                rows(f"SELECT count(*) n FROM {{ns}}.bronze VERSION AS OF {original_version}")[0][
                    "n"
                ],
                initial_count,
            )
            observe(
                "cdf",
                rows(
                    f"SELECT _change_type,count(*) n FROM table_changes('{ns}.bronze',0) GROUP BY _change_type"
                ),
            )
            observe("versions", {t: version(t) for t in ["bronze", "candidates", "publications"]})
        elif phase == "recovery":
            require(
                "remote_ahead_candidate",
                rows("SELECT publication_id FROM {ns}.publications ORDER BY publication_id"),
                [dict(publication_id="original")],
            )
            if spark.catalog.tableExists(ns + ".fault_journal"):
                require(
                    "failed_task_durable_commit",
                    rows("SELECT * FROM {ns}.fault_journal"),
                    [dict(boundary="committed_before_task_failure")],
                )
            company, entity = [fixture["controls"][0][k] for k in ["company", "legal_entity"]]
            sql(f"UPDATE {{ns}}.controls SET admitted=false WHERE company='{company}'").collect()
            try:
                project("restated")
            except AssertionError as e:
                require("changed_admission_blocks_recovery", str(e), "frozen_control_unchanged")
            else:
                raise AssertionError("changed_admission_recovery_allowed")
            finally:
                sql(f"UPDATE {{ns}}.controls SET admitted=true WHERE company='{company}'").collect()
            require(
                "changed_admission_did_not_publish",
                rows("SELECT publication_id FROM {ns}.publications ORDER BY publication_id"),
                [dict(publication_id="original")],
            )
            ingest(fixture["corrections"])
            project("restated")
            publish("restated")
            publish("restated")
            require(
                "recovery_single_marker",
                rows("SELECT count(*) n FROM {ns}.publications WHERE publication_id='restated'")[0][
                    "n"
                ],
                1,
            )
            original = rows(
                "SELECT result_json FROM {ns}.publications WHERE publication_id='original'"
            )[0]["result_json"]
            require(
                "historical_publication_unchanged",
                json.loads(original),
                fixture["expected"]["original"],
            )
            # A conflicting replay must not overwrite a previously published result.
            conflict = dict(
                fixture["baseline"][0], amount_minor=fixture["baseline"][0]["amount_minor"] + 1
            )
            try:
                ingest([conflict])
            except ValueError as e:
                require("conflicting_replay_denied", str(e), "same_revision_content_conflict")
            else:
                raise AssertionError("conflicting_replay_accepted")
            invalid = [
                dict(fixture["baseline"][0], legal_entity="WRONG"),
                dict(fixture["baseline"][0], source="untrusted"),
            ]
            require("entity_authority_rejected", ingest(invalid), 2)
            count_before = rows("SELECT count(*) n FROM {ns}.bronze")[0]["n"]
            try:
                sql(
                    "INSERT INTO {ns}.bronze SELECT * REPLACE(cast(NULL as bigint) AS amount_minor) FROM {ns}.bronze LIMIT 1"
                ).collect()
            except Exception as e:
                code = e.getErrorClass() if hasattr(e, "getErrorClass") else type(e).__name__
                assert "CONSTRAINT" in str(e), "unrelated_error_not_transaction_proof"
                observe("delta_constraint_rejected", code)
            else:
                raise AssertionError("null_constraint_accepted")
            require(
                "failed_transaction_no_partial_write",
                rows("SELECT count(*) n FROM {ns}.bronze")[0]["n"],
                count_before,
            )
            cdf = (
                spark.readStream.format("delta")
                .option("readChangeFeed", "true")
                .option("startingVersion", 0)
                .table(ns + ".bronze")
            )
            checkpoint = f"/Volumes/workspace/{schema}/checkpoints/cdf"

            def stream_once():
                query = (
                    cdf.writeStream.format("delta")
                    .option("checkpointLocation", checkpoint)
                    .trigger(availableNow=True)
                    .toTable(ns + ".cdf_audit")
                )
                assert query.awaitTermination(180), "stream_timeout"
                progress = query.lastProgress or {}
                return {
                    k: progress.get(k)
                    for k in [
                        "batchId",
                        "numInputRows",
                        "durationMs",
                        "inputRowsPerSecond",
                        "processedRowsPerSecond",
                    ]
                }

            observe("stream_first", stream_once())
            before = rows("SELECT count(*) n FROM {ns}.cdf_audit")[0]["n"]
            observe("stream_restart", stream_once())
            require(
                "checkpoint_replay_unchanged",
                rows("SELECT count(*) n FROM {ns}.cdf_audit")[0]["n"],
                before,
            )
            observe(
                "native_lineage_tables",
                [ns + ".bronze", ns + ".silver", ns + ".eligible", ns + ".gold"],
            )
            metrics = [
                k
                for k in fixture["expected"]["restated"]["legal"][0]
                if k not in ["company", "legal_entity", "period", "currency"]
            ]
            fields = "company:string,legal_entity:string,period:string,currency:string," + ",".join(
                k + ":bigint" for k in metrics
            )
            result_type = "struct<legal:array<struct<" + fields + ">>>"
            sql(
                f"CREATE VIEW {{ns}}.company_view AS SELECT p.publication_id,f.* FROM {{ns}}.publications p LATERAL VIEW explode(from_json(p.result_json,'{result_type}').legal) x AS f WHERE f.company='{company}' AND f.legal_entity='{entity}'"
            ).collect()
            require(
                "view_only_published_versions",
                rows(
                    "SELECT DISTINCT publication_id FROM {ns}.company_view ORDER BY publication_id"
                ),
                [dict(publication_id="original"), dict(publication_id="restated")],
            )
        else:
            raise ValueError("unknown_phase")

    out["completed_at_utc"] = datetime.now(UTC).isoformat()
    out["status"] = "passed"
    return out


# The uploader supplies FIXTURE in the first cell; never embed credentials.
if __name__ == "__main__":
    dbutils.notebook.exit(canonical(run(spark, dbutils, FIXTURE)))  # noqa: F821
