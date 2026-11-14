# Native lakehouse acceptance ledger

The owner authorized up to USD300 of existing Databricks trial credits, starting
with a native pilot targeting no more than USD20. No payment method, account
upgrade, external AWS infrastructure or recurring workload is permitted.

The first pilot uses the existing three-company `Portfolio` fixture and its
independent `portfolio_oracle.calculate` implementation. Admission is a frozen
synthetic control export, not a live connection to PostgreSQL or a replacement
for its current authorization. Existing financial definitions and fixtures are
unchanged. All monetary values are integer USD minor units.

## Pilot contract

- One isolated `workspace.acq_lh_*` schema, comment-bound to the fixture hash.
- Disable predictive optimization before creating managed tables.
- Serverless Spark notebook task, 900-second timeout, zero automatic retries;
  separate bounded observer/cleanup tasks. No SQL warehouse start or schedule.
- Bronze Delta history, same-revision content conflict protection, replay and
  reordered-input checks, late corrections, cutoff-specific Silver/Gold SQL.
- Compare every company/period and all nine financial metrics, including open
  variances, against independently calculated expected results.
- Commit a candidate, withhold its publication marker, and preserve the earlier
  publication. A subsequent recovery must compare committed content before
  publishing once. Delta table transactions are not cross-table atomicity.
- Record CDF and actual table-version time travel.

Using the previously observed USD0.35/DBU price and an assumed 50 DBU/hour,
1,200 compute-seconds plus a USD2 storage/pending-usage reserve project USD7.84
rounded upward. This is a planning estimate, not a provider-enforced cap or
observed consumption. Cancel/pause if actual or delayed exposure threatens the
USD20 pilot or USD300 overall allowance. Retained storage may be billed after
namespace deletion; cleanup and billing clearance are separate observations.

## Expansion gates

Native pilot success is required before recovery, governance and scale tasks.
Next verify durable CDF checkpoint replay, independent publication readback,
separately executed restricted-principal access, lineage and actual usage.
Only then measure larger distributed synthetic datasets. Each execution uses
finite inputs, a timeout and no automatic retry. Failed observations are retained;
there is no unlimited full-run retry. Preserve budget headroom for export and
cleanup before the trial ends.

## Reproduction

The existing protected CLI OAuth profiles are used. No credentials are embedded
in notebooks, fixtures, evidence or source. Private configuration and runtime
logs remain under ignored `.local/`.

```text
python scripts/lakehouse_native.py prepare --config <private-config> --work .local/<fresh-run> --schema acq_lh_<unique-id>
python scripts/lakehouse_native.py upload --config <private-config> --work .local/<run>
python scripts/lakehouse_native.py submit --phase pilot --config <private-config> --work .local/<run>
python scripts/lakehouse_native.py observe --run-id <returned-id> --config <private-config> --work .local/<run>
```

Source must be committed before preparation. The manifest binds the source SHA,
fixture hash and uploaded notebook hash; one-time Jobs submissions use stable
idempotency tokens. Observe an existing run rather than resubmitting to poll it.
Before cleanup, export results and table history. Cleanup verifies the exact
fixture ownership comment before dropping only that schema. Remove the exact
run's notebook and dedicated principal/job, then verify absence separately.

Current status: implementation prepared and offline contracts executed. Native
execution results will be added as new immutable records after actual runs.
