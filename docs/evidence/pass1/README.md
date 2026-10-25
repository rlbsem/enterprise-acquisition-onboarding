# Pass 1 executed acceptance

Executed implementation: [`e10c676401c0e7afb503afb5fc6f638f90a9b09f`](https://github.com/rlbsem/enterprise-acquisition-onboarding/tree/e10c676401c0e7afb503afb5fc6f638f90a9b09f).

[Verification record](run01/verification.json) contains the actual 23 passing pytest cases, zero failures/errors/skips and exact source fingerprints. [Standalone demo](run01/demo.json) records real loopback HTTP requests backed by PostgreSQL, with source-linked normalized records, quarantine, admission observations and the final portfolio projection. [Artifact hashes](run01/manifest.json) protect the original bytes. Execution time and synthetic source-observation time are separate.

| Scenario | Expected | Observed |
|---|---|---|
| Clean onboarding | Two reviewed companies admitted | Cedar and Meridian portfolio-ready; two scoped customer accounts included |
| Identity ambiguity | No weak automatic merge | Summit CRM quarantined as `ambiguous_identity`, with two candidate UUIDs |
| Mapping/legal-entity conflict | Wrong entity held | `incorrect_legal_entity`; Summit remains excluded |
| Retry/replay | No duplicate business row or readiness bypass | Same accepted message returns duplicate; source records remain eight |

Additional tests execute concurrent HTTP delivery, preserved original content after an identity collision, source-revision and lifecycle rejection, source coverage failure, mapping approval restrictions, immutable evidence, a read-only sponsor identity and direct database permission denials. A forged ready flag or changed normalized field fails fresh reconciliation.

All source systems are finite local contracts and all business records are synthetic. No native vendor operation, customer communication, finance transaction, paid cloud resource or production deployment occurred. No browser or native vendor acceptance is claimed. Each owned local API process and temporary database is stopped by the harness.

The mapping review/baseline is a trusted synthetic installer action, not independent human approval. Quarantine resolution, controlled source resnapshot, downstream dispatch/receipts and commit-then-lost-response recovery remain later work.
