"""One complete local HTTP/PostgreSQL demonstration. Output contains no runtime credentials."""

import argparse
import json
from pathlib import Path
from .sandbox import Sandbox
from .db import connect


def execute(stack):
    responses = []
    for message in stack.messages:
        with stack.client(company=message["company"], source=message["source"]) as client:
            r = client.post("/v1/intake", json=message)
            r.raise_for_status()
        responses.append(
            {
                "company": message["company"],
                "source": message["source"],
                "event_id": message["event_id"],
                "response": r.json(),
            }
        )
    original = next(
        m for m in stack.messages if m["company"] == "summit" and m["source"] == "legacy-ops"
    )
    invalid = {
        **original,
        "event_id": "wrong-entity-review",
        "data": {**original["data"], "entity": "LE-US-02"},
    }
    with stack.client(company=invalid["company"], source=invalid["source"]) as client:
        conflict = client.post("/v1/intake", json=invalid)
        conflict.raise_for_status()
    assert conflict.json()["reason"] == "incorrect_legal_entity"
    gates = []
    with stack.client("controller") as client:
        for company in ["cedar", "meridian", "summit"]:
            r = client.post("/v1/admission/" + company)
            r.raise_for_status()
            gates.append(r.json())
    message = stack.messages[0]
    with connect(stack.dsn) as c:
        before = c.execute("SELECT count(*) n FROM source_records").fetchone()["n"]
    with stack.client(company=message["company"], source=message["source"]) as client:
        replay = client.post("/v1/intake", json=message)
        replay.raise_for_status()
    with connect(stack.dsn) as c:
        after = c.execute("SELECT count(*) n FROM source_records").fetchone()["n"]
        journal = c.execute(
            "SELECT company,source,event_id,status,reason,hash FROM messages ORDER BY id"
        ).fetchall()
        exceptions = c.execute(
            "SELECT company,reason,detail FROM quarantine ORDER BY id"
        ).fetchall()
    with stack.client("viewer") as client:
        r = client.get("/v1/portfolio")
        r.raise_for_status()
        view = r.json()
    assert [g["passed"] for g in gates] == [True, True, False]
    assert view["included_companies"] == 2 and view["included_customer_accounts"] == 2
    assert replay.json()["duplicate"] and before == after == 8
    return {
        "lane": "actual_local_http_postgresql",
        "native_vendor_calls": 0,
        "synthetic": True,
        "scenarios": {
            "A_clean": {
                "expected_included_companies": 2,
                "observed_included_companies": view["included_companies"],
            },
            "B_ambiguity": {
                "expected": "ambiguous_identity",
                "observed": next(
                    r["response"]["reason"]
                    for r in responses
                    if r["company"] == "summit" and r["source"] == "legacy-crm"
                ),
            },
            "C_readiness_gate": {
                "expected": False,
                "observed": gates[-1]["passed"],
                "issues": gates[-1]["issues"],
                "invalid_legal_entity_response": conflict.json(),
            },
            "D_replay": {
                "expected_source_records": 8,
                "before": before,
                "after": after,
                "response": replay.json(),
            },
        },
        "source_intake": responses,
        "readiness_gates": gates,
        "portfolio": view,
        "message_journal": journal,
        "quarantine": exceptions,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    output = Path(a.output)
    if output.exists():
        raise ValueError("fresh_output_required")
    with Sandbox(a.workspace) as stack:
        result = execute(stack)
    result["owned_resources_cleaned"] = True
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps(result, indent=2, default=str) + "\n").encode())
    print(
        json.dumps(
            {
                "included_companies": 2,
                "held_acquisitions": 1,
                "duplicate_business_records": 0,
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    main()
