# Governed resolution and receipted execution

## Review a held acquisition

The generated reviewer identity is distinct from source intake, sponsor read and controller identities. It has an explicit company allowlist. `GET /v1/reviews/{company}` exposes original messages, candidate IDs, unresolved exceptions and current mapping. The API derives the actor from authentication; callers cannot supply an approving actor in the body.

1. Propose a scoped candidate with `POST /v1/reviews/{company}/identity`, giving `quarantine_id`, `candidate` and `reason`.
2. Decide with `POST /v1/reviews/{company}/{review_id}/decision`, giving `result` (`approved` or `rejected`) and `reason`. Decisions are immutable. A new proposal does not rewrite a rejected one.
3. A frozen context hash binds the proposal to source revisions, crosswalks, mapping and quarantine state. Changes make approval stale. A decision cannot merge customers, approve a wrong legal entity or grant source ownership.
4. Correct a wrong-entity or unsupported-state event through legitimate higher-revision source intake. The correction review links the accepted message to the original exception; it never edits that exception.

Mapping proposals contain `contract`, exact `coverage` and `reason`. Coverage names every current source ID, revision and raw hash across the three domains. Activation atomically installs the next mapping and baseline, preserves previous versions/crosswalks, reconstructs fields from current source evidence and records a new gate observation. No-Regress checks still apply. Source-ID, legal-entity-path or domain rekeying is rejected as a separate migration, not silently handled by this slice. The controller must explicitly recompute admission afterward.

`pass2.sql` is additive and backfills existing source projections into immutable history. The reproducible harness tests fresh disposable installations; it is not evidence of an in-place production migration.

## Keep business meanings separate

`POST /v1/business` accepts `business-fact.v1` from the authenticated company/source. CRM owns opportunity `won`; operations owns work-order `created`/`completed`; finance owns finance-account `verified`. Work orders reference a won opportunity for the same scoped customer. Consecutive revisions, mapping scope and non-regression are checked. Rejected facts remain in the event journal and can block dispatch of an outdated business snapshot.

This is a finance **account-control** contract, not invoice, payment, recognized revenue or cash. Operating-company and legal-entity IDs remain separate throughout the handoff.

## Dispatch and recover

`POST /v1/handoff/{company}` freezes the admitted customer snapshot and explicit opportunity/work-order/finance references into `onboarding-handoff.v1`. The stable effect ID derives from exact immutable content. Identical planning reuses the intent and attempt budget; a different governed snapshot is a different possible handoff. This is not a perpetual once-per-customer identity.

`POST /v1/outbound/{effect_id}/step` or `python -m onboarding.execution --config PRIVATE_SENDER_CONFIG --effect EFFECT_UUID` performs one bounded step:

- Query the independent receiver receipt and actual business record first. Verify full payload, hashes and expected content. An unavailable read is unknown; only a valid 404 establishes absence.
- Existing exact proof confirms historical execution even if current admission has been revoked. It cannot authorize another POST.
- Without proof, require current admission, mapping, source provenance and business references to match the frozen intent. Commit the attempt before POST; allow at most three attempts, with persisted exponential backoff capped at 30 seconds.
- Record `pending`, `uncertain`, `confirmed`, `exhausted` or `blocked`. A missing previously confirmed effect blocks rather than replaying. Exhaustion prevents new POSTs but still permits receipt reconciliation.

The local company lock serializes dispatch with intake and governance while the HTTP call runs. An effect lock prevents simultaneous workers from dispatching the same intent. These are bounded local controls, not a general distributed authorization guarantee. The API/CLI is explicitly stepped; no autonomous background scheduling or throughput guarantee is implemented. Exhaustion tests bypass elapsed backoff to exercise the finite budget; normal calls are checked to honor the persisted due time.

The receiver runs in another process and database with a separate login. One transaction commits an immutable internal onboarding record and its receipt. The sender has HTTP credentials but no receiver SQL, administrator or fault-injection configuration. Tests deny sender access to the receiver database. A trusted harness can inject a committed response delay, pre-commit unavailability or deliberate record corruption; those are controlled faults, not vendor behavior.

The harness owns both databases on one local host and can inspect receiver SQL independently. Same-host administrator/filesystem compromise is outside this isolation claim. Local tokens and SQL roles are not public production authentication.

## Executed acceptance

[Pass 2 records](evidence/pass2/README.md) preserve actual source history, review decisions, gate observations, outbound attempts, receiver receipt/record and request journal. A real child worker is terminated after the remote commit but before local confirmation; restart confirms one effect. The suite also verifies unknown readback, exhausted retries, stale reviews, revoked authority and content mismatch. These finite observations establish neither universal exactly-once execution nor production reliability. No native vendor, paid infrastructure or browser application is involved.
