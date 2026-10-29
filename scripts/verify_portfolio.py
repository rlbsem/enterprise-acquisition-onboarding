"""Bind and execute the real multi-company lane; private logs never become public evidence."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fingerprints():
    files = [ROOT / "requirements.lock", ROOT / "pyproject.toml"]
    for folder in ["src", "warehouse", "scripts", "tests"]:
        files += [
            p
            for p in (ROOT / folder).rglob("*")
            if p.is_file()
            and p.suffix in [".py", ".sql", ".yml", ".yaml", ".html", ".css", ".js", ".json"]
            and not any(s in p.parts for s in ["__pycache__", "target", "logs"])
        ]
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(
            p.read_text(encoding="utf-8").encode()
        ).hexdigest()
        for p in sorted(files)
    }


def binding():
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    hashes = fingerprints()
    for path, value in hashes.items():
        assert (
            hashlib.sha256(
                subprocess.check_output(["git", "show", revision + ":" + path], cwd=ROOT)
            ).hexdigest()
            == value
        ), "uncommitted_execution_source:" + path
    return dict(
        source_commit=revision,
        source_hash_encoding="UTF-8 with LF line endings",
        source_hashes=hashes,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sizes", nargs="+", type=int, default=[3, 10, 25, 50])
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--binding-file", type=Path)
    p.add_argument("--write-binding", action="store_true")
    p.add_argument("--browser", action="store_true")
    a = p.parse_args()
    stamp = json.loads(a.binding_file.read_bytes()) if a.binding_file else binding()
    assert stamp["source_hashes"] == fingerprints(), "source_binding_mismatch"
    if a.write_binding:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_bytes((json.dumps(stamp, indent=2) + "\n").encode())
        return
    if a.workspace is None or a.workspace.exists() or a.output.exists():
        raise ValueError("fresh_workspace_and_output_required")
    a.workspace.mkdir(parents=True)
    private = a.workspace / "source-binding.json"
    private.write_bytes((json.dumps(stamp, indent=2) + "\n").encode())
    command = [
        sys.executable,
        "-m",
        "onboarding.portfolio_demo",
        "--workspace",
        str(a.workspace / "work"),
        "--output",
        str(a.output),
        "--sizes",
        *[str(x) for x in a.sizes],
        "--repeats",
        str(a.repeats),
        "--workers",
        str(a.workers),
        "--binding-file",
        str(private),
    ]
    if a.browser:
        command += ["--browser"]
    with (a.workspace / "execution-private.log").open("w", encoding="utf-8") as log:
        r = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=2400,
        )
    assert fingerprints() == stamp["source_hashes"], "source_changed_during_measurement"
    if r.returncode:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "classification": "inspect_private_execution_log",
                    "returncode": r.returncode,
                }
            )
        )
        raise SystemExit(1)
    hashes = {
        p.relative_to(a.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(a.output.rglob("*"))
        if p.is_file() and p.name != "artifact-integrity.json"
    }
    (a.output / "artifact-integrity.json").write_bytes(
        (json.dumps(hashes, indent=2) + "\n").encode()
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "sizes": a.sizes,
                "repeats": a.repeats,
                "source_commit": stamp["source_commit"],
            }
        )
    )


if __name__ == "__main__":
    main()
