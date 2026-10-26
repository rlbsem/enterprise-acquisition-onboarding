import hashlib
import httpx
import psycopg
import pytest
from onboarding.console import COOKIE
from onboarding.db import connect


def login(stack, user="sponsor"):
    client = httpx.Client(base_url=stack.url, trust_env=False)
    response = client.post(
        "/console/api/login",
        headers={"Origin": stack.url},
        json={k: stack.console_credentials[user][k] for k in ["username", "password"]},
    )
    assert response.status_code == 200
    return client, response.json()["csrf"]


def test_console_session_required_and_api_tokens_are_not_browser_sessions(stack):
    with stack.client("viewer") as c:
        for path in [
            "/console/api/session",
            "/console/api/overview",
            "/console/api/companies/cedar",
            "/console/api/reports/original",
        ]:
            assert c.get(path).status_code == 401
        assert c.get("/console", follow_redirects=False).status_code == 303


def test_opaque_expiring_session_cookie_and_logout(stack):
    c, csrf = login(stack)
    try:
        assert c.get("/console/api/session").json()["role"] == "sponsor"
        token = c.cookies.get(COOKIE)
        with connect(stack.console["auth_dsn"]) as db:
            row = db.execute("SELECT * FROM console_sessions").fetchone()
            assert row["session_hash"] == hashlib.sha256(
                token.encode()
            ).hexdigest() and token not in str(row)
        assert (
            c.post(
                "/console/api/logout", headers={"Origin": stack.url, "X-CSRF-Token": csrf}, json={}
            ).status_code
            == 200
        )
        assert c.get("/console/api/overview").status_code == 401
    finally:
        c.close()


def test_expired_session_is_rejected_server_side(stack):
    c, _ = login(stack)
    try:
        with connect(stack.admin_dsn) as db:
            db.execute(
                "UPDATE console_sessions SET expires_at=clock_timestamp()-interval '1 second'"
            )
        assert c.get("/console/api/overview").status_code == 401
    finally:
        c.close()


def test_browser_tenant_scope_is_enforced_on_every_target(stack):
    c, csrf = login(stack, "cedar-leader")
    try:
        assert [r["id"] for r in c.get("/console/api/overview").json()["companies"]] == ["cedar"]
        assert c.get("/console/api/companies/cedar").status_code == 200
        assert c.get("/console/api/companies/meridian").status_code == 403
        for value in ["meridian", "all"]:
            assert (
                c.get("/console/api/reports/original", params={"company": value}).status_code == 403
            )
        assert c.post(
            "/console/api/companies/cedar/admission",
            headers={"Origin": stack.url, "X-CSRF-Token": csrf},
            json={"reason": "forged browser role", "role": "reviewer"},
        ).status_code in [403, 422]
    finally:
        c.close()


def test_browser_review_requires_role_csrf_origin_and_scope(stack):
    c, csrf = login(stack, "reviewer")
    try:
        path = "/console/api/companies/summit/admission"
        body = {"reason": "reviewed request"}
        assert c.post(path, headers={"Origin": stack.url}, json=body).status_code == 403
        assert (
            c.post(
                path,
                headers={"Origin": "https://untrusted.invalid", "X-CSRF-Token": csrf},
                json=body,
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/console/api/companies/cedar/admission",
                headers={"Origin": stack.url, "X-CSRF-Token": csrf},
                json=body,
            ).status_code
            == 403
        )
        assert c.get("/console/api/companies/cedar").status_code == 403
        with connect(stack.dsn) as db:
            assert db.execute("SELECT count(*) n FROM review_decisions").fetchone()["n"] == 0
    finally:
        c.close()
    c, csrf = login(stack)
    try:
        assert (
            c.post(path, headers={"Origin": stack.url, "X-CSRF-Token": csrf}, json=body).status_code
            == 403
        )
    finally:
        c.close()


def test_local_login_origin_throttle_and_security_headers(stack):
    with httpx.Client(base_url=stack.url, trust_env=False) as c:
        assert (
            c.post(
                "/console/api/login", json={"username": "sponsor", "password": "wrong"}
            ).status_code
            == 403
        )
        for _ in range(5):
            assert (
                c.post(
                    "/console/api/login",
                    headers={"Origin": stack.url},
                    json={"username": "unknown", "password": "wrong"},
                ).status_code
                == 401
            )
        assert (
            c.post(
                "/console/api/login",
                headers={"Origin": stack.url},
                json={"username": "unknown", "password": "wrong"},
            ).status_code
            == 429
        )
        response = c.get("/console/login")
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["Cache-Control"] == "no-store"
        assert c.get("/console/api/overview", headers={"Host": "evil.invalid"}).status_code == 400
    c, _ = login(stack)
    try:
        response = c.get("/console/api/session")
        assert response.status_code == 200
        # Check the actual login cookie flags without exporting the credential.
        item = next(iter(c.cookies.jar))
        assert (
            item.has_nonstandard_attr("HttpOnly")
            and item.get_nonstandard_attr("SameSite") == "strict"
        )
    finally:
        c.close()


def test_console_sql_roles_cannot_change_controls_or_read_sessions(stack):
    for dsn, query in [
        (stack.console["read_dsn"], "UPDATE companies SET status='portfolio_ready'"),
        (stack.console["read_dsn"], "SELECT * FROM console_sessions"),
        (stack.console["auth_dsn"], "SELECT * FROM financial_publications"),
        (stack.dsn, "SELECT * FROM console_sessions"),
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connect(dsn) as c:
                c.execute(query)
