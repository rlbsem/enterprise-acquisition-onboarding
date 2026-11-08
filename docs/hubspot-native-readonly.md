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

The two objects were created with explicit authorization through the connected
HubSpot CRM interface. On **November 7, 2026 (November 8 UTC)**, the Python
adapter executed successfully against the real HubSpot API. Two subsequent
GETs using a separate standard-library HTTPS client and parser independently
confirmed the expected records and relationship. [Exact results and retained
failures](evidence/hubspot-native/2026-11-08/README.md).

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

The GitHub provider-contract tests inject synthetic `httpx.MockTransport`
responses, **not** a real Service Key. CI also validates the recorded native
artifacts offline with `python scripts/check_hubspot_native_evidence.py`.
CI must **never** be given the real credential. Use fresh
private evidence storage for any native acceptance record; keep historical
Pass 1–5 bundles and the annual scenario unchanged.

## What this does and does not establish

| Boundary | Status |
|---|---|
| Native HubSpot Service Key authentication and exact live reads | **Executed and verified** at source `0e6a5b6ae0ef0cf05b75f636e9ab5676499b1cf4`; two application GETs and two independent verification GETs |
| Existing two native HubSpot objects and association through connected CRM | Readback previously verified independently of this adapter |
| API client enforcing read-only methods and fixed object paths | Implemented; covered by synthetic HTTP contract tests |
| Exact record IDs, expected name/email and two-direction link | Enforced by native adapter on actual GET responses |
| Company–legal-entity crosswalk, source revisions, field ownership, admission gate | **Not connected or proved by this read-only lane** |
| HubSpot change stream, CDC coverage, webhook delivery or retry-safe CRM writes | **Not claimed** |
| Enterprise throughput, production portal, production client data | **Not claimed** |

The full acquisition application already demonstrates canonical identity,
No-Regress Logic, outbox/receipt recovery and financial controls against
**local synthetic** HTTP and PostgreSQL boundaries. This addendum is narrower:
genuine HubSpot **read-only access** is an additional, independently
verified boundary recorded by the separately authorized service-key run.
Read-only API calls do not establish idempotent **writes** or remote receipts.

## Association semantics and fixture repair

The first authenticated run returned HTTP 200 for both records but failed
acceptance. The contact also referenced an unexpected company; its cause is
not established. With separate owner approval, the owner browser removed only
that association. HubSpot required selecting Cedar as the replacement primary
company. No records were deleted, no properties were manually edited, and no
key scopes or account settings changed. This fixture repair was a **write**,
distinct from the GET-only native program.

HubSpot can return both primary and unlabeled types for the same relationship.
The corrected parser allows different types for one object identity, rejects
repeated identical `(id, type)` pairs and ambiguous untyped repeats, and still
requires the exact singleton company/contact identity in each direction.
An unexpected second company remains a hard failure. The archived failed
observations are retained rather than replaced by the corrected result.

## API references

- [HubSpot 2026-09 Contacts API](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/guide)
- [HubSpot 2026-09 Companies API](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/companies/guide)
- [HubSpot Service Keys](https://developers.hubspot.com/changelog/service-keys)
- [HubSpot association types and labels](https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide)
- [HubSpot primary-company associations](https://knowledge.hubspot.com/records/associate-records)
