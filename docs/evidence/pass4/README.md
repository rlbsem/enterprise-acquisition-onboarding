# Pass 4 authenticated console acceptance

Executed implementation: [`dc8591072eae90a8587ec6a28a8f309fa4746d02`](https://github.com/rlbsem/enterprise-acquisition-onboarding/tree/dc8591072eae90a8587ec6a28a8f309fa4746d02). Recorded `2026-10-26T03:42:30.284515+00:00` on Windows with Python 3.12.14. [Verification](run01/verification.json) pins actual committed source bytes, including HTML/CSS/JavaScript, SQL, browser driver and vendored accessibility engine. A preflight rejects mismatched working-copy bytes before acceptance.

**57 regression tests passed; zero failures, errors or skips.** All original Pass 1–3 tests remain included. [Real Chromium execution](run01/pass4.json) records **52 passing checks**, seven accessibility scans and seven screenshots. Engine: 156.0.8078.4, Playwright 1.64.1. Axe-core 4.11.0 reported zero violations and zero unresolved checks across the seven scanned views. This finite scan is not a complete accessibility/security certification.

| Acceptance | Actual result |
|---|---|
| A: Sponsor scope | Authenticated sponsor inspected Cedar, Meridian and Summit and both validated financial versions |
| B: Company isolation | Cedar leader received only Cedar rows; crafted Meridian/company/report targets returned 403 and a Meridian source-event lookup returned 404 |
| C: Unauthorized review | Sponsor/operator writes and missing-CSRF/reviewer-outside-scope requests were denied without creating decisions |
| D: Genuine review | Browser persisted rejected identity, approved fresh identity and approved mapping decisions; PostgreSQL actor/reason/audit records confirm the session-bound reviewer |
| E: Publication figures | Original/restated net invoicing USD 368,000/388,000, ERP postings USD 363,000/383,000, cash USD 230,000; January selector shows USD 160,000/180,000 net invoicing |
| F: Open exceptions | USD 5,000 posting discrepancy and USD 8,000 unsupported intercompany candidate remain separate |
| G: Reporting perimeter | Meridian's USD 90,000 January invoice is pre-acquisition; Summit's USD 100,000 October invoice remains held in the immutable reporting snapshot |
| H: No downstream dispatch | Receiver POSTs and effects remain one before and after navigation, period/version changes and governance review |
| I: Responsive layout | Desktop and 390-pixel mobile views render without page overflow; mobile admission cards retain company, entity, status, acquisition date, mapping and inspection access |
| J: Keyboard/accessibility | Keyboard sign-in/focus, navigation, source-dialog activation/Escape and semantic forms execute; desktop/mobile scans have no violations or unresolved rules |

The browser lane executes fresh actual financial source intake and dbt builds through the existing Pass 3 driver; it does not import static numbers into a mock dashboard. Its `financial_execution` records both validated dbt builds and independent comparisons. The separate [Pass 3 demonstration](run01/pass3.json), [Pass 2 demonstration](run01/pass2.json) and [Pass 1 demonstration](run01/demo.json) also ran during this acceptance. Earlier archives are preserved unchanged; these are separate local executions, not one native vendor workflow.

The authorized reviewer selects an explicit scoped candidate, rejects one proposal, and approves a new proposal. Re-approving the rejected decision returns 409. Mapping activation creates version 2 and preserves version 1. Current Summit admission then passes while the original/restated financial publications still retain held status and mapping version 1. Two customer candidates remain; no destructive merge or automatic financial republication occurs.

The console reader is independently denied access to the working dbt table. The unbalanced candidate is not a validated publication and returns 404. Source dialogs read frozen original source bodies, and restricted projections omit other companies' source records. Backend tests cover server expiration/logout, opaque cookies, same-origin/CSRF checks, login throttling, role scope, credential-domain separation and SQL privileges.

## Genuine screenshots

All PNGs are direct full-page Chromium captures with no manual image editing. Their route, role, viewport, reporting scope/version and actual capture timestamp are recorded in `pass4.json`; hashes are in the manifest. Portfolio/mobile captures precede review; the governance capture follows the recorded decisions.

- [Portfolio desktop](run01/portfolio-desktop.png)
- [Financial reconciliation desktop](run01/financial-desktop.png)
- [Reporting history desktop](run01/history-desktop.png)
- [Operating-company desktop](run01/company-desktop.png)
- [Reviewer workflow desktop](run01/governance-desktop.png)
- [Portfolio mobile](run01/portfolio-mobile.png)
- [Financial mobile](run01/financial-mobile.png)

[Artifact manifest](run01/manifest.json) protects all exported records and images. `scripts/check_repository.py` checks original-byte integrity, pinned source revisions, financial recomputation, browser/tenant results, SQL audit decisions, PNG dimensions, provenance, links and public-content patterns. Credentials, profiles, session/CSRF values, browser traces and raw runtime logs are excluded. All owned local resources were stopped.

This is a loopback-only synthetic application with server-scoped sessions, not production SSO/TLS or per-brand PostgreSQL RLS. It has no native financial-vendor execution, recognized revenue, commercial outcome, public deployment or independent Pass 5 audit. [Run and inspect](../../operations-console.md). The PR remains draft and unmerged.
