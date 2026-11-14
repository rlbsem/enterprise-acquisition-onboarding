# Databricks execution cost and lifecycle controls

The owner authorized up to USD300 of bounded Databricks resource consumption,
starting with a native pilot targeting no more than USD20. The original
read-only observations remain preserved. See the [native execution ledger](lakehouse-native-execution.md)
for actual run status. No account upgrade or external AWS resources are permitted.

## Public rates observed

The actual rendered price pages were inspected on November 13, 2026 (Toronto),
selecting **Premium, AWS, US West (Oregon)**. These are public list prices, not
an invoice or proof of account feature entitlements.

| Component | Price/basis |
|---|---|
| Jobs Serverless | USD0.35/DBU; underlying compute included |
| Default storage | USD0.023/DSU |
| Stored bytes | One DSU per binary GB-month; prorated using 730 hours/month |
| AWS tier 1 storage operations | 0.2174 DSU per 1,000 PUT/COPY/POST/LIST operations |
| AWS tier 2 storage operations | 0.0174 DSU per 1,000 GET/SELECT/other operations |

Backing storage can remain billable **up to 30 days after deletion**. Namespace
deletion is not immediate storage-cost cessation or billing clearance. The
storage price page also identifies possible transfer/networking charges. Avoid
cross-region data, customer-managed AWS resources and private networking; bound
any evidence export.

Execution eligibility and approved account billing restrictions are prerequisites
for running workloads. Export evidence before access to the workspace ends;
workspace assets may subsequently be deleted. Resource deletion does not
establish final billing clearance.

## Authorized planning envelope

| Item | Assumption/reserve | USD |
|---|---|---:|
| Bounded native pilot | Correctness, rates and actual usage before expansion | 20 |
| Core native engineering | Delta, financial reconciliation, recovery and governance | 160 |
| Meaningful scale and failure measurements | Only after correctness and usage gates | 80 |
| Controlled reruns | Finite retry plan required | 20 |
| Evidence export, storage tail and cleanup | Protected final reserve | 20 |
| Total allowance | Owner-approved execution envelope; not a hard provider cap | 300 |

The assumed 50 DBU/hour is a planning reference, not an observed or enforced account cap. Actual usage is workload-dependent. A
finite native plan must bind task count, timeout, automatic-retry behavior,
source sizes and resource ownership. Start with a small measured pilot before
scaling. Budget alerts and timeouts are not hard financial caps.

Sensitivity, **not observed consumption**: five binary GB retained for 14 active
days plus a 30-day deletion tail cost approximately USD0.1664. Hypothetical
100,000 tier 1 requests add USD0.50002; 1,000,000 tier 2 requests add USD0.4002.
The combined USD1.0666 illustrates the storage reserve, before transfer/other
charges; it does not prove the future workload meets those byte/request bounds.

Keep the existing SQL warehouse stopped. Use bounded Spark Jobs and an isolated
namespace, without schedules or paid add-ons. Disable predictive optimization
only for the new acceptance schema before managed tables, then verify it.
Deletion and delayed usage must be checked separately from job correctness.

## Remaining gate

OAuth and management API access work, and a bounded native pilot is authorized.
Expansion requires successful pilot acceptance, actual usage and applicable
rate observations. Empty delayed usage exports do not establish zero cost.
Retain pending-consumption reserves and stop submitting work if projected or
delayed exposure could exceed the allowance. Current execution status and
uncompleted controls are in the native ledger; do not infer acceptance from a
successful management read or an available workspace.

Sources: [Jobs price list](https://www.databricks.com/product/pricing/lakeflow-jobs),
[storage rates and lifecycle FAQ](https://www.databricks.com/product/pricing/storage),
[serverless limitations](https://docs.databricks.com/aws/en/compute/serverless/limitations),
[usage and reporting delay](https://docs.databricks.com/aws/en/compute/serverless/).
