# Sponsor and acquisition operations console

The local FastAPI application serves plain HTML/CSS/JavaScript. Live company/control views query PostgreSQL; financial views query **immutable validated publications and their frozen source inputs**. The console SQL reader has no access to the working dbt schema. An unpublished candidate never becomes selectable merely because its analytics tables exist.

## Routes and roles

| Browser route | Purpose |
|---|---|
| `/console/login` | Local credential sign-in |
| `/console/#portfolio` | Permitted acquisitions, current admission, published measures and separate variances |
| `/console/#company` | Scoped identity, three source domains, mapping, recorded recovery proof and company financial rows |
| `/console/#governance` | Original quarantine, candidates, proposals, immutable decisions, mappings and admission recomputation |
| `/console/#finance` | Invoice/posting/cash reconciliation, intercompany evidence and original source drilldown |
| `/console/#history` | Original/restated publication, exact bridge, held/pre-acquisition exclusions and captured control state |

The sponsor reads all three configured companies and has no governance write authority. Each company leader reads only its configured company. The integration reviewer reads and acts only within Summit. Direct API targets, report parameters and source-event IDs are checked server-side; hiding controls in the browser is not the authorization boundary. Restricted report projections omit other companies' rows and source records.

Reviewer forms call the existing identity/mapping/correction contracts. A proposal is distinct from a decision. Actor identity comes from the session, and a reason is required. Rejected decisions stay rejected; source/mapping changes invalidate stale proposals. Admission recomputation invokes the existing gate, never an override. The UI cannot dispatch a handoff, create a financial fact or publish a report.

## Current controls versus recorded finance

The browser fixture executes the actual Pass 3 sources and dbt builds in a fresh owned database. Original/restated publications show USD 368,000/388,000 consolidated net invoicing, USD 363,000/383,000 ERP postings and unchanged USD 230,000 allocated cash. The USD 5,000 posting discrepancy and unsupported USD 8,000 intercompany candidate remain separate. January, February and October are selected periods, not a continuous YTD series. No recognized revenue is claimed.

The browser reviewer resolves Summit identity and activates mapping version 2. Its **current** admission can then pass while previously published financial versions still exclude Summit under their captured held state and mapping version 1. Reading or reviewing a record does not republish history. The Cedar recovery card is recorded independent-receipt evidence, not a new recovery operation. Receiver POST counts remain unchanged through browser navigation and review.

## Local sessions and SQL separation

Generated high-entropy credentials live only in the ignored workspace. Server configuration stores salted scrypt hashes; JavaScript contains no database credential or privileged API token. The session cookie is opaque, HttpOnly, SameSite Strict and host-only, with an absolute 30-minute server expiration. Logout deletes the server session. A browser timer also returns the user to sign-in at expiry. The cookie uses local HTTP without `Secure`; host checks and binding restrict the demonstration to loopback. This is not an Internet deployment configuration.

Login requires same-origin JSON and has a five-failure/ten-minute local throttle. State-changing authenticated browser actions require exact same-origin validation and the per-session CSRF token. Cookie auth and the earlier source/API-token identities are separate authentication domains. Responses prevent caching and framing and use a restrictive self-only content policy.

The session SQL login can manage only session/throttle tables. The console reader can select the required control/publication tables but cannot write governance or access sessions. The trusted server delegates authorized review actions through the existing governance login. Company scope is enforced in the API; per-brand PostgreSQL RLS, production SSO, MFA, public TLS and a hostile-host threat model remain outside this bounded lane. The independent Pass 5 audit has not occurred.

## Run and verify

Use the repository's pinned Python 3.12 / PostgreSQL 17 setup. To open a prepared application:

```text
python -m onboarding.console_demo --workspace .local/console-01 --serve
```

After actual financial preparation, the command prints the loopback URL and path to `console-credentials-private.json`. Open that private JSON locally for the generated `sponsor`, company-leader or `reviewer` credentials. Never commit it. Stop with Ctrl+C to close the owned API/receiver processes and databases. A fresh workspace is required; do not point this harness at a client or production database.

Browser acceptance additionally needs Chromium in the workspace browser directory. Before installation, set `PLAYWRIGHT_BROWSERS_PATH` to the checkout's `.local/browsers` folder: PowerShell `$env:PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/browsers"`, or macOS/Linux `export PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/browsers"`. Keep that setting for verification; CI sets the same path.

```text
python -m playwright install chromium
python scripts/verify.py --workspace .local/verify-04 --output .local/evidence-04
python scripts/check_repository.py
```

The runner uses Playwright 1.64.1 and vendored axe-core 4.11.0 (license and package integrity included). It performs real sign-in, role/scope negatives, financial/period selection, source dialogs, rejected/approved identity decisions, mapping activation, audit verification, logout/expiry and desktop/mobile checks. Seven scans cover WCAG 2 A/AA and 2.1 AA rules, including determinate contrast. These checks are not a complete accessibility or security certification.

[Pass 4 evidence and genuine screenshots](evidence/pass4/README.md) pin the implementation, outcomes and PNG hashes. Raw credentials, profiles, browser traces and private runtime logs are excluded. Earlier acceptance archives remain byte-identical. No native vendor integration, paid resource, public hosting or deployment is involved.
