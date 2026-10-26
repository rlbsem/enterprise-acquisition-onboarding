"""Reuse the original real-browser acceptance through the packaged console gateway."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from .console_demo import browser_acceptance
from .db import connect
from .portable import current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("/state"))
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    if a.output.exists():
        raise ValueError("fresh_acceptance_output_required")
    record, run = current(a.state.resolve())
    if not record["acceptance"]:
        raise ValueError("explicit_acceptance_mode_required")
    config = json.loads((run / "acceptance-private.json").read_text())
    stack = SimpleNamespace(**config, path=run, url=record["url"])
    # The only extra SQL login can expire sessions, not read their secret columns.
    with connect(stack.admin_dsn) as c:
        row = c.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert not any(row.values())
        assert not c.execute(
            "SELECT has_column_privilege(current_user,'console_sessions','session_hash','SELECT') allowed"
        ).fetchone()["allowed"]
    a.output.parent.mkdir(parents=True, exist_ok=True)
    result = browser_acceptance(stack, a.output.parent)
    result["packaged_gateway"] = True
    result["test_expiry_role_is_restricted"] = True
    result["image_sha256"] = {
        r["file"]: hashlib.sha256((a.output.parent / r["file"]).read_bytes()).hexdigest()
        for r in result["screenshots"]
    }
    result["financial_summary"] = json.loads((run / "financial-summary.json").read_text())
    result["boundary"] = (
        "actual local PostgreSQL, dbt and HTTP; no native vendor or independent architecture audit"
    )
    a.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    if os.name != "nt":
        a.output.chmod(0o600)
    print(
        json.dumps(
            {
                "browser_checks": len(result["checks"]),
                "screenshots": len(result["screenshots"]),
                "accessibility_views": len(result["accessibility"]),
                "passed": True,
            }
        )
    )


if __name__ == "__main__":
    main()
