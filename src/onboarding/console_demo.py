"""Real Chromium role/scope/review/financial acceptance with local PostgreSQL publications."""

import argparse
import json
import os
import time
from pathlib import Path
from datetime import UTC, datetime
from importlib.metadata import version
from psycopg.errors import InsufficientPrivilege
from playwright.sync_api import sync_playwright, expect
from .sandbox import Sandbox
from .financial_demo import execute as financial_execute
from .db import connect
from .fixtures import canonical

ROOT = Path(__file__).resolve().parents[2]


def browser_acceptance(stack, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".local/browsers"))
    checks = []
    roles = {}
    stage = "browser_start"

    def progress(name, diagnostic=None):
        nonlocal stage
        stage = name
        (stack.path / "browser-progress-private.json").write_text(
            json.dumps({"stage": stage, "completed_checks": len(checks), "diagnostic": diagnostic}),
            encoding="utf-8",
        )

    accessibility = []
    screens = []
    errors = []

    def check(name, expected, observed):
        assert observed == expected, (name, observed)
        checks.append({"case": name, "expected": expected, "observed": observed, "passed": True})
        progress(name)

    axe_source = (ROOT / "tests/vendor/axe.min.js").read_text(encoding="utf-8")

    def ready(page):
        expect(page.locator("#main h1")).to_be_visible()
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")

    def axe(page, name):
        progress(name)
        page.evaluate(axe_source)
        result = page.evaluate(
            """async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {version:r.testEngine.version,violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length})),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.length}))};}"""
        )
        progress(name, result)
        assert not result["violations"], (name, result)
        assert not result["incomplete"], ("unresolved_accessibility_check", name, result)
        accessibility.append({"view": name, **result})

    def screenshot(page, name, route):
        page.evaluate("window.scrollTo(0,0)")
        page.evaluate("() => new Promise(requestAnimationFrame)")
        page.screenshot(path=str(out / name), full_page=True, animations="disabled")
        screens.append(
            {
                "file": name,
                "route": route,
                "viewport": page.viewport_size,
                "capture": "real_chromium_page_screenshot",
                "synthetic": True,
                "role": roles[page],
                "full_page": True,
                "publication": page.locator("#report-select").input_value(),
                "company_scope": page.locator("#company-select").input_value(),
                "captured_at": datetime.now(UTC).isoformat(),
            }
        )

    def signin(context, user):
        page = context.new_page()
        roles[page] = stack.console_credentials[user]["role"]
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(stack.url + "/console")
        expect(page).to_have_url(stack.url + "/console/login")
        page.keyboard.press("Tab")
        check(
            "login_keyboard_username_" + user,
            "username",
            page.evaluate("document.activeElement.id"),
        )
        page.locator("#username").fill(stack.console_credentials[user]["username"])
        page.keyboard.press("Tab")
        check(
            "login_keyboard_password_" + user,
            "password",
            page.evaluate("document.activeElement.id"),
        )
        check(
            "visible_focus_" + user,
            True,
            page.evaluate("getComputedStyle(document.activeElement).outlineStyle!=='none'"),
        )
        page.locator("#password").fill(stack.console_credentials[user]["password"])
        page.keyboard.press("Enter")
        ready(page)
        return page

    def request(page, path, body=None):
        return page.evaluate(
            """async({path,body})=>{const s=await(await fetch('/console/api/session')).json();const r=await fetch('/console/api'+path,body===null?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf},body:JSON.stringify(body)});return {status:r.status,data:await r.json()};}""",
            {"path": path, "body": body},
        )

    with connect(stack.receiver_admin) as c:
        before = c.execute(
            "SELECT count(*) n FROM requests WHERE operation IN('apply','duplicate')"
        ).fetchone()["n"]
    try:
        with connect(stack.console["read_dsn"]) as c:
            c.execute("SELECT * FROM analytics.fct_invoices")
    except InsufficientPrivilege:
        denied = True
    else:
        denied = False
    check("console_reader_cannot_use_working_dbt", True, denied)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        browser_engine = {
            "name": "chromium",
            "version": browser.version,
            "playwright": version("playwright"),
        }
        contexts = []
        try:
            sponsor_context = browser.new_context(viewport={"width": 1500, "height": 1050})
            contexts.append(sponsor_context)
            sponsor = signin(sponsor_context, "sponsor")
            expect(sponsor.locator('[data-metric="consolidated_invoice_minor"]')).to_have_text(
                "$388,000"
            )
            check(
                "A_sponsor_company_scope",
                ["cedar", "meridian", "summit"],
                [r["id"] for r in request(sponsor, "/overview")["data"]["companies"]],
            )
            sponsor.select_option("#report-select", "original")
            expect(sponsor.locator('[data-metric="consolidated_invoice_minor"]')).to_have_text(
                "$368,000"
            )
            expect(sponsor.locator('[data-metric="consolidated_erp_minor"]')).to_have_text(
                "$363,000"
            )
            check(
                "E_original_invoice_usd",
                36800000,
                request(sponsor, "/reports/original")["data"]["totals"][0][
                    "consolidated_invoice_minor"
                ]
                + request(sponsor, "/reports/original")["data"]["totals"][1][
                    "consolidated_invoice_minor"
                ],
            )
            sponsor.select_option("#period-select", "2026-01-01")
            expect(sponsor.locator('[data-metric="consolidated_invoice_minor"]')).to_have_text(
                "$160,000"
            )
            check(
                "E_original_january_usd",
                "$160,000",
                sponsor.locator('[data-metric="consolidated_invoice_minor"]').inner_text(),
            )
            sponsor.select_option("#report-select", "restated")
            expect(sponsor.locator('[data-metric="consolidated_invoice_minor"]')).to_have_text(
                "$180,000"
            )
            check(
                "E_restated_january_usd",
                "$180,000",
                sponsor.locator('[data-metric="consolidated_invoice_minor"]').inner_text(),
            )
            sponsor.select_option("#period-select", "all")
            expect(sponsor.locator('[data-metric="consolidated_invoice_minor"]')).to_have_text(
                "$388,000"
            )
            expect(sponsor.locator('[data-metric="allocated_cash_minor"]')).to_have_text("$230,000")
            axe(sponsor, "sponsor_portfolio_desktop")
            screenshot(sponsor, "portfolio-desktop.png", "/console/#portfolio")
            check(
                "unpublished_candidate_hidden",
                404,
                request(sponsor, "/reports/unbalanced-candidate")["status"],
            )
            sponsor.locator('nav a[href="#finance"]').focus()
            sponsor.keyboard.press("Enter")
            ready(sponsor)
            expect(sponsor.get_by_text("$5,000", exact=True).first).to_be_visible()
            expect(sponsor.get_by_text("$8,000", exact=True).first).to_be_visible()
            result = request(sponsor, "/reports/restated")["data"]
            check(
                "F_variance_categories",
                [["erp_posting_difference", 500000], ["intercompany_unresolved", 800000]],
                sorted(
                    [
                        [r["code"], r["amount_minor"]]
                        for r in result["datasets"]["reconciliation_variances"]
                    ]
                ),
            )
            source = sponsor.locator("[data-source]").first
            source.focus()
            sponsor.keyboard.press("Enter")
            expect(sponsor.locator("#evidence-dialog")).to_be_visible()
            check(
                "source_original_body_visible",
                True,
                "financial-fact.v1" in sponsor.locator("#dialog-content").inner_text(),
            )
            sponsor.keyboard.press("Escape")
            expect(sponsor.locator("#evidence-dialog")).not_to_be_visible()
            axe(sponsor, "financial_reconciliation_desktop")
            screenshot(sponsor, "financial-desktop.png", "/console/#finance")
            sponsor.locator('nav a[href="#history"]').click()
            ready(sponsor)
            exclusions = request(sponsor, "/reports/restated")["data"]["exclusions"]
            check(
                "G_held_and_effective_exclusions",
                [["meridian", "pre_acquisition", 9000000], ["summit", "admission_held", 10000000]],
                [[r["company"], r["reason"], r["amount_minor"]] for r in exclusions],
            )
            check(
                "restatement_bridge_five_changes",
                5,
                len([r for r in result["bridge"] if r["delta_minor"]]),
            )
            axe(sponsor, "reporting_history_desktop")
            screenshot(sponsor, "history-desktop.png", "/console/#history")
            with connect(stack.dsn) as c:
                initial_decisions = c.execute("SELECT count(*) n FROM review_decisions").fetchone()[
                    "n"
                ]
            check(
                "C_sponsor_write_denied",
                403,
                request(
                    sponsor,
                    "/companies/summit/admission",
                    {"reason": "Sponsor must remain read only"},
                )["status"],
            )
            mobile_context = browser.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                device_scale_factor=1,
            )
            contexts.append(mobile_context)
            mobile = signin(mobile_context, "sponsor")
            check(
                "I_mobile_no_page_overflow",
                True,
                mobile.evaluate("document.documentElement.scrollWidth<=innerWidth"),
            )
            expect(mobile.locator('[data-metric="consolidated_invoice_minor"]')).to_have_text(
                "$388,000"
            )
            axe(mobile, "sponsor_portfolio_mobile")
            screenshot(mobile, "portfolio-mobile.png", "/console/#portfolio")
            mobile.locator('nav a[href="#finance"]').click()
            ready(mobile)
            check(
                "I_mobile_finance_no_page_overflow",
                True,
                mobile.evaluate("document.documentElement.scrollWidth<=innerWidth"),
            )
            expect(mobile.get_by_text("$5,000", exact=True).first).to_be_visible()
            axe(mobile, "financial_reconciliation_mobile")
            screenshot(mobile, "financial-mobile.png", "/console/#finance")
            operator_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            contexts.append(operator_context)
            operator = signin(operator_context, "cedar-leader")
            check(
                "B_operator_single_scope",
                ["cedar"],
                [r["id"] for r in request(operator, "/overview")["data"]["companies"]],
            )
            for path in [
                "/companies/meridian",
                "/reports/restated?company=meridian",
                "/reports/restated?company=all",
            ]:
                check("B_denied_" + path, 403, request(operator, path)["status"])
            with connect(stack.dsn) as c:
                other = c.execute(
                    "SELECT event_id FROM financial_inputs WHERE report_id='restated' AND body->>'company'='meridian' LIMIT 1"
                ).fetchone()["event_id"]
            check(
                "B_cross_company_source_denied",
                404,
                request(operator, "/reports/restated/sources/" + str(other))["status"],
            )
            scoped = request(operator, "/reports/restated")["data"]
            check(
                "B_scoped_financial_rows",
                True,
                all(
                    row["company"] == "cedar"
                    for rows in scoped["datasets"].values()
                    for row in rows
                ),
            )
            check(
                "C_operator_write_denied",
                403,
                request(
                    operator, "/companies/cedar/admission", {"reason": "Operator cannot approve"}
                )["status"],
            )
            operator.locator('nav a[href="#company"]').click()
            ready(operator)
            expect(operator.get_by_text("confirmed", exact=True)).to_be_visible()
            check(
                "recorded_recovery_visible",
                True,
                operator.get_by_text("confirmed", exact=True).is_visible(),
            )
            axe(operator, "operating_company_desktop")
            screenshot(operator, "company-desktop.png", "/console/#company")
            reviewer_context = browser.new_context(viewport={"width": 1440, "height": 1100})
            contexts.append(reviewer_context)
            reviewer = signin(reviewer_context, "reviewer")
            check(
                "reviewer_other_company_denied",
                403,
                request(reviewer, "/companies/cedar")["status"],
            )
            no_csrf = reviewer.evaluate(
                """async()=>{const r=await fetch('/console/api/companies/summit/admission',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'Missing CSRF'})});return r.status;}"""
            )
            check("reviewer_missing_csrf_denied", 403, no_csrf)
            with connect(stack.dsn) as c:
                check(
                    "C_denials_no_decisions",
                    initial_decisions,
                    c.execute("SELECT count(*) n FROM review_decisions").fetchone()["n"],
                )

            def identity_proposal(reason):
                reviewer.select_option("#candidate", canonical("summit"))
                reviewer.fill("#identity-reason", reason)
                reviewer.get_by_role("button", name="Create identity proposal", exact=True).click()
                expect(reviewer.locator(".decision-form")).to_have_count(1)
                return reviewer.locator(".decision-form").get_attribute("data-review")

            first = identity_proposal(
                "Original references require explicit rejection before a fresh scoped review."
            )
            form = reviewer.locator(".decision-form")
            form.locator('select[name="result"]').select_option("rejected")
            form.locator('input[name="reason"]').fill(
                "Reject this proposal; preserve the original evidence."
            )
            form.get_by_role("button", name="Record decision", exact=True).click()
            expect(reviewer.locator(".decision-form")).to_have_count(0)
            check(
                "rejected_decision_cannot_be_overwritten",
                409,
                request(
                    reviewer,
                    f"/companies/summit/reviews/{first}/decision",
                    {"result": "approved", "reason": "Rejected decisions are immutable"},
                )["status"],
            )
            second = identity_proposal(
                "Reviewed source references select the existing scoped customer without merging accounts."
            )
            form = reviewer.locator(".decision-form")
            form.locator('select[name="result"]').select_option("approved")
            form.locator('input[name="reason"]').fill(
                "Approve only the exact scoped candidate and current source revision."
            )
            form.get_by_role("button", name="Record decision", exact=True).click()
            expect(reviewer.locator("#identity-form")).to_have_count(0)
            reviewer.fill(
                "#admission-reason",
                "Reconcile current scoped source coverage after identity review.",
            )
            reviewer.get_by_role("button", name="Recompute admission", exact=True).click()
            expect(reviewer.locator("#status")).to_contain_text("Admission recomputed")
            check(
                "D_identity_admission_passed",
                True,
                request(reviewer, "/companies/summit")["data"]["company"]["admitted"],
            )
            reviewer.get_by_text("Open mapping proposal editor", exact=True).click()
            reviewer.get_by_role("button", name="Preview exact source coverage", exact=True).click()
            expect(reviewer.locator("#status")).to_contain_text("coverage previewed")
            reviewer.fill(
                "#mapping-reason",
                "Reconfirm exact current coverage as an explicit reviewed mapping resnapshot.",
            )
            reviewer.get_by_role("button", name="Create mapping proposal", exact=True).click()
            expect(reviewer.locator(".decision-form")).to_have_count(1)
            mapping_id = reviewer.locator(".decision-form").get_attribute("data-review")
            form = reviewer.locator(".decision-form")
            form.locator('select[name="result"]').select_option("approved")
            form.locator('input[name="reason"]').fill(
                "Activate the exact reviewed version and preserve previous mappings."
            )
            form.get_by_role("button", name="Record decision", exact=True).click()
            expect(reviewer.locator(".decision-form")).to_have_count(0)
            reviewer.fill(
                "#admission-reason",
                "Recompute readiness after controlled mapping version activation.",
            )
            reviewer.get_by_role("button", name="Recompute admission", exact=True).click()
            expect(reviewer.locator("#status")).to_contain_text("Admission recomputed")
            current = request(reviewer, "/companies/summit")["data"]
            check("D_mapping_version_activated", 2, current["company"]["active_mapping"])
            check("D_current_admission_passed", True, current["company"]["admitted"])
            check("original_customers_not_merged", 2, len(current["governance"]["customers"]))
            check(
                "original_quarantine_retained",
                True,
                all(q["resolution"] for q in current["governance"]["quarantine"]),
            )
            axe(reviewer, "authorized_review_desktop")
            screenshot(reviewer, "governance-desktop.png", "/console/#governance")
            check(
                "historical_held_scope_remains",
                False,
                request(reviewer, "/reports/restated")["data"]["control"]["summit"]["admitted"],
            )
            check(
                "E_publication_unchanged_after_review",
                38800000,
                sum(
                    r["consolidated_invoice_minor"]
                    for r in request(sponsor, "/reports/restated")["data"]["totals"]
                ),
            )
            with connect(stack.dsn) as c:
                decisions = c.execute(
                    "SELECT * FROM review_decisions WHERE company='summit' ORDER BY decided_at"
                ).fetchall()
                audits = c.execute(
                    "SELECT * FROM audit WHERE company='summit' AND action IN('identity_proposed','review_rejected','review_approved','console_admission_requested') ORDER BY id"
                ).fetchall()
                check(
                    "D_actor_bound_to_session",
                    True,
                    all(d["actor"] == "acquisition-reviewer" for d in decisions),
                )
                check(
                    "D_actual_decision_results",
                    ["rejected", "approved", "approved"],
                    [d["result"] for d in decisions],
                )
                check(
                    "validated_publications_remain_two",
                    2,
                    c.execute("SELECT count(*) n FROM financial_publications").fetchone()["n"],
                )
            # Expire an actual browser session independently in PostgreSQL.
            with connect(stack.admin_dsn) as c:
                c.execute(
                    "UPDATE console_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE actor='cedar-leader'"
                )
            operator.goto(stack.url + "/console")
            expect(operator).to_have_url(stack.url + "/console/login")
            check(
                "session_expiration_browser_redirect", True, operator.url.endswith("/console/login")
            )
            sponsor.get_by_role("button", name="Sign out", exact=True).click()
            expect(sponsor).to_have_url(stack.url + "/console/login")
            check(
                "logout_revokes_browser_session",
                401,
                sponsor.evaluate("async()=> (await fetch('/console/api/overview')).status"),
            )
            check("browser_uncaught_errors", [], errors)
        finally:
            for context in contexts:
                context.close()
            browser.close()
    with connect(stack.receiver_admin) as c:
        after = c.execute(
            "SELECT count(*) n FROM requests WHERE operation IN('apply','duplicate')"
        ).fetchone()["n"]
        effects = c.execute("SELECT count(*) n FROM effects").fetchone()["n"]
    check("H_no_new_business_posts", before, after)
    check("H_receiver_effects", 1, effects)
    return {
        "lane": "real_chromium_authenticated_local_postgresql_http",
        "browser": browser_engine,
        "synthetic": True,
        "checks": checks,
        "accessibility": accessibility,
        "screenshots": screens,
        "review_ids": {
            "rejected_identity": first,
            "approved_identity": second,
            "approved_mapping": mapping_id,
        },
        "review_decisions": decisions,
        "audit": audits,
        "downstream_posts_before": before,
        "downstream_posts_after": after,
        "receiver_effects": effects,
        "native_vendor_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output")
    parser.add_argument("--serve", action="store_true")
    a = parser.parse_args()
    if not a.serve and not a.output:
        parser.error("--output or --serve is required")
    if a.output and Path(a.output).exists():
        raise ValueError("fresh_output_required")
    with Sandbox(a.workspace) as stack:
        financial = financial_execute(stack, Path(a.workspace) / "financial")
        if a.serve:
            print(
                json.dumps(
                    {
                        "url": stack.url + "/console",
                        "private_credentials": str(stack.path / "console-credentials-private.json"),
                        "scope": "local synthetic only",
                    }
                ),
                flush=True,
            )
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            return
        out = Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        result = browser_acceptance(stack, out.parent)
        result["financial_execution"] = {
            name: {"dbt": financial[name]["dbt"], "comparisons": financial[name]["comparisons"]}
            for name in ["original", "restated"]
        }
        result["financial_publication_checks"] = {
            k: financial[k] for k in ["totals_before", "totals_after", "original_report_unchanged"]
        }
    result["owned_resources_cleaned"] = True
    out.write_bytes((json.dumps(result, indent=2, default=str) + "\n").encode())
    print(
        json.dumps(
            {
                "browser_checks": len(result["checks"]),
                "accessibility_views": len(result["accessibility"]),
                "screenshots": len(result["screenshots"]),
                "downstream_posts": result["downstream_posts_after"],
            }
        )
    )


if __name__ == "__main__":
    main()
