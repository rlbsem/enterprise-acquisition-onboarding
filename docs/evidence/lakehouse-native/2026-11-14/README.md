# Native Databricks acceptance

Synthetic financial fixtures; actual Databricks Jobs execution. These records
are distinct from the earlier management-only preflight, PostgreSQL tests and
native HubSpot read-only proof.

## Preserved observations

`01-runtime-failure.json` records the first actual run at source
`9ee5faec9c32a39954f77c987c932c3da5f670e8`. The default notebook environment
rejected the Python 3.11 `datetime.UTC` alias under Python 3.10, before the
acceptance function or table creation executed. It is a failure, not Spark or
financial acceptance. A subsequent source revision uses `timezone.utc` and
records the selected runtime explicitly.

Public records contain allowlisted task results, run identifiers and source
revisions. Private observations are fingerprinted; raw authentication,
account/identity metadata, provider logs and managed-storage paths are excluded.
Those private-response hashes are not provider-signed attestations. The original
failure bytes remain unchanged as later execution records are added.

See the [execution contract and current ledger](../../../lakehouse-native-execution.md)
and [credit/lifecycle controls](../../../lakehouse-cost-review.md).

```text
python scripts/check_lakehouse_native.py
```

CI verifies the exported record integrity offline. It does not access Databricks
or rerun native workloads. No production reliability or business outcome is claimed.
