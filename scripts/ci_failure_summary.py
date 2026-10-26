"""Publish only trusted test/node identifiers and bounded error codes, never runtime logs."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

junit = Path(".local/ci/junit.xml")
if junit.exists():
    for case in ET.parse(junit).getroot().iter("testcase"):
        errors = list(case.findall("failure")) + list(case.findall("error"))
        for error in errors:
            print(
                json.dumps(
                    {
                        "case": case.attrib["name"],
                        "class": case.attrib["classname"],
                        "type": error.attrib.get("type"),
                        "codes": sorted(
                            set(re.findall(r"\b(?:financial|reporting)_[a-z_]+", error.text or ""))
                        ),
                    }
                )
            )
for result in Path(".local/ci").glob("pass3-demo/warehouse-runs/*/target/run_results.json"):
    data = json.loads(result.read_text(encoding="utf-8"))
    for node in data["results"]:
        if node["status"] in ["error", "fail"]:
            print(
                json.dumps(
                    {
                        "dbt_node": node["unique_id"],
                        "status": node["status"],
                        "failures": node.get("failures"),
                    }
                )
            )

progress = Path(".local/ci/pass4-demo/browser-progress-private.json")
if progress.exists():
    print(json.dumps({"browser_progress": json.loads(progress.read_text(encoding="utf-8"))}))
