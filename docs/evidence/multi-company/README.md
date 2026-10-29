# Multi-company scale and failure-isolation acceptance

Eight source-bound Windows executions passed: two each at **3, 10, 25 and 50 synthetic companies**. All used actual PostgreSQL 17.11, authenticated loopback HTTP source/intake/receiver services and two real nine-model dbt builds. The original three-company correctness and annual scenarios remain unchanged. No native vendor or cloud execution is claimed.

## Measured workload

[Recorded summary](windows-run01/summary.json) · [50-company source/receipt/financial witness](windows-run01/companies-050-run-01.json) · [Exact artifact hashes](windows-run01/artifact-integrity.json).

| Companies | Repeat | Accounts | Initial admission median (s) | Intake/admission stage (s) | Original publication (s) | Full protocol (s) | Three databases (MiB) |
|---|---|---|---|---|---|---|---|
| 3 | 1 | 9 | 0.0830 | 4.37 | 3.47 | 15.30 | 26.16 |
| 3 | 2 | 9 | 0.0499 | 4.51 | 3.60 | 15.59 | 26.17 |
| 10 | 1 | 29 | 0.0566 | 8.62 | 3.85 | 22.01 | 28.31 |
| 10 | 2 | 29 | 0.0607 | 8.93 | 3.65 | 22.53 | 28.34 |
| 25 | 1 | 74 | 0.0520 | 18.55 | 4.01 | 37.18 | 32.90 |
| 25 | 2 | 74 | 0.0548 | 19.38 | 3.73 | 37.30 | 32.99 |
| 50 | 1 | 149 | 0.0568 | 35.20 | 4.26 | 61.56 | 40.12 |
| 50 | 2 | 149 | 0.0545 | 35.89 | 4.26 | 62.64 | 40.10 |

These are initial request latencies and complete finite-protocol timings, not pure endpoint throughput or cold application startup. The protocol duration excludes fixture installation, browser capture and teardown, whose outcomes are recorded separately. Publication includes snapshot freeze, dbt and independent comparison. Storage includes PostgreSQL catalog overhead. At 50 companies, 47 initial admission requests were sampled; three pending-review companies made no such request and are excluded. Worker-queue delay and individual request intervals remain in each record. No throughput improvement is inferred from these differently sized workloads.

The shared Windows 11 host reported 32 logical CPUs and 33,457,201,152 bytes of physical memory. Each owned PostgreSQL server used 30 maximum connections and 32 MB shared buffers. The driver used four concurrent workers and serialized warehouse builds. Database statistics, three separate database sizes, orchestrator CPU and unavailable container-only observations are recorded explicitly. Orchestrator CPU is not total system CPU; I/O timing was disabled. This is not a controlled production capacity benchmark.

## Independently checked results at 50 companies

- All 50 companies reuse local customer ID `100`; 149 canonical accounts remained distinct. The source projections retained 439 accepted company-scoped records, with unresolved/missing observations kept outside admission.
- **37 healthy companies completed while the dedicated company's operations feed remained stopped.** A separate real PostgreSQL lock probe established a blocked backend, then observed another company's admission complete before releasing the blocked company's lock.
- Before source recovery, 37 internal handoff intents were exercised. The independently persisted receiver contained **36 confirmed effects**, one exhausted intent with three attempts, and no duplicate applied business effects. Lost acknowledgment was recovered by receipt and record readback. The receiver still has a shared process/database failure domain.
- A deliberately omitted allocation blocked financial freeze without creating a partial snapshot. Delivery of the exact missing source fact restored inventory before publication.
- Original and restated source membership, invoice grains, allocation parentage, company-period contributions and bilateral elimination evidence matched the independent observer. The latest source set contains **2,727 financial identities**, with three later correction revisions retained separately.
- After source recovery: **38 admitted, nine held and three pending**. The restated report contained 123 included invoices and 116 allocations across 100 company-period rows. Held and pre-acquisition facts remain source-visible and financially excluded.
- Original publication and frozen input membership survived the later admission and financial correction unchanged. Actual listener, process and PostgreSQL-stop checks passed after all eight runs.

The restated selected-period financial results are **USD $17,281,590 bookings, $6,047,899.69 consolidated net invoicing, $6,046,149.69 consolidated ERP postings and $3,854,519.89 allocated cash**. Only **$5,340** had supported bilateral elimination evidence. The **$1,750 posting difference remains unresolved**, alongside unsupported intercompany and unallocated-payment observations; no commercial result or recognized revenue is inferred.

Original consolidated invoicing was $5,925,832.89. The $122,066.80 restatement comprises $120,696.80 from the recovered company's newly admitted reporting perimeter and $1,370 from an independent source correction. It is not an operational revenue uplift.

## Browser and regression evidence

The 50-company run recorded **18 browser checks, six accessibility views with no violations or unresolved checks, zero script errors and six genuine viewport screenshots**. These are actual current application pages, with no image editing:

- [Desktop portfolio with held-company filter](windows-run01/browser/desktop-portfolio.png) · [mobile portfolio](windows-run01/browser/mobile-portfolio.png).
- [Current admission versus original reporting inclusion](windows-run01/browser/desktop-company.png) · [mobile company](windows-run01/browser/mobile-company.png).
- [Financial reconciliation](windows-run01/browser/desktop-finance.png) · [mobile reconciliation](windows-run01/browser/mobile-finance.png).
- [Capture times, viewports, selected publications, interaction results and screenshot hashes](windows-run01/browser/browser.json).

The [complete Windows regression](regression-run01/verification.json) passed **97 tests**, followed by the original four standalone demos. Its existing browser lane passed **53 checks and seven accessibility views**. That record pins `fc2704b9aa371ad9106cf506a9f337cb7cac3d01`; the corrected measured workload and six new screenshots pin `f401e62c4eff249e99bacfd4d05fd830b48482a8`. Source financial rules and dbt models did not change between them. A final disposable-fixture reset correction and its real PostgreSQL regression follow those checkpoints; the exact PR head is rerun in GitHub, including the capped 50-company container lane. Inspect final-head CI before release.

## Corrections and limits

The first timing collector included pending-review branches that made no HTTP admission request. Its [original summary](instrumentation-before-fix/summary.json), [classification](instrumentation-before-fix/classification.json) and hashes are preserved; the request-only collector was corrected and all eight measured runs repeated. This was an instrumentation defect, not a demonstrated financial or authorization failure. The new pending state is also shown consistently in company detail and governance rather than being relabeled held.

[All 140 historical evidence files](preserved-files.json) remain byte-for-byte unchanged. The new SQL/HTTP negatives and independent-oracle mutation tests add to the existing suite rather than changing old test semantics. Development diagnostics remain private, including a correctly denied raw-financial read by the console identity and an acceptance-export UUID serialization correction; neither was an application permission expansion or a native-vendor finding.

The experiment establishes finite observed progress and exact financial comparisons for this workload. It does not establish per-company PostgreSQL RLS, independent physical infrastructure, concurrent dbt-build safety, native vendor connectors, an unrestricted fairness guarantee, statutory consolidation or production reliability. The shared warehouse schema requires serialized builds. A globally unreviewed financial inventory gap still blocks publication even when healthy company onboarding can proceed.

[Architecture and reproduction](../../multi-company-acceptance.md) · [Observed baseline](../../multi-company-baseline.md).
