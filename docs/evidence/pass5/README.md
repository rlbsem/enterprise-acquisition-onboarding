# Pass 5 independent adversarial acceptance

**Decision: ready for the stated local synthetic scope.** One demonstrated, nonblocking acceptance-evidence defect was corrected. No material authorization, source-integrity, financial correctness or replay-safety failure remains demonstrated by this review. Recommend human review and merge within that scope; PR #1 is deliberately draft and unmerged. This is an independent AI-led assessment of prior builder work, not independent human penetration testing or security certification.

Starting audited implementation: [`7a65b7fe5cd3cf7841ceb8cb7ddb22b8d7cf9b36`](https://github.com/rlbsem/enterprise-acquisition-onboarding/tree/7a65b7fe5cd3cf7841ceb8cb7ddb22b8d7cf9b36). Corrected, final tested implementation: [`dc17ad5f627a1c3d84db9e8032d7ac1a0ba1ac40`](https://github.com/rlbsem/enterprise-acquisition-onboarding/tree/dc17ad5f627a1c3d84db9e8032d7ac1a0ba1ac40). Subsequent delivery changes only acceptance records, README and roadmap. No application feature, schema, financial policy, native integration or infrastructure was changed.

## Method and reproduction

Reviewed the source and assertions at the identity, mapping, admission, outbox/receiver, financial-publication and console boundaries. Inspected SQL constraints/privileges, transactions and locks, session/CSRF checks, source selection, dbt grain and publication rechecks. Passing counts were treated as observations to challenge. Five focused additional tests assert actual PostgreSQL consequences, including complete control-row hashes before and after denied requests.

Used a fresh clone and Python 3.12.14 virtual environment, the repository's exact dependency lock, existing PostgreSQL 17.11 binaries with fresh private clusters/databases/roles, and freshly installed pinned Playwright Chromium. All business inputs are synthetic. The first restricted execution could not connect to its own database; the enabled local-connection lane then succeeded. Private logs and generated credentials remain outside published evidence.

| Executed procedure | Result |
|---|---|
| Original-byte/source/link checker before review | Exit 0; 49 archived artifacts and 69 local Markdown links |
| Fresh baseline at supplied starting head | Exit 0; 57 tests, no failures/errors/skips; all four standalone demonstrations |
| Five additional focused adversarial tests | Exit 0; database and real HTTP controls passed |
| Final complete verification at corrected revision | Exit 0; 62 tests, no failures/errors/skips; all four demonstrations |
| Final browser acceptance | 53 checks; seven screenshots, each asserting actual route and heading; seven axe-core 4.11.0 view evaluations, zero violations/unresolved checks after recorded visibility follow-ups |
| Financial reproduction | Each valid version builds nine real PostgreSQL dbt models and passes nine data tests; seven exact application-oracle comparisons per version |
| Additional overallocation control | Real dbt amount test fails as expected; candidate has no publication and cannot be read through console HTTP |
| Standalone reviewer financial calculation | Both versions agree with source arithmetic; zero differences; one-cent publication and multiplied-join negatives detected |

[Commands and exit codes](run01/commands.json) · [Final verification and exact source hashes](run01/verification.json) · [Original baseline](baseline/verification.json) · [Artifact manifest](run01/manifest.json)

## Claims challenged

| Boundary | Negative controls and observed consequences |
|---|---|
| Canonical identity/legal scope | Reused `100` and identical trade names remain company-scoped; wrong entity stays quarantined. A Cedar candidate submitted for Summit returns 409, no crosswalk/resolution/decision is written, and original quarantine/hash survives. Forged review IDs, changed company path and injected decision fields fail. |
| Source ownership/current authority | Original regressions exercise unauthorized fields, lower/gapped revisions, observation regression, invalid transitions, stale decisions, changed mapping, exact coverage gaps and forged ready flags. Pending changes fail without activating a mapping or erasing history; dispatch recomputes current authority. |
| Durable execution/recovery | Replays, conflicting idempotency bodies, lost acknowledgement, independent receipt plus record readback, genuine worker kill, competing worker, unknown readback and three-attempt exhaustion are reproduced. Historical proof can confirm an existing effect after authority is revoked, while a new plan returns 409; effects/records/POSTs each remain one. |
| Financial grain | Header/line/credit/posting and allocation grains independently recalculated. A deliberately naive two-line by two-posting join multiplies Cedar I1 gross by four and is detected. Extra allocation makes an $80,000 payment fund $90,000; actual dbt controls reject publication. |
| Reporting/history | Accepted source revisions are independently selected at each cutoff and matched to frozen inputs/hashes. Pre-acquisition and held invoices remain excluded. Original publication/cutoff replay survives later correction. Unbalanced and overallocated candidates remain unpublished. |
| Console authorization | Direct HTTP covers every write route with sponsor/operator roles and missing/forged CSRF/foreign origin; all 30 requests fail before any control-row change. Cross-company report/source/company targets, forged identifiers and modified decision requests fail. A legitimate owned frozen source is readable as a positive control. |
| Sessions | Invalid, oversized, empty and copied post-logout sessions fail across read and write routes (24 requests); revoked session rows are absent and control rows are unchanged. Existing tests also force server-side expiry and verify browser redirects, origin/throttling and restricted SQL roles. |

Targeted records: [identity](run01/identity-negative.json), [write routes and row hashes](run01/write-route-matrix.json), [logout replay](run01/session-replay.json), [historical authority](run01/historical-authority.json), [payment and unpublished access](run01/payment-and-publication-negative.json). Full regression cases are enumerated in `verification.json`; recovery observations are exported beside it.

## Independent financial comparison

The [standalone reviewer calculation](../../../scripts/pass5_financial_oracle.py) imports no onboarding/dbt/original-oracle code. It selects accepted source revisions directly from the new execution's exported original source bodies, verifies their hashes and frozen-input equality, groups documents before summing, checks allocations and bilateral elimination evidence, and compares entity/portfolio totals. It is an additional implementation of the stated finite policy, not independent certification of that policy.

| Synthetic USD, selected January/February/October periods | Original | Restated |
|---|---:|---:|
| Net invoicing before elimination | 388,000 | 408,000 |
| ERP postings before elimination | 383,000 | 403,000 |
| Allocated cash | 230,000 | 230,000 |
| Supported elimination | 20,000 | 20,000 |
| Consolidated net invoicing | 368,000 | 388,000 |
| Consolidated ERP postings | 363,000 | 383,000 |

**Open exceptions remain separate: $5,000 Cedar I2 posting difference; $8,000 Cedar IC2 unsupported elimination candidate.** Oracle agreement is calculation agreement, not resolution of accounting differences. Only exact IC1 bilateral evidence supports $20,000 elimination. Meridian's $90,000 January invoice and Summit's $100,000 October invoice remain excluded for different reasons. The late source correction changes five January bridge measures by $20,000 without changing cash or causing a downstream POST.

[Reviewer arithmetic, source-set hashes and negative controls](run01/independent-financial.json) · [Actual sources/dbt/publications](run01/pass3.json)

## UI and evidence disposition

Inspected the fresh desktop sponsor, company, reviewer, reconciliation and reporting-history captures and the two mobile views. Browser interactions exercise navigation, version/month selectors, scoped source dialogs, actual rejected/approved review operations, mapped admission, keyboard focus/Escape and logout. Current Summit admission can become admitted at mapping v2 while the financial publication still clearly shows held-at-publication state. Navigation does not dispatch remote writes. UI success messages are backed by persisted decisions/audits and failed writes leave rows unchanged.

**F5-01, nonblocking, fixed:** the initial mobile finance screenshot/a11y scan could run against stale portfolio content. The initial run's 52 passing browser assertions did not establish that view. The driver now waits for its unique heading and invoice region before scanning, and asserts/records route plus heading for every capture. [Detailed finding and reproduction](findings.md). The [initial mislabeled capture](baseline/financial-mobile.png) and original baseline remain intact; use the [corrected mobile finance capture](run01/financial-mobile.png) for acceptance. The rejected intermediate locator correction and its failing run are disclosed in `commands.json`.

Once the actual mobile finance view was scanned, axe initially marked 46 horizontally clipped table nodes inconclusive for contrast (`elmPartiallyObscured`). The diagnostic scrolled every affected node into view and obtained an explicit contrast pass for that exact node. Final acceptance preserves the initial incomplete counts and all per-node follow-ups; it fails on any other inconclusive result or missing explicit pass. This resolves the visibility-related checks without disabling rules, waiving nodes or altering the application layout. It is still a finite automated accessibility evaluation, not comprehensive accessibility certification.

[Portfolio desktop](run01/portfolio-desktop.png) · [Finance desktop](run01/financial-desktop.png) · [History](run01/history-desktop.png) · [Company](run01/company-desktop.png) · [Reviewer](run01/governance-desktop.png) · [Portfolio mobile](run01/portfolio-mobile.png) · [Finance mobile](run01/financial-mobile.png) · [Browser checks and actual database audit](run01/pass4.json)

## Integrity, CI and remaining limits

[Historical integrity record](run01/historical-integrity.json) compares every Pass 1–4 evidence file byte-for-byte with the starting commit. Both run manifests hash exported records/images. Verification checks source hashes against committed bytes before and after execution. The source revision's [Linux PostgreSQL/dbt/Chromium CI](https://github.com/rlbsem/enterprise-acquisition-onboarding/actions/runs/40270066744) passed all 62 tests and the complete verification procedure; its [CI record](run01/ci.json) includes actual job steps and summary lines. Final delivery-head status is visible on [PR #1](https://github.com/rlbsem/enterprise-acquisition-onboarding/pull/1), whose description pins the completed final check.

Documented limitations remain: loopback HTTP and generated local users, no production SSO/TLS certification or per-company database RLS; trusted setup/host administrator; no native vendor calls or CDC-completeness proof; selected synthetic USD periods rather than general FX/statutory consolidation or recognized revenue; finite bounded recovery tests rather than universal exactly-once execution or production reliability. Rejection evidence here is the retained source/quarantine and captured HTTP/database observations; rejected malformed review attempts are not claimed to create a separate durable application audit entry. No load/performance certification, Internet exposure test or independent human certification was performed.

There are no unresolved material release blockers **within the demonstrated local synthetic scope**. Production deployment remains unverified and is outside the authorization for this delivery. No merge, deployment, vendor contact or unrelated repository modification occurred.
