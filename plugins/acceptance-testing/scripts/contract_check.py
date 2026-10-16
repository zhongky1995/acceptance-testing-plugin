#!/usr/bin/env python3
"""Run an existing project's JSON adapter against frozen, offline input files.

The adapter must call the real producer schema and consumer validator; duplicating
those rules here would test a substitute. stdin is the input JSON; stdout is a
JSON object with producer_accepts, consumer_accepts and both *_evidence strings.
The enclosing qa run owns the process-group timeout and budget.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from qa_store import QAError, file_hash, load, save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("output")
    args = parser.parse_args()
    spec = load(args.spec)
    root = Path.cwd().resolve()
    argv = spec["argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        raise QAError("adapter argv 必须是非空数组")
    argv = [sys.executable if a == "{python}" else a for a in argv]
    results, tests = [], []
    for sample in spec["samples"]:
        path = (root / sample["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 25000000:
            raise QAError("契约输入必须是项目内的小型离线文件")
        raw = path.read_bytes()
        json.loads(raw)
        proc = subprocess.run(argv, input=raw, capture_output=True, timeout=30)
        try:
            actual = json.loads(proc.stdout)
        except (ValueError, UnicodeDecodeError):
            actual = {}
        row = {"id": sample["id"], "sha256": file_hash(path), "expected_producer": sample["expected_producer"],
               "expected_consumer": sample["expected_consumer"], "returncode": proc.returncode,
               "actual": actual, "stderr": proc.stderr.decode("utf-8", errors="replace")}
        ok = consistent(row)
        row["status"] = "passed" if ok else "failed"
        results.append(row)
        tests.append({"name": sample["id"], "status": row["status"]})
    save(args.output, {"boundary": spec["boundary"], "sample_results": results, "tests": tests})
    return 0 if tests and all(t["status"] == "passed" for t in tests) else 1


def consistent(row):
    actual = row.get("actual", {})
    if not isinstance(actual, dict):
        return False
    for side in ("producer", "consumer"):
        if type(row.get(f"expected_{side}")) is not bool or type(actual.get(f"{side}_accepts")) is not bool:
            return False
        if actual[f"{side}_accepts"] != row[f"expected_{side}"]:
            return False
        if not isinstance(actual.get(f"{side}_evidence"), str) or not actual[f"{side}_evidence"].strip():
            return False
    return row.get("returncode") == 0 and not (actual["producer_accepts"] and not actual["consumer_accepts"])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (QAError, OSError, KeyError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"契约检查受阻：{exc}", file=sys.stderr)
        sys.exit(2)
