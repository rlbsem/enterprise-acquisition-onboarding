# Governed multi-company lakehouse acceptance

The additive Databricks lane will test whether source-owned company and financial
history can become a governed analytical publication without bypassing the
existing PostgreSQL admission, mapping and approval controls. PostgreSQL remains
the operational authority. No financial definition, fixture or existing dbt
model is changed by the feasibility work.

**Current boundary: real management API reads passed; native Spark/Delta/Jobs
acceptance has not executed.** The [recorded preflight](evidence/lakehouse-preflight/2026-11-14/README.md)
is deliberately separate from the existing PostgreSQL/dbt financial proof and
native HubSpot reads.

## Phase 1: supported access and spending gate

The official Databricks CLI 1.26.0 supports OAuth user-to-machine authentication.
Workspace and account profiles authenticated successfully using secure Windows
credential storage. Neither browser automation of the workspace nor the Genie
connector is used for management execution. No personal access token is required.

The read-only collector has seven fixed commands: current identity, pinned
account workspace, metastore assignment, catalogs, a bounded Jobs page, SQL
warehouse inventory and service-principal inventory. It has no provisioning,
SQL execution, warehouse start, secret retrieval or arbitrary-command interface.
It requires committed source, an exact CLI version and a fresh output file.
Public projections omit account IDs, workspace endpoints, emails and storage paths.

| Observation | Status |
|---|---|
| Supported CLI OAuth path | Executed, workspace and account scopes |
| Account workspace | AWS `us-west-2`, Premium, serverless, running |
| Unity Catalog | Attached metastore and managed workspace catalog observed |
| Jobs and service-principal listing | Authenticated GETs succeeded; both inventories empty |
| Existing starter warehouse | Serverless Small, stopped, zero clusters, ten-minute auto-stop |
| Trial balance | Owner reported USD400; not verified by these management endpoints |
| Expiry | Owner reported 14 days remaining; exact instant not supplied |
| Payment arrangement | Owner subsequently confirmed no linked payment method; no billing change made |
| Native restricted-principal denials | Not executed; listing identities proves no write/run-as permissions |

The first source-bound record predates that payment confirmation and retains its
original closed-gate reasons unchanged. The owner report resolves the linked
payment question; it does not create a trial-spending allowance or a native run.

The gate rejects missing/stale observations, mismatched target bindings, ambiguous
expiry, unconfirmed no-payment trial arrangements, inapplicable price plans,
non-finite/negative amounts and consumption beyond explicit approval or credit
headroom. It is an eligibility check, not an API mutation or general spending
authorization. The recorded gate remains **blocked**.

The public AWS Premium Oregon Jobs Serverless price was observed at **USD0.35/DBU**,
including underlying compute. A provisional four-hour, 50-DBU/hour model gives
USD70 for jobs, plus USD5 storage reserve, USD20 rerun reserve and USD25 delayed
usage reserve: **USD120 proposed total**. The DBU rate of consumption, storage
pricing remain unverified; payment-method absence is owner-reported. This is not a guaranteed
maximum, measured bill, owner-approved spending allowance or a claim of zero cost.
It does not authorize starting the existing SQL warehouse.

**Cost correction before managed tables:** predictive optimization is inherited
as enabled on the workspace catalog. It can run billable background maintenance.
A future isolated acceptance schema must explicitly disable it and verify that
setting before table creation. Existing account/catalog defaults stay unchanged.
No schema, principal, job, table or permission was created in this phase.

## Reproduce management reads privately

Install the official checksum-verified CLI, then use supported OAuth profiles:

```text
databricks auth login --host <workspace-url> --profile acquisition-trial
databricks auth login --host https://accounts.cloud.databricks.com --account-id <account-id> --skip-workspace --profile acquisition-account-read
```

Set `DATABRICKS_CONFIG_FILE` to a private location and
`DATABRICKS_AUTH_STORAGE=secure` before login. Do not print `auth token`,
`auth env`, secret values or raw authentication diagnostics. The CLI download
and local configuration stay outside Git. Install the repository's existing
pinned dependencies using the root quick start.

Supply a private JSON document with `config_file`, `workspace_profile`,
`account_profile` and a `target` object containing `host`, `account_id`,
`workspace_id` and `region`. Optional `owner_observation` and `cost_plan`
inputs are separately reviewed evidence; missing fields must block the pilot.
Do not put credentials in that document.

```text
python -m onboarding.lakehouse_preflight --read-only --cli <official-cli-path> --private-config <private-json-path> --output <fresh-private-output.json>
```

The collector returns success when the metadata reads pass, even if its explicit
`native_gate` is blocked. Exit zero must never be treated as Spark acceptance
or authorization to launch a job. Re-check exact expiry, payment arrangement,
applicable costs and a bounded owner-approved trial allowance before any native
compute. Credit/usage observations can lag; alerts are not a hard cap.

Credential-free checks:

```text
python -m pytest -q tests/test_lakehouse_preflight.py tests/test_lakehouse_preflight_evidence.py
python scripts/check_lakehouse_preflight.py
python scripts/check_repository.py
```

CI validates the recorded management observations offline. It never logs into
Databricks or supplies vendor credentials.

## Native acceptance scope after the gate

1. Export the existing synthetic source versions and frozen control/policy
   context with explicit authority, company, legal entity and source identity.
   This is not a live HubSpot/ERP CDC connector.
2. Process Bronze history, validated Silver facts/quarantine and Gold financial
   projections with native Spark and Delta. Preserve duplicates/conflicts and
   late revisions under the existing contract.
3. Execute bounded `AvailableNow` Jobs with durable checkpoints and measured
   change-feed processing. Retention gaps and incompatible checkpoints refuse
   continuation instead of silently skipping data.
4. Compare complete fixture result sets with the existing independent Python
   oracle. Preserve open financial variances, reporting exclusions and original
   publications; a late correction creates a new version.
5. Inject a failure after an actual target commit, then recover idempotently.
   Independently inspect effects and ensure an incomplete candidate cannot
   become published. No cross-table atomicity or arbitrary exactly-once claim.
6. Use real separately authenticated/run-as restricted principals for raw-read,
   write and company-scope denials. An owner-only test is not equivalent. If
   trial restrictions prevent this, retain a clearly reduced acceptance verdict.
7. Capture actual Jobs/task identifiers, Delta versions, lineage, profiles where
   available, independently read results and usage. Export sanitized evidence,
   remove only exact-run resources and verify residuals without altering the
   original control layer. SQL warehouse, live vendor and external cloud
   provisioning are not required by this design.

The smallest fixture must pass before a larger workload is considered. The
current read-only checkpoint demonstrates none of these native data outcomes.

## References

- [Official CLI installation](https://docs.databricks.com/aws/en/dev-tools/cli/install)
- [OAuth and secure token storage](https://docs.databricks.com/aws/en/dev-tools/cli/authentication)
- [Trial and billing arrangements](https://docs.databricks.com/aws/en/getting-started/free-trial)
- [Jobs price list](https://www.databricks.com/product/pricing/lakeflow-jobs)
- [Serverless Jobs and automatic retries](https://docs.databricks.com/aws/en/jobs/run-serverless-jobs)
- [Predictive optimization and billing](https://docs.databricks.com/aws/en/optimizations/predictive-optimization)
