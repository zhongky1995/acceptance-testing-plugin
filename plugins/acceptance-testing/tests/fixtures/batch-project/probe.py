"""Offline batch recovery example. Invoke with a fixture JSON and evidence directory."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


def resume(batch, events):
    for row in batch["rows"]:
        key = row["id"]
        if batch["states"].get(key) == "posted":
            continue
        if "amount" not in row:
            events.append({"stage": "validate", "fault": "missing-amount", "object": key})
            batch["states"][key] = "held"
            continue
        events.append({"stage": "post", "object": key})
        batch["states"][key] = "posted"


def main():
    path, directory = map(Path, sys.argv[1:])
    raw = path.read_bytes()
    batch = json.loads(raw)
    events = []
    resume(batch, events)
    resume(batch, events)
    trace = {"events": events, "batch": batch["batch"], "states": batch["states"]}
    (directory / "events.json").write_text(json.dumps(trace))
    fault = next((e for e in events if "fault" in e), {"stage": "validate", "fault": "none"})
    calls = [e["object"] for e in events if e["stage"] == "post"]
    counts = Counter(calls)
    receipt = {"stage": fault["stage"], "fault": fault["fault"], "sample_id": path.stem,
               "sha256": hashlib.sha256(raw).hexdigest(), "run_id": batch["batch"],
               "states": batch["states"], "next_inputs": {"post": calls},
               "effects": {"post:" + row["id"]: counts[row["id"]] for row in batch["rows"]},
               "trace_file": "events.json", "locator": "events and final states after two resume calls"}
    (directory / "result.json").write_text(json.dumps(receipt))


if __name__ == "__main__":
    main()
