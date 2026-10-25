"""Fresh local acceptance; private logs stay outside published evidence."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    files = [ROOT / "pyproject.toml", ROOT / "requirements.lock"]
    for folder in ["src", "tests", "scripts"]:
        files += [p for p in (ROOT / folder).rglob("*") if p.suffix in [".py", ".sql"]]
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    work, out = Path(a.workspace).resolve(), Path(a.output).resolve()
    if work.exists() or out.exists():
        raise ValueError("fresh_workspace_and_evidence_required")
    work.mkdir(parents=True)
    out.mkdir(parents=True)
    start = source_hashes()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    def run(name, args):
        with (work / (name + ".log")).open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [sys.executable, *args],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PYTHONUTF8": "1",
                    "ONBOARDING_TEST_EVIDENCE": str(out),
                },
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if result.returncode:
            raise RuntimeError("acceptance_failed:" + name + "; inspect private log")

    run("lint", ["-m", "ruff", "check", "src", "tests", "scripts"])
    run("format", ["-m", "ruff", "format", "--check", "src", "tests", "scripts"])
    run(
        "tests",
        [
            "-m",
            "pytest",
            "-q",
            "--basetemp=" + str(work / "pytest"),
            "--junitxml=" + str(work / "junit.xml"),
        ],
    )
    suite = ET.parse(work / "junit.xml").getroot().find("testsuite")
    if any(int(suite.attrib[k]) for k in ["failures", "errors", "skipped"]):
        raise ValueError("required_cases_not_all_passed")
    run(
        "demo",
        [
            "-m",
            "onboarding.demo",
            "--workspace",
            str(work / "demo"),
            "--output",
            str(out / "demo.json"),
        ],
    )
    run(
        "pass2-demo",
        [
            "-m",
            "onboarding.pass2_demo",
            "--workspace",
            str(work / "pass2-demo"),
            "--output",
            str(out / "pass2.json"),
        ],
    )
    if start != source_hashes():
        raise ValueError("source_changed_during_acceptance")
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "source_commit": revision,
        "source_sha256": start,
        "python": platform.python_version(),
        "os": platform.system(),
        "lane": "actual_local_postgresql_and_loopback_http",
        **{k: int(suite.attrib[k]) for k in ["tests", "failures", "errors", "skipped"]},
        "cases": [
            {"class": c.attrib["classname"], "name": c.attrib["name"], "outcome": "passed"}
            for c in suite.findall("testcase")
        ],
        "native_vendor_execution": False,
        "cloud_resources": False,
        "scope": "Passes 1 and 2; finite local acceptance, no independent final audit or later-pass acceptance",
    }
    (out / "verification.json").write_bytes((json.dumps(report, indent=2) + "\n").encode())
    manifest = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()
    }
    (out / "manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    print(
        json.dumps(
            {
                "tests": report["tests"],
                "failures": 0,
                "errors": 0,
                "skipped": 0,
                "evidence": str(out),
            }
        )
    )


if __name__ == "__main__":
    main()
