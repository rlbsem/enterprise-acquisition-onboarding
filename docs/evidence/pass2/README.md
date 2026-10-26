# Pass 2 executed acceptance

Executed implementation: [`32c4e7475b12bf42898a51e697bd853db8159d10`](https://github.com/rlbsem/enterprise-acquisition-onboarding/tree/32c4e7475b12bf42898a51e697bd853db8159d10). Recorded at `2026-10-25T23:50:58.991324+00:00` on Windows with Python 3.12.14. Synthetic source-observation dates are distinct from execution time.

**39 tests passed; zero failures, errors or skips.** This includes all 23 original Pass 1 cases and 16 Pass 2 cases. The source-pinned [verification record](run01/verification.json) lists every case and exact implementation hashes. Two standalone demonstrations also completed: the [original admission slice](run01/demo.json) and [review/resnapshot/receiver slice](run01/pass2.json). All temporary owned resources were stopped by the harness.

| Scenario | Expected | Observed |
|---|---|---|
| A: Identity review | An explicit scoped decision resolves ambiguity without merging customers | Summit gate changes from held to passing; both customer candidates remain; a rejected proposal cannot be approved afterward |
| B: Wrong entity | Identity review cannot validate the original wrong-entity event | Review request rejected, admission held; accepted higher source revision supplies the correction; original message remains quarantined |
| C: Mapping resnapshot | Complete reviewed coverage precedes derived-state change | Incomplete inventory rejected; version 2 maps local `closed` to operations `complete`; new gate passes; version 1 and source history remain |
| D: Receiver proof | Exact content independently verified | One internal handoff, receipt and separately queried business record agree |
| E: Lost response | Recover the original effect without another commit | Sender timeout is `uncertain`; independent SQL observes the commit; readback confirms it; duplicate delivery returns the original receipt; changed payload returns HTTP 409 |
| F: Current authority | Changed admission, mapping, source revision or business facts prevent a new POST | Four controls record `blocked`, zero POSTs and zero receiver effects |

[Pass 2 execution](run01/pass2.json) includes original source messages and quarantine, immutable review decisions/resolutions, both mapping/baseline versions, source-record history, audit/gate observations, separate business facts, frozen outbox content, persisted attempt, receiver record/receipt and receiver request journal. The journal's status describes receiver processing, not proof that the sender received its response.

Negative-control observations: [admission](run01/authorization-admission.json), [mapping](run01/authorization-mapping.json), [source revision](run01/authorization-source_revision.json), [business revision](run01/authorization-business.json). [Exhaustion](run01/exhaustion.json) records three failed dispatch attempts and no receiver effect. Its finite test accelerates retry timing; ordinary calls are separately asserted to honor backoff.

[Process interruption](run01/process-death.json) records an actual child-worker termination after receiver commit and before sender confirmation. A simultaneous worker observes the effect lock; restart independently confirms the one original effect and one POST. Other passing cases cover unknown readback without dispatch, historical reconciliation after revoked admission, denied receiver SQL/governance access, stale reviews, unsupported/incomplete mapping contracts, forged finance authority and deliberately corrupted receiver content.

[Artifact inventory and SHA-256 hashes](run01/manifest.json) protect these bytes. `python scripts/check_repository.py` checks hashes, exact source revision, cross-record content, expected-versus-observed controls, local links and public-content patterns. The [original Pass 1 archive](../pass1/README.md) is unchanged.

These are real local PostgreSQL/loopback HTTP executions with synthetic data and an authorized synthetic reviewer, not native vendor or independent human acceptance. The receiver writes an internal onboarding handoff; no invoice, payment, cash, commercial outcome, production deployment or universal exactly-once guarantee is established. Pass 3 financial modeling and the independent final audit have not run.
