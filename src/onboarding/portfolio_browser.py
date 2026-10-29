"""Genuine desktop/mobile inspection of the existing console with the larger portfolio."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from importlib.metadata import version
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def capture(stack, spec, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    credential = stack.console_credentials["sponsor"]
    checks, scans, screens, errors = [], [], [], []

    def check(name, observed, expected):
        assert observed == expected, (name, observed, expected)
        checks.append(dict(case=name, observed=observed, expected=expected, passed=True))

    def ready(page, heading=None):
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
        if heading:
            expect(page.locator("#main h1")).to_have_text(heading)

    def axe(page, name):
        page.evaluate((ROOT / "tests/vendor/axe.min.js").read_text(encoding="utf-8"))
        scan = page.evaluate(
            """async()=>{let r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {version:r.testEngine.version,violations:r.violations.map(v=>v.id),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,obscured:n.any.length>0&&n.any.every(a=>a.data?.messageKey==='elmPartiallyObscured')}))}))}}"""
        )
        follow = []
        for rule in scan["incomplete"]:
            assert rule["id"] == "color-contrast"
            for node in rule["nodes"]:
                assert node["obscured"] and len(node["target"]) == 1
                selector = node["target"][0]
                page.locator(selector).evaluate(
                    "e=>e.scrollIntoView({block:'center',inline:'center'})"
                )
                observed = page.evaluate(
                    """async(s)=>{let r=await axe.run({include:[[s]]},{runOnly:{type:'rule',values:['color-contrast']}});return {violations:r.violations.length,incomplete:r.incomplete.length,explicit_pass:r.passes.some(v=>v.id==='color-contrast'&&v.nodes.some(n=>n.target[0]===s))}}""",
                    selector,
                )
                assert observed == dict(violations=0, incomplete=0, explicit_pass=True)
                follow.append(dict(target=selector, **observed))
        assert not scan["violations"]
        scans.append(dict(view=name, **scan, scroll_checks=follow, unresolved_checks=0))
        page.evaluate(
            "document.querySelectorAll('.table-wrap').forEach(e=>e.scrollLeft=0);window.scrollTo(0,0)"
        )

    with httpx.Client(base_url=stack.url, headers={"Origin": stack.url}, trust_env=False) as client:
        assert (
            client.post(
                "/console/api/login",
                json={"username": "sponsor", "password": credential["password"]},
            ).status_code
            == 200
        )
        report = client.get("/console/api/reports/restated").json()
        original = client.get("/console/api/reports/original").json()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        engine = dict(name="Chromium", version=browser.version, playwright=version("playwright"))
        for viewport, label in [
            (dict(width=1500, height=1050), "desktop"),
            (dict(width=390, height=844), "mobile"),
        ]:
            context = browser.new_context(viewport=viewport)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(stack.url + "/console")
            page.locator("#username").fill("sponsor")
            page.locator("#password").fill(credential["password"])
            page.locator("button[type=submit]").click()
            ready(page, "Which acquisitions are ready to report?")
            check(
                label + "_company_count",
                page.locator("#company-select option").count(),
                spec.count + 1,
            )
            check(
                label + "_actual_financial_metric",
                page.locator("[data-metric=consolidated_invoice_minor]").inner_text(),
                f"${sum(r['consolidated_invoice_minor'] for r in report['totals']) / 100:,.0f}",
            )
            for state in ["held", "pending", "admitted"]:
                page.locator("#admission-filter").select_option(state)
                expected = sum(
                    (
                        (
                            "admitted"
                            if spec.expected_admitted(i, True)
                            else "pending"
                            if spec.mode(i) == "pending_review"
                            else "held"
                        )
                        == state
                    )
                    for i in range(spec.count)
                )
                check(
                    label + "_" + state + "_filter",
                    page.locator("#company-table button[data-company]").count(),
                    expected,
                )
            page.locator("#admission-filter").select_option("all")
            page.locator("#company-query").fill(spec.companies[2][2])
            check(
                label + "_entity_search",
                page.locator("#company-table button[data-company]").count(),
                1,
            )
            page.locator("#company-query").fill("")
            page.locator("#admission-filter").select_option("held")
            axe(page, label + "_portfolio")
            check(
                label + "_page_no_overflow",
                page.evaluate("document.documentElement.scrollWidth<=innerWidth"),
                True,
            )

            def screenshot(view, route):
                observed = page.url.split("#", 1)[1] if "#" in page.url else "portfolio"
                assert observed == route
                page.evaluate("window.scrollTo(0,0)")
                name = label + "-" + view + ".png"
                page.screenshot(path=str(output / name), full_page=False, animations="disabled")
                screens.append(
                    dict(
                        file=name,
                        sha256=hashlib.sha256((output / name).read_bytes()).hexdigest(),
                        captured_at=datetime.now(UTC).isoformat(),
                        viewport=viewport,
                        route=route,
                        publication=page.locator("#report-select").input_value(),
                        company=page.locator("#company-select").input_value(),
                        admission_filter=page.locator("#admission-filter").input_value()
                        if route == "portfolio"
                        else None,
                        capture="real_browser_viewport_no_image_editing",
                    )
                )

            screenshot("portfolio", "portfolio")
            page.locator("#report-select").select_option("original")
            ready(page)
            expect(page.locator("[data-metric=consolidated_invoice_minor]")).to_have_text(
                f"${sum(r['consolidated_invoice_minor'] for r in original['totals']) / 100:,.0f}"
            )
            page.locator("#company-select").select_option(spec.companies[0][0])
            page.locator("nav a[data-route=company]").click()
            ready(page, spec.companies[0][1])
            check(
                label + "_current_vs_historical_admission",
                "captured held" in page.locator("#main .notice").inner_text(),
                True,
            )
            axe(page, label + "_company")
            screenshot("company", "company")
            page.locator("#company-select").select_option("all")
            page.locator("#report-select").select_option("restated")
            page.locator("nav a[data-route=finance]").click()
            ready(page, "Financial reconciliation")
            axe(page, label + "_finance")
            screenshot("finance", "finance")
            context.close()
        browser.close()
    assert not errors
    result = dict(
        browser=engine,
        checks=checks,
        accessibility=scans,
        screenshots=screens,
        script_errors=errors,
        synthetic=True,
        native_vendor_calls=0,
    )
    (output / "browser.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
    return result
