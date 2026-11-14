# Native lakehouse acceptance ledger

The owner authorized an overall USD300 resource-consumption envelope, starting
with a native pilot targeting no more than USD20. No account upgrade, external
AWS infrastructure or recurring workload is permitted.

The first pilot uses the existing three-company `Portfolio` fixture and its
independent `portfolio_oracle.calculate` implementation. Admission is a frozen
synthetic control export, not a live connection to PostgreSQL or a replacement
for its current authorization. Existing financial definitions and fixtures are
unchanged. All monetary values are integer USD minor units.

```mermaid
flowchart LR
  S[Frozen synthetic source versions] --> B[Bronze Delta history]
  C[Frozen PostgreSQL control expectations] --> V[Company / entity / source authority checks]
  B --> V --> I[Incremental Silver MERGE]
  I --> G[Recomputed Gold financial projections]
  O[Existing independent Python oracle] --> R[Exact content and source reconciliation]
  G --> R --> K[Immutable candidate]
  K --> P[Publication marker after verification]
  P --> U[Scoped consumer view of published versions]
  B --> F[Bounded CDF stream and durable checkpoint]
```

Gold is recomputed from validated Silver. Incremental claims apply to source
history, Silver MERGE and the bounded CDF consumer; this is not a fully incremental
Gold financial engine. Company isolation uses a scoped view with base-table
access denied to the dedicated consumer, not a claim of base-table row filters
or production SSO. The public app requires no Databricks credentials.

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
cleanup before the approved execution window ends.

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

## Executed checkpoint

Actual native results are preserved in the [evidence directory](evidence/lakehouse-native/2026-11-14/README.md).

| Execution | Actual result |
|---|---|
| Initial pilot `376042101469046` | Failed on the default Python 3.10 runtime's unsupported `datetime.UTC` import, before table creation code. Original failure retained. |
| Corrected pilot `165257131529869` | Passed on Spark 4.2.0/Python 3.10.12; 162 original source rows plus three corrections; all nine financial metrics at company/period and portfolio grains matched the existing independent oracle. |
| Incremental and historical state | Silver MERGE matched independent full-snapshot results; duplicate/reordered delivery did not change source membership; earlier Delta table-version readback matched the baseline. |
| Publication boundary | Original publication remained visible while the corrected candidate was committed but deliberately unpublished. This first pilot withheld a marker; it did not crash a process. |
| First observer `365544213277342` | Timed out with a five-minute total allowance after 236 seconds of setup. No successful readback is attributed to this record. |
| Corrected observer `1066881425859697` | Passed; original publication independently read back and reconciled, actual history observed and 66 native lineage records returned. These are records, not 66 distinct dependencies. |

The corrected pilot took 135 seconds to set up and 238 seconds to execute.
The successful observer took 266 seconds to set up and 194 seconds to execute.
These are acceptance-task durations including checks, not ingestion throughput
benchmarks. Immutable records retain exact source commits; later fixes do not
retroactively change what an older run proved.

Usage reads returned no rows. This is pending reporting, not zero consumption.
The first native rate query also returned no rows because its SKU pattern
assumed the words SERVERLESS and JOBS were in the wrong order; the corrected
query is part of subsequent execution. The applicable public regional price was
observed independently; actual workload billing remains unverified.

Databricks documents [up to a 24-hour reporting delay](https://docs.databricks.com/aws/en/compute/serverless),
and [new-workspace delivery can take longer](https://docs.databricks.com/aws/en/admin/system-tables/billing).
Completed-run wall time is reserved at 75 DBU/hour times USD0.35 (a conservative
50 DBU/hour scenario assumption plus a 50% margin). Those padded pending
estimates are not billed amounts. Future task timeouts remain reserved and a
separate cleanup/storage reserve is retained. Scale expansion stays blocked
until actual usage, applicable rates and successful pilot acceptance are observed.

A bounded native Jobs dependency chain is testing a real task failure after a
durable Delta journal commit, followed by guarded recovery and CDF checkpoint
replay. Restricted-principal access tests, that recovery verdict and the full
50-company/scale lane are not claimed as passed in this checkpoint.
