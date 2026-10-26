# Pass 3 executed financial acceptance

Executed implementation: [`a0bf88d4b1d8ba81fdfd125e23553311b6ab24a2`](https://github.com/rlbsem/enterprise-acquisition-onboarding/tree/a0bf88d4b1d8ba81fdfd125e23553311b6ab24a2). Recorded `2026-10-26T02:16:49.831758+00:00` on Windows / Python 3.12.14. Business-effective dates and source-observation cutoffs are synthetic dates; actual capture time is preserved separately.

**49 Python/PostgreSQL/HTTP tests passed; zero failures, errors or skips.** All original 39 cases remain included. [Verification](run01/verification.json) lists cases and exact source/fixture/SQL/dbt project hashes. Three standalone demonstrations completed: [Pass 1](run01/demo.json), [Pass 2](run01/pass2.json), and [Pass 3 financial reporting](run01/pass3.json).

The original and restated versions each ran **nine dbt PostgreSQL models and nine data tests**, all passing. For each version, seven financial result sets agree with the independent source-body Python oracle: exact row content, expected/observed row counts, matching hashes and zero differences. Results cover invoice-level line/credit/posting reconciliation, payment allocations, legal entities, parent totals, eliminations, variances and the temporal bridge. The oracle does not read dbt outputs.

| USD measure across selected January, February and October periods | Original | Restated |
|---|---:|---:|
| Commercial bookings | 550,000 | 550,000 |
| Net invoice source totals before elimination | 388,000 | 408,000 |
| ERP posting source totals before elimination | 383,000 | 403,000 |
| Allocated cash | 230,000 | 230,000 |
| Supported intercompany elimination | 20,000 | 20,000 |
| Consolidated net invoicing | 368,000 | 388,000 |
| Consolidated ERP postings | 363,000 | 383,000 |

Both publications retain **`reconciled_with_open_variances`**: Cedar invoice `I2` has a USD 5,000 ERP posting difference; invoice `IC2` has an unsupported USD 8,000 intercompany candidate. These are separate exception categories, not an asserted combined accounting loss. They are not removed to force agreement.

| Acceptance | Executed observation |
|---|---|
| A: Correct consolidation | Source-owned header/line/posting/allocation grains reconcile to eligible legal-entity and parent totals using integer cents |
| B: Held acquisition | Summit's USD 100,000 October invoice is excluded under the captured failed admission state |
| C: Financial discrepancy | Cedar's USD 5,000 posting difference remains source-linked and open |
| D: Elimination | USD 20,000 is eliminated with one exact seller charge, independent buyer acceptance and bilateral legal entities; unsupported USD 8,000 remains gross |
| E: Acquisition-effective reporting | Meridian's USD 90,000 January invoice is excluded before its February 1 acquisition; its USD 200,000 February invoice is included |
| F: Restatement | Three higher source revisions observed October 22 change five January measures by USD 20,000; original cutoff replay, original publication and all prior source versions remain intact |
| G: Independent verification | Seven result sets match exactly in each version; deliberate one-cent oracle disagreement is rejected in regression testing |

Financial source rejection tests cover wrong legal entity, mismatched currency, lower source authority, stale mapping/revision, duplicate-content conflict, noninteger money and unapproved source inventory. Ambiguous bilateral acceptance cannot authorize an elimination. SQL role tests deny raw-ingestion/control access to the dbt role. Snapshot inputs reject later inserts as well as updates/deletes; publication rechecks the frozen input manifest and current control state.

The final one-cent line imbalance is **rejected evidence**: actual dbt test `test.acquisition_finance.financial_amount_controls` failed with `1` violation. Its failed/skipped node results are retained under `blocked_candidate`; no publication exists for that candidate. This failure is not counted as a passing dbt build. There are exactly two published financial versions.

Receiver effects and POST counts both remain **one before and one after** reporting. The pre-existing synthetic handoff is not the origin of invoice or payment facts, and restatement emits no downstream business-system action.

[Financial execution](run01/pass3.json) contains original source events and rejected updates, frozen policies/controls/inputs, versioned publications, exact model/variance/bridge results, admission exclusions, audit entries and sanitized dbt node outcomes. [Artifact hashes](run01/manifest.json) protect the bytes. The checker independently recomputes financial results from those source inputs. Original [Pass 1](../pass1/README.md) and [Pass 2](../pass2/README.md) archives are unchanged.

All data and source adapters are local and synthetic. No native financial vendor, cloud resource, commercial result, recognized revenue, statutory consolidation or independent final audit is claimed. Reporting periods are selected months, not a continuous year-to-date series. Generated credentials/profiles, compiled dbt SQL and raw runtime logs remain private. All owned databases/processes were stopped. [Policy and reproduction](../../financial-reporting.md) describe the precise boundaries. Pass 4 has not started.
