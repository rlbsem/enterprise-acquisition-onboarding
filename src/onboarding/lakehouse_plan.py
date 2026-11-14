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
    if phase not in {"pilot", "recovery", "observer", "governance", "scale", "cleanup"}:
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
