import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import yaml

from onboarding.portable import current, private_json, serve, state_lock
from onboarding.portable_gateway import Gateway, MAX_BODY


@pytest.fixture
def gateway():
    received = []

    class Echo(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.do_POST()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append(
                {"path": self.path, "headers": dict(self.headers), "body": body.decode()}
            )
            out = json.dumps(received[-1]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.send_header(
                "Set-Cookie",
                "acquisition_session=synthetic; HttpOnly; SameSite=Strict; Path=/console",
            )
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(out)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    ready = threading.Event()
    ready.set()
    server = Gateway(("127.0.0.1", 0), upstream.server_address, ready)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in [upstream, server]]
    for t in threads:
        t.start()
    with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as client:
        yield client, received, ready, server.server_port
    for s in [server, upstream]:
        s.shutdown()
        s.server_close()
    for t in threads:
        t.join(timeout=5)


def test_gateway_preserves_browser_authority_and_response_controls(gateway):
    client, received, _, port = gateway
    r = client.post(
        "/console/api/review",
        json={"reason": "synthetic"},
        headers={
            "Origin": f"http://127.0.0.1:{port}",
            "X-CSRF-Token": "fixture-csrf",
            "Cookie": "acquisition_session=fixture-session",
            "X-Admission-Token": "must-not-forward",
            "Authorization": "must-not-forward",
            "X-Forwarded-Host": "attacker.example",
        },
    )
    assert r.status_code == 200
    headers = {k.lower(): v for k, v in received[0]["headers"].items()}
    assert headers["host"] == f"127.0.0.1:{port}"
    assert headers["origin"] == f"http://127.0.0.1:{port}"
    assert headers["x-csrf-token"] == "fixture-csrf"
    assert headers["cookie"] == "acquisition_session=fixture-session"
    assert not any(k in headers for k in ["authorization", "x-admission-token", "x-forwarded-host"])
    assert r.headers["content-security-policy"] == "default-src 'none'"
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=Strict" in r.headers["set-cookie"]


@pytest.mark.parametrize(
    "path", ["/ingest", "/dispatch", "/api/config", "/receiver", "/openapi.json"]
)
def test_gateway_never_exposes_nonconsole_services(gateway, path):
    client, received, *_ = gateway
    assert client.post(path, json={}).status_code == 404
    assert received == []


def test_gateway_denies_host_rebinding_and_path_escape(gateway):
    client, received, *_ = gateway
    assert client.get("/console", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/console/%2e%2e/ingest").status_code == 400
    assert client.get("/console", headers={"Host": "localhost/path"}).status_code == 400
    assert received == []


def test_gateway_rejects_ambiguous_framing_and_large_bodies(gateway):
    _, received, _, port = gateway
    for headers in [
        [("Content-Length", "0"), ("Content-Length", "1")],
        [("Transfer-Encoding", "chunked")],
        [("Content-Length", str(MAX_BODY + 1))],
    ]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.putrequest("POST", "/console/api/login")
        for k, v in headers:
            connection.putheader(k, v)
        connection.endheaders()
        assert connection.getresponse().status == 413
        connection.close()
    assert received == []


def test_gateway_readiness_fails_closed(gateway):
    client, received, ready, _ = gateway
    assert client.get("/health").status_code == 200
    ready.clear()
    assert client.get("/health").status_code == 503
    assert client.get("/console").status_code == 503
    assert received == []


def test_state_lock_and_pointer_cannot_attach_other_workspace(tmp_path):
    state = tmp_path / "owned"
    with state_lock(state):
        private_json(state / "ready-private.json", {"run": "../foreign"})
        with pytest.raises(ValueError, match="already_in_use"):
            with state_lock(state):
                pass
        assert (state / "ready-private.json").exists()
    with pytest.raises(ValueError, match="invalid_owned_run"):
        current(state)
    with state_lock(state):
        pass


def test_portable_refuses_external_database_before_start(monkeypatch, tmp_path):
    monkeypatch.setenv("ONBOARDING_TEST_ADMIN_DSN", "must-not-be-used")
    with pytest.raises(ValueError, match="refuses_external_runtime"):
        serve(tmp_path / "unused", 0)
    assert not (tmp_path / "unused").exists()


def test_compose_boundary_and_build_context_are_explicit():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    service = compose["services"]["demo"]
    assert len(compose["services"]) == 1
    assert service["ports"] == ["127.0.0.1:${ACQUISITION_DEMO_PORT:-8592}:8080"]
    assert service["user"] == "10001:10001" and service["read_only"]
    assert service["cap_drop"] == ["ALL"]
    network = compose["networks"]["default"]
    assert network["driver"] == "bridge"
    assert network["driver_opts"]["com.docker.network.bridge.host_binding_ipv4"] == "127.0.0.1"
    assert network["driver_opts"]["com.docker.network.bridge.enable_icc"] == "false"
    assert service["restart"] == "no" and "network_mode" not in service
    assert "**\n!Dockerfile" in (root / ".dockerignore").read_text()
