# Databricks credit and lifecycle cost review

Read-only planning, not native execution authorization. No job, table, volume,
principal, warehouse start or billing change has occurred. The owner reports
USD400 trial credits, 14 days remaining and no linked payment method.

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

The [Express trial documentation](https://docs.databricks.com/aws/en/getting-started/express-setup)
requires adding a payment method to continue after credits expire or are
exhausted. Preserve the unupgraded no-payment trial and export evidence early;
trial assets may later be deleted. This is not a final-accounting guarantee.

## Proposed envelope

| Item | Assumption/reserve | USD |
|---|---|---:|
| Job compute | Four aggregate compute-hours at assumed 50 DBU/hour, times 0.35 | 70 |
| Storage lifecycle and requests | Includes retained versions and deletion tail | 5 |
| Controlled reruns | Finite retry plan required | 20 |
| Delayed usage and uncertainty | Reserve | 25 |
| Total proposal | Not owner spending approval or a hard cap | 120 |

The assumed 50 DBU/hour is a documented possible personal-email trial limit,
not an observed/enforced account cap. Actual usage is workload-dependent. A
finite native plan must bind task count, timeout, automatic-retry behavior,
source sizes and resource ownership. Start with a small measured pilot before
scaling. Budget alerts and timeouts are not hard financial caps.

Sensitivity, **not observed consumption**: five binary GB retained for 14 trial
days plus a 30-day deletion tail cost approximately USD0.1664. Hypothetical
100,000 tier 1 requests add USD0.50002; 1,000,000 tier 2 requests add USD0.4002.
The combined USD1.0666 illustrates the storage reserve, before transfer/other
charges; it does not prove the future workload meets those byte/request bounds.

Keep the existing SQL warehouse stopped. Use bounded Spark Jobs and an isolated
namespace, without schedules or paid add-ons. Disable predictive optimization
only for the new acceptance schema before managed tables, then verify it.
Deletion and delayed usage must be checked separately from job correctness.

## Remaining gate

OAuth and management API access work. Next prepare a source-bound native pilot
with an explicit trial-credit allowance, ownership-checked teardown and an
independent observer. Restricted principal creation/run-as and actual access
denials remain unexecuted. Do not infer spending authorization from credits,
this estimate or a successful metadata preflight: the latest owner instruction
authorizes read-only feasibility and preparation.

Sources: [Jobs price list](https://www.databricks.com/product/pricing/lakeflow-jobs),
[storage rates and lifecycle FAQ](https://www.databricks.com/product/pricing/storage),
[trial limits](https://docs.databricks.com/aws/en/getting-started/free-trial),
[usage and reporting delay](https://docs.databricks.com/aws/en/compute/serverless/).
