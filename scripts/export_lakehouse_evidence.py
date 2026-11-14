"""Export allowlisted native records; raw provider logs and identities stay private."""

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project(raw):
    public = {k: raw[k] for k in ["run_id", "source_commit"]}
    public["state"] = {k: raw["state"].get(k) for k in ["life_cycle_state", "result_state"]}
    public["tasks"] = []
    for t in raw["tasks"]:
        item = {
            k: t.get(k)
            for k in ["task_key", "run_id", "execution_duration_ms", "setup_duration_ms"]
        }
        item["state"] = {k: t["state"].get(k) for k in ["life_cycle_state", "result_state"]}
        if "result" in t:
            item["result"] = t["result"]
        if "error" in t:
            item["failure_observation"] = t["error"].splitlines()[0][:400]
        public["tasks"].append(item)
    data = json.dumps(public, sort_keys=True)
    # Secondary rejection, not the primary redaction mechanism.
    if re.search(
        r"(?i)(access_token|refresh_token|client_secret|bearer\s|dbc-[a-z0-9-]+\.cloud|[\w.+-]+@[\w.-]+\.[a-z]{2,})",
        data,
    ):
        raise ValueError("private_content_refused")
    return public


def verify(document):
    if not re.fullmatch("[0-9a-f]{40}", document["source_commit"]):
        raise ValueError("source_revision_missing")
    if type(document["run_id"]) is not int or not document["tasks"]:
        raise ValueError("native_run_identity_missing")
    for t in document["tasks"]:
        result = t.get("result")
        if result:
            if (
                result["source_commit"] != document["source_commit"]
                or result.get("synthetic") is not True
            ):
                raise ValueError("native_result_source_mismatch")
            if t["state"]["result_state"] != "SUCCESS" or result["status"] != "passed":
                raise ValueError("success_claim_inconsistent_with_job_state")
            for observation in result["observations"]:
                v = observation["result"]
                if (
                    isinstance(v, dict)
                    and "equal" in v
                    and (v["equal"] is not True or v["actual"] != v["expected"])
                ):
                    raise ValueError("failed_comparison_claimed_as_pass")
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--observation", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    src, dst = Path(a.observation), Path(a.output)
    if dst.exists():
        raise ValueError("immutable_fresh_evidence_required")
    public = project(json.loads(src.read_bytes()))
    verify(public)
    public["private_observation_sha256"] = digest(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        json.dumps(public, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(dict(exported=dst.name, sha256=digest(dst))))


if __name__ == "__main__":
    main()
