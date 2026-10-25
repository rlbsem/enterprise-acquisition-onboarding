# Pass 1 admission contract

## Grain, identity and authority

The input is `source-customer.v1`: one versioned customer-account snapshot owned by a registered source in one company and legal entity. It is not a vendor webhook schema or a financial transaction. Source record IDs are preserved exactly. Company, source and source ID jointly scope identity; the canonical UUID is stable within that company. A common trade name across companies is not evidence that their billing accounts are interchangeable.

An approved `admission-mapping.v1` assigns CRM ownership of display name and commercial state, operations ownership of service state, and finance ownership of account-control state. Every lifecycle field requires explicit local-to-canonical values. Unsupported fields, unknown states, stale/conflicting revisions, observation-time regression and invalid transitions quarantine the entire message. Source revisions are consecutive integers in this local contract; they are not Salesforce CDC replay IDs.

A reviewed crosswalk is required. Zero links is unmapped; multiple weak name candidates require review. Neither creates a customer. SQL uniqueness forbids conflicting source IDs and duplicate same-source identities for one canonical account/version. Legal-entity foreign keys constrain registry and crosswalk scope. Original source structures, messages, rejected deliveries and approval references are retained.

## Admission checks

A company is included only if an admission observation passes and remains consistent with current persisted inputs:

1. An active, exact-content approved mapping covers all three registered source domains.
2. Reviewed source inventories exist and are nonempty for that mapping version.
3. Actual source-ID/revision/content sets exactly equal each reviewed inventory.
4. Each source row reconciles to its crosswalk, raw hash, normalized fields and exact field provenance.
5. Each observed canonical customer is covered by CRM, operations and finance.
6. No unresolved quarantined message or identity collision exists.

The accepted input fingerprint includes mapping identity, coverage, raw source hashes, normalized facts, crosswalk-derived identity, message lineage and quarantine state. Portfolio reads use one repeatable-read snapshot and recompute the gate. A status flag or matching record count alone cannot authorize inclusion. New source facts stage the company again; a new mapping version requires new reviewed coverage. Replays of identical facts do not create new business rows or invalidate a valid gate.

The source inventories are independently reviewed acquisition fixtures, not an attestation from live vendor APIs. They demonstrate exact set reconciliation; they do not prove a real external source supplied every record. Snapshot baselines and revision checks do not establish CDC retention or continuity.

## API and database boundaries

`POST /v1/intake` uses a generated source identity bound to one company/system. `POST /v1/admission/{company}` requires a separate controller identity and can only request the computed check. `GET /v1/portfolio` requires the sponsor read identity. No API approves mapping changes, edits source ownership, links candidates or overrides quarantine. Tokens are headers, never URL parameters; access logging is disabled in the local harness.

The application database login may write ingestion/control state but cannot edit registry identity, mapping approval, reviewed baselines or crosswalks. Accepted message content, mapping records, delivery evidence, gate observations and audit records are protected from mutation. The trusted fixture installer owns schema creation and synthetic reset. It is not an untrusted operating-company identity. A compromised application/database administrator is outside this Pass 1 boundary; per-brand database identities/RLS and production SSO remain later work.

## Deliberate limits

Mappings and baselines are versioned immutable rows installed through the local governance function, with a review identity/reference. Quarantine cannot be cleared through the intake API. A controlled link-resolution and resnapshot workflow is a Pass 2 prerequisite; source updates may be valid yet remain excluded until that governance exists. Registry acquisition dates are preserved, while historical financial inclusion and restatement policies belong to the later analytical pass.

No financial amounts are consolidated. No native Salesforce, HubSpot, LMN, Aspire, QuickBooks or NetSuite operation occurs. No receiver side effect, lost-ack recovery, statutory elimination, global party deduplication or production reliability is claimed.
