# Pass 3 final acceptance: canonical source ordering

Executed implementation: [`5571760795f1a32d7dadcc322529bf6afb899f94`](https://github.com/rlbsem/enterprise-acquisition-onboarding/tree/5571760795f1a32d7dadcc322529bf6afb899f94). Recorded `2026-10-26T02:27:27.951268+00:00` on Windows, Python 3.12.14. [Verification](verification.json) pins source/fixture/dbt hashes and every executed case.

**50 tests passed, zero failures/errors/skips**, including the original 39 tests, ten financial cases and an order-invariance regression. All three standalone demonstrations completed: [admission](demo.json), [governed receiver execution](pass2.json) and [financial reporting](pass3.json).

Each financial version passed nine real PostgreSQL dbt models and nine data tests. Seven financial result sets per version matched the source-based Python oracle exactly: 14 comparisons, 75 compared rows, zero differences and matching expected/observed hashes. The oracle independently calculates from original frozen source bodies, not dbt output.

| Synthetic USD across selected January, February and October periods | Original | Restated |
|---|---:|---:|
| Commercial bookings | 550,000 | 550,000 |
| Net invoicing before elimination | 388,000 | 408,000 |
| ERP postings before elimination | 383,000 | 403,000 |
| Allocated cash | 230,000 | 230,000 |
| Supported intercompany elimination | 20,000 | 20,000 |
| Consolidated net invoicing | 368,000 | 388,000 |
| Consolidated ERP postings | 363,000 | 383,000 |

Cedar's USD 5,000 posting difference and unsupported USD 8,000 intercompany candidate remain open in both versions. Status remains `reconciled_with_open_variances`, not an assertion that the source accounts balance.

Acceptance A-G is preserved: eligible entity/parent consolidation; held Summit's USD 100,000 October invoice excluded; source-linked posting discrepancy; exact bilateral USD 20,000 elimination with unsupported candidate retained gross; Meridian's USD 90,000 pre-acquisition January invoice excluded and USD 200,000 February invoice included; higher source revisions restate January by USD 20,000; independent exact financial comparisons.

The original report/cutoff remain reproducible and unchanged. Cash, bookings and eliminations do not change. Five January bridge measures rise by USD 20,000. Receiver effects and POST counts each remain one before and after reporting: no downstream write is triggered by restatement.

An intentionally unbalanced one-cent candidate fails the real `financial_amount_controls` dbt test and remains unpublished. Its failed/skipped nodes are preserved separately in `blocked_candidate`; only the original and restated versions are published. The valid builds' results are not combined with that rejected build into a misleading all-pass claim.

The Linux CI failure identified locale-sensitive source-ID ordering in exact inventory comparison. Selection now canonicalizes ordering before freezing and fingerprinting; no financial amounts, IDs, inclusion or elimination rules changed. The added order-invariance test protects that boundary. The [previous Windows record](../README.md) and all prior evidence bytes are preserved.

[Financial execution](pass3.json) includes source events/rejections, frozen policy/control/input/publication records, model outputs, independent comparison hashes, exclusion reasons, audit records, restatement bridge and sanitized dbt statuses. [Manifest](manifest.json) protects every artifact. The offline checker recomputes the financial results from those source inputs. Private profiles, credentials, compiled SQL and raw logs are excluded.

These are local PostgreSQL/HTTP/dbt executions on synthetic data. Cutoffs represent synthetic source-observation knowledge, separate from actual capture time. No native vendor, recognized revenue, commercial result, statutory consolidation, production deployment or independent final audit is claimed. All owned resources were stopped. [Policy/reproduction](../../../financial-reporting.md) explains boundaries; Pass 4 has not started. Hosted CI is independently visible in [draft PR #1](https://github.com/rlbsem/enterprise-acquisition-onboarding/pull/1).
