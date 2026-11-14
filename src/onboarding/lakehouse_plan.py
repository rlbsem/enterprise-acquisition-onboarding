"""Frozen synthetic exports and independent expected results for native Delta acceptance."""

import hashlib
import json
import re
from decimal import Decimal

from .portfolio_fixtures import Portfolio, ORIGINAL, RESTATED, PERIODS
from .portfolio_oracle import calculate


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def namespace(value):
    if not re.fullmatch(r"acq_lh_[a-z0-9]{8,28}", value):
        raise ValueError("isolated_namespace_required")
    return "workspace." + value


def export_fixture(count=3):
    p = Portfolio(count)
    baseline, corrections = p.financial(), p.corrections()
    admitted = {c[0]: p.expected_admitted(i, recovered=True) for i, c in enumerate(p.companies)}
    expected = {}
    for label, cutoff in [("original", ORIGINAL), ("restated", RESTATED)]:
        oracle = calculate(
            [{"body": b} for b in baseline + corrections], cutoff, p.companies, admitted, PERIODS
        )
        expected[label] = {
            "legal": sorted(oracle["legal"], key=lambda r: (r["company"], r["period"])),
            "totals": sorted(oracle["totals"], key=lambda r: r["period"]),
            "variances": sorted([list(v) for v in oracle["variances"]]),
        }
    controls = []
    for i, (company, _, entity, acquired, _) in enumerate(p.companies):
        rules = p.contract(i)["sources"]
        controls.append(
            dict(
                company=company,
                legal_entity=entity,
                acquired_on=acquired,
                admitted=admitted[company],
                mapping_version=p.version(i),
                crm=next(s for s, r in rules.items() if r["domain"] == "crm"),
                finance=next(s for s, r in rules.items() if r["domain"] == "finance"),
            )
        )
    return dict(
        contract="governed-lakehouse.v1",
        synthetic=True,
        currency="USD",
        control_boundary="frozen synthetic expected admission; not live PostgreSQL authorization",
        company_count=count,
        controls=controls,
        baseline=baseline,
        corrections=corrections,
        periods=PERIODS,
        cutoffs={"original": ORIGINAL, "restated": RESTATED},
        expected=expected,
    )


def job_spec(path, schema, phase, revision, fixture_hash, seconds=900):
    namespace(schema)
    if phase not in {
        "pilot",
        "fault",
        "recovery",
        "postcheck",
        "observer",
        "governance",
        "scale",
        "cleanup",
    }:
        raise ValueError("unknown_native_phase")
    if not re.fullmatch("[0-9a-f]{40}", revision) or not re.fullmatch("[0-9a-f]{64}", fixture_hash):
        raise ValueError("exact_source_binding_required")
    if not path.startswith("/Shared/acquisition-lakehouse/") or ".." in path:
        raise ValueError("isolated_notebook_path_required")
    if type(seconds) is not int or not 60 <= seconds <= 900:
        raise ValueError("bounded_task_timeout_required")
    return dict(
        run_name=f"{schema}-{phase}",
        timeout_seconds=seconds,
        performance_target="STANDARD",
        tasks=[
            dict(
                task_key=phase,
                timeout_seconds=seconds,
                max_retries=0,
                retry_on_timeout=False,
                disable_auto_optimization=True,
                notebook_task=dict(
                    notebook_path=path,
                    source="WORKSPACE",
                    base_parameters=dict(
                        schema=schema,
                        phase=phase,
                        revision=revision,
                        fixture_hash=fixture_hash,
                    ),
                ),
            )
        ],
    )


def credit_projection(compute_seconds, dbu_per_hour="50", rate="0.35", reserve="2"):
    """Conservative planning only; neither DBU rate nor a timeout is a financial cap."""
    values = [Decimal(str(x)) for x in [compute_seconds, dbu_per_hour, rate, reserve]]
    if any(not x.is_finite() or x < 0 for x in values):
        raise ValueError("finite_nonnegative_cost_inputs_required")
    return str(values[0] / Decimal(3600) * values[1] * values[2] + values[3])


def admit_credit_step(ledger, proposed_reserve, *, expansion=False):
    """Pending exposure is additive; an empty delayed report is not zero cost."""
    amounts = [
        Decimal(str(ledger[k]))
        for k in ["observed_usd", "pending_reserved_usd", "cleanup_reserved_usd"]
    ]
    amounts.append(Decimal(str(proposed_reserve)))
    reruns = Decimal(str(ledger.get("controlled_rerun_reserved_usd", "0")))
    if any(not v.is_finite() or v < 0 for v in [*amounts, reruns]):
        raise ValueError("invalid_credit_observation")
    if reruns > 20 or sum(amounts) + reruns > 300:
        raise ValueError("controlled_rerun_or_total_allowance_exceeded")
    limit = Decimal("300" if expansion else "20")
    if expansion and (
        not ledger.get("pilot_accepted")
        or not ledger.get("actual_usage_observed")
        or not ledger.get("applicable_rate_verified")
    ):
        raise ValueError("measured_pilot_required_before_expansion")
    if sum(amounts) + (reruns if expansion else 0) > limit:
        raise ValueError("pending_or_projected_exposure_exceeds_allowance")
    return str(sum(amounts) + reruns)


def reserve_completed_duration(ledger, run_id, milliseconds):
    """Replace timeout exposure with a padded wall-time estimate, never a bill claim."""
    if type(milliseconds) is not int or milliseconds <= 0:
        raise ValueError("positive_observed_duration_required")
    for entry in ledger.get("submissions", []):
        if entry["run_id"] != run_id or entry.get("observed_wall_time_ms") is not None:
            continue
        amount = max(
            Decimal("0.25"),
            Decimal(
                credit_projection(Decimal(milliseconds) / 1000, dbu_per_hour="75", reserve="0")
            ),
        )
        field = (
            "controlled_rerun_reserved_usd"
            if entry.get("budget_bucket") == "controlled_rerun"
            else "pending_reserved_usd"
        )
        ledger[field] = str(
            Decimal(str(ledger.get(field, "0"))) - Decimal(str(entry["reserved_usd"])) + amount
        )
        entry.update(
            reserved_usd=str(amount),
            observed_wall_time_ms=milliseconds,
            estimate_basis="observed entire wall time times 75 DBU/hour times USD0.35; pending estimate, not measured billing",
        )
    return ledger
