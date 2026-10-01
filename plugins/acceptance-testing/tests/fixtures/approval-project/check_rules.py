import argparse
import json
from pathlib import Path
from app import approve, create_request


def denied(call, error):
    try:
        call()
    except error:
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    req = create_request("alice", 500)
    approve(req, "bob", "manager")
    checks = [
        ("主管可审批他人申请", req["state"] == "approved"),
        ("普通员工不能审批", denied(lambda: approve(create_request("alice", 1), "bob", "employee"), PermissionError)),
        ("主管不能审批本人申请", denied(lambda: approve(create_request("alice", 1), "alice", "manager"), PermissionError)),
        ("零金额被拒绝", denied(lambda: create_request("alice", 0), ValueError)),
        ("超过金额上限被拒绝", denied(lambda: create_request("alice", 10001), ValueError)),
        ("最低金额可创建", create_request("alice", 1)["amount"] == 1),
        ("最高金额可创建", create_request("alice", 10000)["amount"] == 10000),
    ]
    approve(req, "bob", "manager")
    checks.append(("重复审批不增加记录", len(req["approvals"]) == 1))
    output = {"tests": [{"name": name, "status": "passed" if passed else "failed",
                         "expected": True, "actual": passed} for name, passed in checks]}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
