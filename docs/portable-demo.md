# Portable local demonstration

## Quick start

Install Docker Engine 28 or newer with Docker Compose V2 (Docker Desktop with Linux containers is suitable). From this repository:

```text
docker compose up --build
```

Wait for the `ready` message, then open **http://127.0.0.1:8592/console**. Initial startup installs isolated synthetic sources and executes real PostgreSQL dbt builds plus independent financial comparisons. It is not an HTML-only preview. Build dependencies require network access; runtime uses a dedicated Docker bridge with loopback-only port publication.

In a separate terminal, display only the selected user's fresh local credential:

```text
docker compose exec demo python -m onboarding.portable credentials --user sponsor
```

The same command accepts `cedar-leader`, `meridian-leader`, `summit-leader` and `reviewer`. Passwords are random per startup and stored in mode-600 private volume files, never in the image, Compose environment, default logs or this repository. Treat displayed credentials and the Docker volume as private. Anyone who controls the host or Docker daemon remains trusted.

Use `ACQUISITION_DEMO_PORT` to select a different host port if 8592 is occupied. The port remains bound to `127.0.0.1`. The gateway accepts `127.0.0.1` and `localhost` Host headers only.

## Five-minute guided inspection

1. **Sponsor:** Compare Cedar, Meridian and held Summit in Portfolio overview. The companies retain different source structures, scoped customer IDs and separate legal entities.
2. **Reporting history:** Switch between Original and Restated. Consolidated net invoicing changes from synthetic USD $368,000 to $388,000. Bookings remain $550,000, allocated cash $230,000 and supported eliminations $20,000.
3. **Financial reconciliation:** Open invoice/ERP source drilldowns. The $5,000 posting difference and $8,000 unsupported intercompany candidate remain separate open exceptions. A passing data import does not eliminate either finding.
4. **Company scope:** Sign out, retrieve `cedar-leader` credentials and sign in. Only Cedar is visible; foreign-company requests are denied by the server, not merely hidden by the UI.
5. **Governed review:** Sign in as `reviewer`, whose scope is Summit. Propose/reject an identity resolution, then create and explicitly approve a new proposal. Preview and review mapping version 2, then recompute admission. Inspect actor-bound audit history. Current admission can change while the frozen financial publication still shows Summit held at its cutoff.

The console exposes governance, not the private dispatch API. The seeded handoff has one independently verified local HTTP effect and receipt. Browser review does not make additional business POSTs. Inspect [governance](governed-execution.md), [financial contracts](financial-reporting.md), the existing [console controls](operations-console.md) and `tests/test_portable.py` for the deeper implementation.

## Shutdown and fresh execution

Press Ctrl+C in the Compose terminal, or run:

```text
docker compose down --volumes --remove-orphans
```

This deletes only this Compose project's disposable databases, credentials and private logs. It does not modify source files or historical repository evidence. A normal stop also gracefully retires owned SQL/HTTP resources. A later start creates a fresh synthetic run and new credentials; this demo intentionally does not resume prior operator edits. Until the volume is removed, old private run directories remain on disk even though their databases are inactive. Never publish that volume or copy it into the repository.

For detached operation, use `docker compose up --build -d --wait`. Allow roughly 2 GB of available memory plus image/build storage. The configured runtime ceiling is 1.5 GiB, two CPUs and 256 processes; these are limits, not measured capacity guarantees.

## Packaging and security boundary

One non-root container runs the existing installer, PostgreSQL, application and independently executing receiver processes. The two databases and restricted SQL roles remain separate; they share one trusted local host/container rather than representing separate production security domains. Internal services still bind to loopback. Only a bounded console gateway listens on the container interface, and Compose publishes that port on host loopback. PostgreSQL, receiver, intake, dispatch and OpenAPI endpoints are not published.

The gateway preserves exact Origin/Host checks, CSRF, opaque sessions, cookie attributes and response security headers. Non-console paths, external Host headers, ambiguous body framing and oversized requests are rejected. Root filesystem is read-only, all Linux capabilities are dropped, privilege escalation is disabled, and runtime state is confined to a private named volume and temporary mounts. Native vendor configuration is refused by the portable entrypoint.

The first actual container trial reached healthy status on an internal-only network but could not serve the host-published console. The dedicated bridge supports that host connection, defaults published addresses to loopback and disables inter-container communication. It does **not** provide an outbound network firewall. The demo workflow uses only its local contracts; the host and Docker daemon remain trusted. [Docker's bridge documentation](https://docs.docker.com/engine/network/drivers/bridge/) describes these networking properties.

Docker documents that localhost-published ports in versions before Engine 28 could be reachable from the same network segment. Use a current Engine and host firewall; this remains local HTTP, not production SSO/TLS or hostile multi-tenant isolation. [Docker port-publishing guidance](https://docs.docker.com/engine/network/port-publishing/) explains the relevant host boundary.

## Reproduce packaging acceptance

The optional acceptance image adds Chromium and the existing pinned axe script. It also provisions one test-only login limited to expiring sessions, without permission to read session secret columns or create databases/roles. The normal reviewer image does not include that login or Chromium.

```text
python scripts/verify_portable.py --workspace .local/portable-review --output .local/portable-review-evidence
```

The host runner needs the pinned Python dependencies from `requirements.lock`; reviewers launching the ordinary demo need only Docker. The runner builds and tests the normal image, authenticates through the host-published gateway, shuts it down, restarts it and rejects old credentials/sessions. It then executes the original real-browser acceptance through the gateway in the optional image, including company scope, CSRF, governance/audit, immutable publications, open exceptions, keyboard/mobile and accessibility checks. It verifies image source bytes, container settings and independently inventories project containers, networks and volumes after teardown.

With local Python 3.12/PostgreSQL 17 binaries and installed Playwright Chromium, `--native` exercises the same entrypoint and browser harness on loopback. That fallback does not establish Docker execution. New packaging results are distinct from historical Pass 1–5 evidence and are not another independent architecture audit.

[Recorded portable acceptance, screenshots and exact-source verification](evidence/portable/README.md).
