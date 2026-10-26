# Source-linked portfolio financial reporting

## Measures and grain

This finite local scenario reports USD integer cents for **January, February and October 2026**, not a continuous year-to-date series. All companies and records are synthetic. Canadian and US legal-entity identifiers do not imply FX conversion: every admitted financial contract is explicitly denominated in USD. Other currencies are rejected. No recognized revenue, statutory consolidation, tax accounting or production financial-control certification is implemented.

| Contract | Grain and owner | Measure |
|---|---|---|
| Booking | Company, CRM source ID and revision; CRM owns it | Commercial commitment by transaction month; not an invoice |
| Invoice / invoice line | Company, finance document or line ID and revision | Gross header reconciled to lines; credits reduce net invoicing |
| ERP posting | Company, finance posting ID and revision, linked invoice | Signed posted amount; separate credit posting supplies the negative entry |
| Credit | Company, finance adjustment ID and revision, linked invoice | Positive adjustment reduces invoice balance; does not invent an ERP credit |
| Payment / allocation | Company, payment or allocation ID and revision | Payment receipt and independently referenced allocation; only allocated cash enters the reported collection measure |
| Intercompany charge / acceptance | Seller invoice plus exact bilateral legal entities and linkage reference | Documentary support for a bounded elimination, not expense recognition |
| Report | Immutable report ID, policy version, source-observation cutoff and captured control state | Company/legal entity/selected month/currency and parent month/currency |

The source contract is `financial-fact.v1`. It preserves source ID, authenticated source/owner, legal entity, scoped customer reference, mapping version, revision, business-effective transaction date and source-observation timestamp. Source-ID snapshots advance consecutively; reporting selects one accepted revision at its cutoff rather than summing revisions. Wrong entities/currencies, lower authority, stale revisions, changed identity relationships and invalid references are rejected. Identical events replay; changed content under the same event ID conflicts.

## Admission and reporting policy

`portfolio-financial-policy.v1` is an immutable, explicitly reviewed local fixture policy. Its separate governance database identity records actor, reason, USD basis, perimeter, registry-derived acquisition dates, reporting units, expected source IDs and elimination rule. This synthetic approval is not claimed as independent human or native vendor acceptance.

A report freezes current reconciled admission state and mapping versions from the existing control layer, together with exact financial source-ID coverage. Unknown or unreviewed coverage blocks the candidate. Cedar and Meridian are admitted; Summit remains held. Meridian's January invoice is outside its February 1 acquisition boundary. Summit's October invoice is held despite its October 1 acquisition date. Related documents outside the eligible parent perimeter remain excluded explicitly. No pre-acquisition receivable carry-forward is modeled.

The cutoff is a **synthetic source-observation as-of date**, distinct from actual database capture/publication time. The finite imported data does not prove that a live connector knew these facts at a historical wall-clock instant. Frozen event IDs and original body hashes preserve exactly what the reporting version used. PostgreSQL permits input insertion only in the snapshot-creation transaction; later appends, edits and deletes fail. Publication verifies the frozen manifest again. A later mapping/source change cannot rewrite an old report. Publication rechecks control state and cutoff-selected source records after dbt execution.

## Consolidation and reconciliation

Nine PostgreSQL dbt models cover dimension, staging, invoice/allocation facts, intercompany evidence, variances, legal-entity/parent totals and restatement bridge. Invoice children are aggregated before joining; allocations retain their own grain. dbt tests check uniqueness, non-null periods, references, scope, invoice/line agreement, allocation limits and arithmetic identities.

Gross invoicing, credits and net invoicing are retained before elimination. Posting and allocation totals follow their own transaction months; invoice-level reconciliation links their exact source IDs. Parent totals sum eligible legal-entity measures under the single currency policy. These measures cannot be substituted for one another.

Elimination requires one eligible seller charge and one independently sourced buyer acceptance with the exact invoice, link ID, currency, amount and bilateral legal entities, plus matching ERP content. Multiple acceptances are ambiguous. Unsupported candidates remain gross and produce an open variance. The finite matched intercompany item has no cash allocation; intercompany cash/netting and expense-side consolidation are outside this policy. Customer-name similarity or equal amounts never establishes a link.

The Python oracle starts from frozen original source bodies and performs its own integer selection, grouping and arithmetic. It does not query dbt outputs. Seven financial result sets are compared by exact row content and hashes, including invoice, cash, entity, parent, elimination, variance and temporal grains. Zero oracle differences means the two implementations agree; it does **not** mean open source discrepancies have disappeared. Successful reports retain status `reconciled_with_open_variances` where appropriate.

Invoice-line imbalance or excess allocation fails real dbt data tests and blocks publication. A missing/different ERP posting remains an explicit source-linked variance, never a forced balance. Immutable publication rows contain the complete result, comparison and bridge. Rebuildable dbt tables are working projections; they do not replace archived reporting versions. A failed build may leave an unpublished candidate in that working schema. Consumers must use the validated immutable publication, not infer publication from an analytics table existing.

## Executed financial bridge

| USD measure | Original | Restated |
|---|---:|---:|
| Commercial bookings | 550,000 | 550,000 |
| Net invoicing before eliminations | 388,000 | 408,000 |
| ERP postings before eliminations | 383,000 | 403,000 |
| Allocated cash | 230,000 | 230,000 |
| Supported intercompany elimination | 20,000 | 20,000 |
| Consolidated net invoicing | 368,000 | 388,000 |
| Consolidated ERP postings | 363,000 | 383,000 |

The USD 5,000 Cedar posting difference and USD 8,000 unsupported intercompany candidate remain visible in both versions. These are different exception categories and are not summed into an asserted accounting loss.

Original cutoff: October 20. Three source revisions observed October 22 correct Cedar's January invoice, one line and its ERP posting by USD 20,000. Cutoff October 23 produces a new publication. Five January measures change by that amount; credits, cash, bookings and eliminations stay unchanged. Replaying the original cutoff still produces the original source-based result. Receiver effects **and POST counts** remain one before and after reporting: restatement causes no downstream business-system write.

A later one-cent line imbalance deliberately fails the dbt amount-control test and remains an unpublished candidate. Its failed/skipped nodes are preserved as rejected evidence, separate from the two validated builds. [Executed records](evidence/pass3/run02/README.md) pin actual source, fixtures, results and tests.

## Reproduce

Follow the repository's pinned Python 3.12/PostgreSQL 17 setup, then run from the checkout:

```text
python -m onboarding.financial_demo --workspace .local/finance-01 --output .local/finance-01.json
python scripts/verify.py --workspace .local/all-01 --output .local/evidence-01
python scripts/check_repository.py
```

The driver runs real `dbt build` with the [PostgreSQL adapter](https://docs.getdbt.com/docs/local/connect-data-platform/postgres-setup). Generated profiles, passwords, compiled SQL and raw logs stay under ignored `.local/`; sanitized node outcomes and results are exported. dbt uses a separate local SQL role: it can build in `analytics` and read frozen report inputs, but cannot read raw ingestion events or modify admission/control state. Telemetry is disabled. The trusted harness owns local setup/reset, while production RLS/SSO, native financial connectors and the independent final audit remain future work. The [Pass 4 console](operations-console.md) reads these validated publications and frozen source records.
