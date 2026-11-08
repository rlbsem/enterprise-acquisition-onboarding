# Native HubSpot read-only acceptance — Cedar Services

This is a **new, isolated native provider-boundary verification lane**, separate from the
three-company local admission workflow and its immutable historical evidence.
The only records in scope were explicitly created as synthetic acceptance data
in the **Groundbreakers — Integration Engineering Lab** portal.

## Source-bound fixture

| Field | Expected native value |
|---|---|
| HubSpot portal | `343801908` (configured expectation, **not** independently authenticated by this reader) |
| Company object (0-2) | `229684469730` — Cedar Services — Synthetic Acceptance |
| Contact object (0-1) | `288567817180` — Cedar Test Contact |
| Synthetic contact email | `cedar.test.contact@example.com` |
| Required association | Company-to-contact **and** contact-to-company must agree |
| Allowed operations | Two exact **GET** requests; no POST, PATCH, PUT or DELETE |
| API path | `/crm/objects/2026-09/{companies|contacts}/{recordId}` |

The two objects and their association were created with explicit authorization
using the connected HubSpot CRM interface and independently read back through
that interface. **That does not mean this Python adapter has yet run natively.**

The separate, user-created **HubSpot Service Key** is intended for the native
read-only pass and has only:
- `crm.objects.companies.read`
- `crm.objects.contacts.read`

The integration **does not require write scopes**. Never expand those scopes to
satisfy a test failure; investigate the exact failed endpoint first.

## Execute one bounded native read

Run only in a private, authorized environment where the **real Service Key is
available to the Python process** as an environment variable named
`HUBSPOT_SERVICE_KEY`. Use your secure runtime's secret injection; do **not**
paste the value into a shell command, source file, configuration committed to
Git, issue, chat, CI log or screenshot.

```text
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m onboarding.hubspot_native --read-only
```

The explicit flag is required; absent credentials block *before* network access.
The adapter's API origin is fixed to `https://api.hubapi.com`; no user-input
URL is accepted. Its two individually addressed, dated-version object GETs
request only the expected properties and associations. It does not enumerate
the portal, modify records, emit the bearer token, follow redirects, issue
automatic retries or log raw responses. Authentication errors, missing objects,
429s, timeouts, paginated/ambiguous associations and mismatched properties
**fail closed** with sanitized reason codes.

A successful stdout result contains checked categories, a deterministic
sanitized-projection SHA-256 and an observation timestamp. It is **not**
credential proof, a signed attestation, raw vendor evidence, or proof of the
portal account ID from the API. Do not present it as one.

Run the offline contract regressions without credentials:

```text
python -m pytest -q tests/test_hubspot_native.py
```

The GitHub CI tests inject synthetic `httpx.MockTransport` responses, **not**
a real Service Key. CI must **never** be given the real credential. Use fresh
private evidence storage for any native acceptance record; keep historical
Pass 1–5 bundles and the annual scenario unchanged.

## What this does and does not establish

| Boundary | Status |
|---|---|
| Native HubSpot Service Key authentication and exact live reads | **Not yet executed by this application** until the private key is injected into a runtime and this command succeeds |
| Existing two native HubSpot objects and association through connected CRM | Readback previously verified independently of this adapter |
| API client enforcing read-only methods and fixed object paths | Implemented; covered by synthetic HTTP contract tests |
| Exact record IDs, expected name/email and two-direction link | Enforced by native adapter on actual GET responses |
| Company–legal-entity crosswalk, source revisions, field ownership, admission gate | **Not connected or proved by this read-only lane** |
| HubSpot change stream, CDC coverage, webhook delivery or retry-safe CRM writes | **Not claimed** |
| Enterprise throughput, production portal, production client data | **Not claimed** |

The full acquisition application already demonstrates canonical identity,
No-Regress Logic, outbox/receipt recovery and financial controls against
**local synthetic** HTTP and PostgreSQL boundaries. This addendum is narrower:
genuine HubSpot **read-only access** will be an additional, independently
verified boundary once the separately authorized service-key command runs.
Read-only API calls do not establish idempotent **writes** or remote receipts.

## API references

- [HubSpot 2026-09 Contacts API](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/guide)
- [HubSpot 2026-09 Companies API](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/companies/guide)
- [HubSpot Service Keys](https://developers.hubspot.com/changelog/service-keys)
