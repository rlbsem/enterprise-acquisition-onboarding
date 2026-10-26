"""Run the annual portable application and capture actual financial/browser acceptance."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect
from verify_portable import Lane, ROOT, source_hashes, write


def browser(lane, output):
    checks, screenshots, accessibility, errors = [], [], [], []

    def check(case, expected, observed):
        assert observed == expected, (case, observed)
        checks.append(dict(case=case, expected=expected, observed=observed, passed=True))

    credential = lane.credentials("sponsor")
    with httpx.Client(base_url=lane.url, trust_env=False, headers={"Origin": lane.url}) as c:
        assert (
            c.post(
                "/console/api/login", json={k: credential[k] for k in ["username", "password"]}
            ).status_code
            == 200
        )
        original = c.get("/console/api/reports/original").json()
        restated = c.get("/console/api/reports/restated").json()
        check("twelve_reporting_months", 12, len(restated["periods"]))
        check("three_profiles", 3, len(restated["scenario"]["profiles"]))
        check(
            "held_sources_excluded",
            True,
            all(r["company"] != "summit" for r in restated["datasets"]["fct_invoices"]),
        )
        check(
            "preacquisition_visible",
            True,
            any(r["reason"] == "pre_acquisition" for r in restated["exclusions"]),
        )
        check(
            "held_exclusion_visible",
            True,
            any(r["reason"] == "admission_held" for r in restated["exclusions"]),
        )
        check(
            "late_correction_delta_minor",
            4500000,
            sum(r["consolidated_invoice_minor"] for r in restated["totals"])
            - sum(r["consolidated_invoice_minor"] for r in original["totals"]),
        )
    with sync_playwright() as p:
        chromium = p.chromium.launch()
        engine = {
            "name": "chromium",
            "version": chromium.version,
            "playwright": version("playwright"),
        }
        for viewport, label in [
            ({"width": 1500, "height": 1050}, "desktop"),
            ({"width": 390, "height": 844}, "mobile"),
        ]:
            context = chromium.new_context(viewport=viewport)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(lane.url + "/console")
            page.locator("#username").fill(credential["username"])
            page.locator("#password").fill(credential["password"])
            page.locator("button[type=submit]").click()
            expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
            expect(page.locator("#report-select")).to_have_value("restated")
            check(
                label + "_annual_context",
                True,
                "Annual source scenario" in page.locator("#main").inner_text(),
            )
            check(
                label + "_profile_assumption",
                True,
                "Assumed gross billing profile" in page.locator("#main").inner_text(),
            )
            check(
                label + "_no_page_overflow",
                True,
                page.evaluate("document.documentElement.scrollWidth<=innerWidth"),
            )
            expected = sum(r["consolidated_invoice_minor"] for r in restated["totals"])
            check(
                label + "_actual_metric",
                f"${expected / 100:,.0f}",
                page.locator("[data-metric=consolidated_invoice_minor]").inner_text(),
            )
            page.evaluate((ROOT / "tests/vendor/axe.min.js").read_text(encoding="utf-8"))
            scan = page.evaluate(
                """async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {version:r.testEngine.version,violations:r.violations.map(v=>v.id),incomplete:r.incomplete.map(v=>v.id)}}"""
            )
            assert not scan["violations"] and not scan["incomplete"], scan
            accessibility.append({"view": label + "_portfolio", **scan})

            def capture(name, route):
                observed_route = page.url.split("#", 1)[1] if "#" in page.url else "portfolio"
                assert observed_route == route
                page.evaluate("window.scrollTo(0,0)")
                target = output / name
                page.screenshot(path=str(target), full_page=True, animations="disabled")
                screenshots.append(
                    dict(
                        file=name,
                        route=route,
                        viewport=viewport,
                        publication=page.locator("#report-select").input_value(),
                        period=page.locator("#period-select").input_value(),
                        capture="real_chromium_page_screenshot",
                        observed_route=observed_route,
                        rendered_heading=page.locator("#main h1").inner_text(),
                        captured_at=datetime.now(UTC).isoformat(),
                        role="sponsor",
                        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                    )
                )

            capture("annual-" + label + ".png", "portfolio")
            page.locator("#period-select").select_option("2026-06-01")
            expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
            month_total = next(
                r["consolidated_invoice_minor"]
                for r in restated["totals"]
                if r["period"] == "2026-06-01"
            )
            expect(page.locator("[data-metric=consolidated_invoice_minor]")).to_have_text(
                f"${month_total / 100:,.0f}"
            )
            page.locator("[data-route=finance]").click()
            expect(page.locator("#main h1")).to_have_text("Financial reconciliation")
            expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
            check(
                label + "_monthly_filter",
                f"${month_total / 100:,.0f}",
                page.locator("[data-metric=consolidated_invoice_minor]").inner_text(),
            )
            capture("annual-finance-" + label + ".png", "finance")
            context.close()
        chromium.close()
    operator = lane.credentials("cedar-leader")
    with httpx.Client(base_url=lane.url, trust_env=False, headers={"Origin": lane.url}) as c:
        assert (
            c.post(
                "/console/api/login", json={k: operator[k] for k in ["username", "password"]}
            ).status_code
            == 200
        )
        scoped = c.get("/console/api/reports/restated").json()
        check("company_profile_scope", ["cedar"], list(scoped["scenario"]["profiles"]))
        check(
            "foreign_company_denied",
            403,
            c.get("/console/api/reports/restated?company=meridian").status_code,
        )
        check(
            "unpublished_candidate_denied",
            404,
            c.get("/console/api/reports/unbalanced-candidate").status_code,
        )
    check("browser_errors", [], errors)
    return dict(
        checks=checks,
        screenshots=screenshots,
        accessibility=accessibility,
        browser="actual_chromium",
        engine=engine,
        synthetic=True,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--native", action="store_true")
    a = p.parse_args()
    if a.workspace.exists() or a.output.exists():
        raise ValueError("fresh_paths_required")
    a.output.mkdir(parents=True)
    sources = source_hashes()
    report = dict(
        source_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        source_sha256=sources,
        started_at=datetime.now(UTC).isoformat(),
        lane="native_local" if a.native else "actual_docker_compose",
        native_vendor_calls=0,
        cloud_resources=False,
    )
    lane = Lane(a.workspace, a.native, scenario="annual")
    try:
        lane.start()
        financial = json.loads(lane.cli("annual-evidence"))
        write(a.output / "financial.json", financial)
        report["isolation"] = lane.isolation()
        report["browser"] = browser(lane, a.output)
        before = lane.inspect()
        assert before["receiver_posts"] == before["receiver_effects"] == 1
        report["shutdown"] = lane.stop()
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        raise
    finally:
        report["cleanup"] = lane.cleanup()
        report["finished_at"] = datetime.now(UTC).isoformat()
        assert source_hashes() == sources, "source_changed_during_verification"
        write(a.output / "annual.json", report)
        write(
            a.output / "artifact-integrity.json",
            {
                f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                for f in a.output.iterdir()
                if f.is_file() and f.name != "artifact-integrity.json"
            },
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "checks": len(report["browser"]["checks"]),
                "totals": financial["totals_after"],
            }
        )
    )


if __name__ == "__main__":
    main()
