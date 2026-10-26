"""Bounded console-only gateway; internal APIs and receiver stay on loopback."""

import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

MAX_BODY = 65536
MAX_RESPONSE = 4 * 1024 * 1024
REQUEST_HEADERS = {"cookie", "origin", "x-csrf-token", "content-type", "accept", "user-agent"}
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "server",
    "date",
}


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, upstream, ready):
        self.upstream = upstream
        self.ready = ready
        super().__init__(address, Handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def reject(self, status, detail):
        body = json.dumps({"detail": detail}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def forward(self):
        self.connection.settimeout(10)
        hosts = self.headers.get_all("Host", [])
        try:
            host = urlsplit("//" + hosts[0])
            valid = (
                len(hosts) == 1
                and host.hostname in {"127.0.0.1", "localhost"}
                and not host.username
                and not host.password
                and not host.path
                and not host.query
                and not host.fragment
                and (host.port is None or 0 < host.port < 65536)
            )
        except (IndexError, ValueError):
            valid = False
        if not valid:
            return self.reject(400, "loopback_host_required")
        target = urlsplit(self.path)
        path = unquote(target.path)
        if (
            target.scheme
            or target.netloc
            or "\\" in path
            or any(x == ".." for x in path.split("/"))
        ):
            return self.reject(400, "invalid_target")
        if self.command == "GET" and path == "/health":
            return self.reject(
                200 if self.server.ready.is_set() else 503,
                "ready" if self.server.ready.is_set() else "not_ready",
            )
        if self.command not in {"GET", "POST"}:
            return self.reject(405, "method_not_allowed")
        if not (path == "/console" or path.startswith("/console/")):
            return self.reject(404, "console_only")
        lengths = self.headers.get_all("Content-Length", [])
        try:
            size = int(lengths[0]) if lengths else 0
        except ValueError:
            size = -1
        if len(lengths) > 1 or self.headers.get("Transfer-Encoding") or not 0 <= size <= MAX_BODY:
            return self.reject(413, "bounded_body_required")
        if self.command == "GET" and size:
            return self.reject(400, "unexpected_body")
        if not self.server.ready.is_set():
            return self.reject(503, "not_ready")
        body = self.rfile.read(size)
        if len(body) != size:
            return self.reject(400, "incomplete_body")
        headers = {k: v for k, v in self.headers.items() if k.lower() in REQUEST_HEADERS}
        # Preserve the browser's exact origin/Host relationship. Never trust forwarded headers.
        headers["Host"] = hosts[0]
        headers["Content-Length"] = str(size)
        connection = http.client.HTTPConnection(*self.server.upstream, timeout=15)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            content = response.read(MAX_RESPONSE + 1)
            if len(content) > MAX_RESPONSE:
                return self.reject(502, "bounded_response_required")
            self.send_response(response.status)
            blocked = HOP_HEADERS | {
                v.strip().lower() for v in (response.getheader("Connection") or "").split(",")
            }
            for key, value in response.getheaders():
                if key.lower() not in blocked:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(content)
            self.close_connection = True
        except (OSError, http.client.HTTPException):
            self.reject(502, "local_service_unavailable")
        finally:
            connection.close()

    do_GET = forward
    do_POST = forward
    do_PUT = forward
    do_DELETE = forward
    do_PATCH = forward
    do_HEAD = forward
    do_OPTIONS = forward
