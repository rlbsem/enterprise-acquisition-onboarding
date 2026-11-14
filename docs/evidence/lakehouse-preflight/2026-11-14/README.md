# Databricks management preflight

**Executed November 13, 2026 in Toronto (November 14 UTC).** This record proves
supported authenticated CLI/API metadata access. It is not Spark execution,
Delta correctness, effective Unity Catalog isolation or native recovery acceptance.

[management-reads.json](management-reads.json) records seven successful management
GET operations at source
[`10cce9425b716c4c4e0ba414af1a574be941b081`](https://github.com/rlbsem/enterprise-acquisition-onboarding/commit/10cce9425b716c4c4e0ba414af1a574be941b081).
CLI 1.26.0 was downloaded from the official release; its Windows amd64 ZIP
matched SHA-256 `7c7f2bdfc503d0277d60ef36d9ef6d9577769cd992bd3633691ebe47b9f214a2`.
The executed binary fingerprint and collector source hash are retained.

The account API identified AWS `us-west-2`, Premium, serverless workspace mode
and running workspace status. The metastore assignment and managed catalog
were observed. Jobs and principal listing succeeded and returned no objects;
that does not prove permission to create identities or run Jobs. The existing
Small serverless warehouse was stopped with zero clusters and ten-minute
auto-stop. No resource creation, compute start or SQL submission occurred.
Predictive optimization was inherited as enabled; future isolated schemas must
disable background optimization before accepting cost-bounded table workloads.

[feasibility.json](feasibility.json) separates the owner-reported USD400/14-day
trial observation, actual public Oregon pricing observation, separate account
usage probe and provisional cost model. Exact expiry, payment arrangement,
remaining storage costs and a native spending allowance are **not established**.
The account usage download returned no rows; this is not billing clearance.
The recorded launch gate therefore stays closed for four explicit reasons.

Account, workspace and host identifiers are SHA-256 bindings rather than public
endpoints. Emails, storage URLs, OAuth material and private configuration are
excluded. Response hashes refer to CLI stdout before projection; original
response bodies are not distributed and those hashes cannot be recomputed from
the public projection. The record is not a provider-signed attestation.

[artifact-sha256.json](artifact-sha256.json) protects this record's data files.
[historical-sha256.json](historical-sha256.json) binds all **228 existing evidence
files**, which remain unchanged. The current README is an explanatory entry
point outside the data-file inventory.

```text
python scripts/check_lakehouse_preflight.py
python -m pytest -q tests/test_lakehouse_preflight.py tests/test_lakehouse_preflight_evidence.py
```

These checks use the committed record without vendor credentials or compute.
They validate the original source bytes, explicit unexecuted boundaries and
closed gate. Native data acceptance remains a later, gated milestone.
[Reproduction and acceptance contract](../../../lakehouse-acceptance.md).

## Subsequent owner observation

After this API capture, the owner confirmed that no payment method is linked.
The owner-reported balance remains USD400 with 14 days remaining. This updates
the current feasibility assessment without rewriting the earlier JSON, its
timestamps or closed-gate reasons. Exact expiry, complete cost assumptions and
a bounded trial-consumption allowance still need to be established before a
native pilot. No account or infrastructure changes followed the confirmation.
