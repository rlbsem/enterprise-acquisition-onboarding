# Native HubSpot read-only acceptance

**Verified:** the application read the approved synthetic Cedar company and
contact from the real HubSpot API. A separate HTTPS client independently
confirmed their exact properties, archived=false and bidirectional association.
This is application-owned API execution, not connector readback or a mocked test.

| Execution | Recorded result |
|---|---|
| Accepted source | [`0e6a5b6ae0ef0cf05b75f636e9ab5676499b1cf4`](https://github.com/rlbsem/enterprise-acquisition-onboarding/commit/0e6a5b6ae0ef0cf05b75f636e9ab5676499b1cf4) |
| Command | `python -m onboarding.hubspot_native --read-only` |
| Application observation | November 8, 2026, 03:33:20.697776 UTC (November 7 Toronto) |
| Independent verification completed | November 8, 2026, 03:33:21.104477 UTC |
| Provider | `https://api.hubapi.com`, dated CRM API `2026-09` |
| Application result | Exit 0, `verified`; two exact GET requests |
| Independent result | Two HTTP 200 responses; all nine identity/property/relationship checks true |
| Synthetic company/contact | `229684469730` / `288567817180` |
| Portal boundary | Groundbreakers — Integration Engineering Lab, `343801908`, verified in Service Key UI; object GETs do **not** independently authenticate portal ID |
| API credential permissions | `crm.objects.companies.read`, `crm.objects.contacts.read`; no write scopes |

## Inspect the observations

- [Application result](attempt-04/cli.json), [independent response projections](attempt-04/independent-responses.json), [acceptance result](attempt-04/acceptance.json), [executed source hashes](attempt-04/source.json).
- Independent company response correlation: `01a1b937-b0d8-7f4d-8f5d-6643c5e6afd7`.
- Independent contact response correlation: `01a1b937-b1ab-7f8b-bd12-e3e55799b0ad`.
- [Provenance and 140 original evidence hashes](provenance.json), [archive inventory](artifact-sha256.json).

These are allowlisted source fields and actual request metadata. Raw provider
response bytes, HTTP authorization headers and credentials are deliberately
not published. Raw-response hashes record what the private runner observed;
without those private bodies they cannot be recomputed from the public projection
and are not vendor-signed attestations. The independently reconstructed bounded
projection matches the application's SHA-256. HubSpot response `Date` headers
and local timestamps are both retained; they are separate clocks.

## Preserved failures and approved correction

1. [Attempt 01](attempt-01/acceptance.json) and [attempt 02](attempt-02/acceptance.json): transport unavailable; no provider HTTP response. The second records a DNS-resolution error. Neither proves authenticated API execution.
2. [Attempt 03](attempt-03/cli.json): real authenticated reads, but `duplicate_association` blocked the original parser. [Independent observations](attempt-03/independent-responses.json) additionally show the contact linked to unexpected company `229742254061`, not just the approved Cedar company. The reason the extra relationship existed is unproven.
3. A [separately approved owner-browser fixture repair](fixture-repair.json) removed only that extra association. The UI required Cedar as replacement primary. No record deletion or manual property change occurred; automatic modification timestamps were retained. [Genuine repair screenshot](association-repair.jpg).
4. The parser correction accepts primary and unlabeled types for the **same** identity, while rejecting repeated identical typed links, ambiguous untyped duplicates, incomplete paging and extra identities. [Successful attempt 04](attempt-04/acceptance.json) independently observes both primary/unlabeled types for each correct relationship. A regression explicitly retains rejection of a second company.

The API program made no CRM writes. The owner-browser repair was a real,
separately authorized relationship write; it must not be described as read-only.
Both synthetic records remain for controlled acceptance, with Cedar their sole
company relationship. No integration, key, user permission or account setting
was changed during this completion.

## Reproduce the checks

Install the pinned dependencies as described in the [native lane guide](../../../hubspot-native-readonly.md).
Offline, without a key or vendor requests:

```text
python scripts/check_hubspot_native_evidence.py
python -m pytest -q tests/test_hubspot_native.py tests/test_hubspot_native_evidence.py
python scripts/check_repository.py
```

The checker verifies every archived artifact, the source bytes at the actual
executed commits, all 140 prior evidence files, exact observed identities and
properties, association types, preserved failures and execution boundaries.
Tampering tests exercise content assertions separately from hash validation.
CI uses this offline lane and mocked provider responses, never the live key.

[execute_private.py](execute_private.py) and [secure_launch.py](secure_launch.py)
are byte-for-byte archives of the **final** private execution harness, not new
public API entry points. Earlier harness revisions were not retained; their
source/CLI/response observations are preserved. The final harness originally
ran under `.local/hubspot-native-20261107/`; its relative paths depend on that
location. A separately authorized repeat requires restoring that layout,
reviewing/pinning the intended source revision and choosing a fresh output
directory. Do not run the archive in place or overwrite these records. Inject
the existing read-only credential privately; no secret is needed for CI.

## Scope

This acceptance proves only bounded native reads of two synthetic objects and
their relationship. It does not connect HubSpot to acquisition admission,
validate CDC/webhooks, establish retry-safe CRM writes, or demonstrate production
throughput or commercial outcomes. Original PostgreSQL/HTTP/dbt financial and
recovery evidence remains separate and unchanged. No cloud infrastructure was
provisioned and no prospect communications occurred.
