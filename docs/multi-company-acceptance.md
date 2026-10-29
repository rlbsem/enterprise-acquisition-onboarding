# Measured multi-company acceptance

This separate `portfolio.v1` lane exercises the existing PostgreSQL intake, company locks, admission, durable handoff, authenticated console and nine-model dbt reporting path. The original three-company selected-period and annual fixtures are unchanged. All companies, local identifiers and financial records are synthetic USD facts.

## Workload and failure boundaries

Configure 3–100 companies; the recorded target sizes are 3, 10, 25 and 50. Each company has two to four customer accounts, one legal entity, an acquisition-effective date and one of three local contract styles. Local customer, event, opportunity, invoice and payment identifiers deliberately overlap across companies. Some companies use a second, explicitly reviewed finance-field mapping. Others have unresolved identity, incomplete operational coverage or completed intake awaiting an admission decision. Generated business facts and external identity keys are deterministic; timings and concurrently assigned PostgreSQL surrogate IDs are not. Cross-run comparisons use logical source keys and amounts, while within-run lineage retains the actual recorded surrogate IDs.

Two real HTTP source processes read a third PostgreSQL database, separately from the control and receipt databases. One process serves a dedicated company's operations feed and is actually terminated. The other serves the remaining feeds, including that company's independent CRM/finance contracts. Source tokens enforce company scope. These are two source processes and three logical databases, **not 50 physical fault domains**.

The finite measurement driver uses four concurrent company workers by default. Different company locks permit progress while one company's lock is deliberately held; the acceptance record establishes a blocked PostgreSQL backend before issuing the healthy admission request. Duplicate and conflicting deliveries retain original content. One internal handoff exhausts its three persisted attempts, another loses its acknowledgment after receiver commit, and other admitted companies progress. The driver records attempts, receipt/business-record contents and actual receiver request journals. These handoffs are internal synthetic onboarding effects, not billing transactions or native vendor writes.

No new production scheduler or storage partitioning is introduced. Finite observed progress is not a fairness SLA, an unbounded-backlog guarantee or a production throughput claim. The control API, PostgreSQL server, receiver process, source database and analytical build schema remain shared. Warehouse builds run sequentially because the existing `analytics` schema is shared.

## Financial correctness and publication

The independent observer reads persisted source facts using a source-only SQL identity, then compares accepted control membership, source IDs/revisions/hashes, invoice grains, allocation parents, bilateral elimination evidence, company/period contributions and aggregate amounts. It does not call the application's financial oracle or reconciliation functions. Separate tests deliberately corrupt plausible amounts, lineage, elimination results and held-company membership and require rejection.

January and October 2026 are selected reporting periods, not annual recognized revenue. Bookings, invoice headers/lines, credits, postings and payment allocations remain distinct. Acquisition-effective dates exclude pre-acquisition activity. A company may pass operational admission before its acquisition date while remaining excluded from an earlier financial period.

A deliberately withheld financial allocation first blocks the entire snapshot, leaving no partial snapshot or publication. Healthy admission and handoff progress do **not** establish that a globally incomplete financial report is safe to publish. Delivery of the exact missing source fact repairs coverage before original publication. Held/pending companies retain their source facts and are excluded by captured admission state.

After original publication, the terminated feed restarts, its company passes admission and a source-owned invoice/line/posting correction arrives through HTTP. A new restated publication captures those changes. The original publication and input membership remain unchanged; unresolved posting and intercompany differences remain visible. Historical reporting inclusion is distinct from current admission.

## Reproduction

Use the existing pinned Python 3.12 environment, PostgreSQL 17 binaries and Chromium installation documented in the main README. Run as an ordinary local user. No vendor credentials are needed.

```text
python scripts/verify_portfolio.py --workspace .local/portfolio-private --output .local/portfolio-evidence --sizes 3 10 25 50 --repeats 2 --browser
python scripts/check_portfolio_evidence.py .local/portfolio-evidence --require-scale
```

The verifier refuses uncommitted execution-source bytes. Use fresh paths. It keeps raw logs, database files, configuration and generated credentials under the private workspace, outside the public evidence. Outputs bind exact source revisions and canonical UTF-8/LF source hashes. The checker independently recalculates the recorded largest-run financial witness and verifies every preserved historical evidence file.

To inspect the same existing console interactively with 50 companies:

```text
python -m onboarding.portfolio_demo --workspace .local/portfolio-interactive --output .local/portfolio-interactive-evidence --sizes 50 --repeats 1 --serve
```

Open the printed loopback URL and use the private credentials file whose path is printed locally. Stop with Ctrl+C. This direct developer command labels its output unqualified unless provided a verified binding; use the verifier above for source-bound acceptance. The interface adds admission-state filtering, company/entity search and source-coverage counts. It retains company scope, source drilldowns, original/restated publications and the established design.

## Interpretation

Measurements include the stated finite failure/security protocol. Initial admission latency is the measured request interval for the initial company intake stage, excluding the separate contention and recovery probes; pending-review branches that make no admission request are counted separately and excluded from latency samples. Work-queue delay is the test driver's bounded worker wait. Publication duration includes freeze, real dbt and independent comparison. Storage is measured for each logical database. Orchestrator CPU excludes database and dbt child CPU. Native host memory and container limits/peak are reported separately where available. Company mixes and source-row counts vary at each size; these are repeatable workload measurements, not a controlled optimization comparison. Runs on a shared Windows host and a capped Linux CI container are not a controlled cross-platform performance comparison.

Company isolation is enforced by scoped HTTP identities, application checks and company-keyed constraints. Existing SQL identities have shared-table read grants: per-company PostgreSQL RLS, production SSO/TLS, physical fault isolation, native vendor connectors and statutory consolidation remain unverified. No cloud resource, public console, licensing change or commercial result is part of this experiment.

[Observed baseline](multi-company-baseline.md) · [Executed results and source-bound artifacts](evidence/multi-company/README.md).
