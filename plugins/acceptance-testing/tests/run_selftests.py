#!/usr/bin/env python3
import argparse
import json
import sys
import unittest
from pathlib import Path


class NativeResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"name": test.id(), "status": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"name": test.id(), "status": "failed"})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"name": test.id(), "status": "failed"})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({"name": test.id(), "status": "skipped", "reason": reason})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent), pattern="test_*.py")
    result = unittest.TextTestRunner(resultclass=NativeResult, verbosity=1).run(suite)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"tests": result.records}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.wasSuccessful() and result.records else 1)
