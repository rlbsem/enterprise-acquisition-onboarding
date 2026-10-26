# Two scenarios, one financial control layer

The default selected-period correctness fixture covers January, February and October 2026. Its USD $550,000 of bookings is a finite source example, not annual portfolio revenue. Its financial outputs, governance and archived Pass 1–5 evidence remain unchanged.

The optional annual scenario uses the same Cedar, Meridian and Summit companies, source owners, scoped customer identities, acquisition dates, restricted SQL roles and publication contracts. It represents a complete synthetic January–December 2026 source year, with synthetic knowledge cutoffs in January 2027. These are scenario dates, not claims of actual future business activity.

## Business context and assumptions

A larger PE-backed services platform may contain 50+ brands with individual annual operating profiles of approximately $5M–$20M. That is illustrative architectural context. This repository models three representative companies, not fifty brands or a client deployment.

| Representative company | Assumed annual gross billing profile | Reporting boundary |
|---|---:|---|
| Cedar Services | USD $8.4M | Admitted; acquired June 2025 |
| Meridian Facilities | USD $12.6M | Admitted; January 2026 is pre-acquisition |
| Summit Operator | USD $6.3M | Held; finance observations retained but excluded; CRM bookings rejected because identity is unresolved |

These profiles illustrate revenue-scale business context through **gross billing assumptions**, not recognized revenue. Seasonal weights generate twelve monthly anchor-contract bundles per company. Each bundle has distinct source-owned commercial bookings, invoice header/lines, credits, postings, payments and allocations. Monthly documents compress the example; they are not a customer census or a production transaction-volume benchmark.

The reported financial measures are independently calculated at document, posting and allocation grains. They differ from the assumed profiles, from one another and from the full underlying source year because credits, intercompany documents, collection schedules, acquisition dates and admission apply. No total is produced by scaling the earlier correctness fixture.

## Calculated results

All amounts below are synthetic USD. They describe the admitted, post-acquisition reporting perimeter, not all underlying company activity or recognized revenue.

| Measure | Original | Restated |
|---|---:|---:|
| Commercial bookings | $22,421,280.00 | $22,421,280.00 |
| Net invoices before supported elimination | $20,132,260.00 | $20,177,260.00 |
| ERP postings before supported elimination | $20,107,260.00 | $20,152,260.00 |
| Supported elimination | $120,000.00 | $120,000.00 |
| Consolidated net invoicing | $20,012,260.00 | $20,057,260.00 |
| Consolidated ERP postings | $19,987,260.00 | $20,032,260.00 |
| Allocated cash | $15,609,585.60 | $15,609,585.60 |

Cards use the existing whole-dollar display rounding; source facts, API values, comparisons and the evidence preserve integer cents. The $25,000 ERP posting difference and $40,000 unsupported intercompany candidate are distinct open exceptions, not a combined accounting loss.

The generator submits **333 base source records**. **321 are accepted**; Summit's 12 CRM bookings are rejected because their identity has not been reviewed. Its accepted finance observations remain held. The complete run records **340 source events**, including three rejected negative probes, three accepted correction revisions and one accepted but unbalanced candidate revision. Duplicate replay creates no new financial event. The original snapshot contains 321 latest source records; 96 held and nine pre-acquisition source rows are excluded from reporting. A zero accepted-booking control for Summit means no authorized booking source, not zero underlying business.

## Launch and inspect

Stop the default demo first if it is using port 8592. Run the annual scenario in its own Compose project:

```text
docker compose -p acquisition-annual -f compose.yaml -f compose.annual.yaml up --build
```

Wait for `ready`, open **http://127.0.0.1:8592/console**, and retrieve fresh private credentials in another terminal:

```text
docker compose -p acquisition-annual -f compose.yaml -f compose.annual.yaml exec demo python -m onboarding.portable credentials --user sponsor
```

1. Read the sponsor scenario card: assumptions and reportable scope are separate.
2. Compare the three company rows: Meridian has an acquisition cutoff and Summit remains held.
3. Compare Original and Restated, then select June in Financial reconciliation to inspect the unsupported intercompany candidate and its source records. Select March for the ERP posting difference.
4. Open Reporting history and source drilldowns. A late May correction restates only a new publication; the original source snapshot survives. An unbalanced candidate fails real dbt tests and cannot publish.
5. Use `cedar-leader` instead of `sponsor` to verify company scope. Browser use makes no downstream business writes.

```text
docker compose -p acquisition-annual -f compose.yaml -f compose.annual.yaml down --volumes --remove-orphans
```

The [portable security boundary](portable-demo.md) is unchanged. Neither scenario uses vendor credentials, cloud resources, recognized-revenue accounting or real commercial outcomes.

## Reproduce annual acceptance

With the locked Python dependencies and Playwright Chromium installed on the host:

```text
python scripts/verify_annual.py --workspace .local/annual-review --output .local/annual-review-evidence
python scripts/check_annual_evidence.py .local/annual-review-evidence
```

The default lane executes the actual Compose image and tests it from a host browser. `--native` uses the existing local PostgreSQL/loopback fallback and does not establish container isolation. Each run records source events, exact implementation hashes, dbt nodes, independent oracle comparisons, negative observations, actual rendered screenshots and cleanup.

[Recorded execution, source lineage and desktop/mobile screenshots](evidence/annual/README.md).
