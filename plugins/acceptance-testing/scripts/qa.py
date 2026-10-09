#!/usr/bin/env python3
"""Acceptance Testing CLI, Python 3.10+, standard library only."""
import argparse
import json
import sys
from pathlib import Path
from qa_contracts import validate
from qa_report import report_session
from qa_runtime import check_case, record, run
from qa_acceptance import readiness, template
from qa_store import QAError, SCHEMA_VERSION, load, project_snapshot, save, scan


def main(argv=None):
    parser = argparse.ArgumentParser(description="验收测试：只读发现、冻结方案、按预算执行、保留证据。")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("scan", "init"):
        p = sub.add_parser(action)
        p.add_argument("--project", required=True)
        p.add_argument("--session-dir", required=True)
        if action == "init":
            p.add_argument("--scenario", choices=["local-iteration", "third-party", "target-delivery"], default="local-iteration")
            p.add_argument("--goal", required=True)
            p.add_argument("--scope", choices=["product", "focused"], default="product")
    p = sub.add_parser("validate")
    p.add_argument("--plan", required=True)
    p = sub.add_parser("readiness")
    p.add_argument("--plan", required=True)
    for action in ("run", "record"):
        p = sub.add_parser(action)
        p.add_argument("--plan", required=True)
        p.add_argument("--session-dir", required=True)
        if action == "run":
            p.add_argument("--case")
            p.add_argument("--retry", action="store_true")
        else:
            p.add_argument("--observation", required=True)
    p = sub.add_parser("report")
    p.add_argument("--session-dir", required=True)
    p = sub.add_parser("gate")
    p.add_argument("--session-dir", required=True)
    p.add_argument("--scope", choices=["product", "focused"], default="product")
    p = sub.add_parser("check")
    p.add_argument("--plan", required=True)
    p.add_argument("--session-dir", required=True)
    p.add_argument("--case", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action in {"scan", "init"}:
            directory = Path(args.session_dir).resolve()
            if Path(args.project).resolve().is_relative_to(directory):
                raise QAError("档案目录不能等于项目根目录或其祖先，避免排除整个被测项目")
            if args.action == "init" and (directory / "plan.json").exists():
                raise QAError("方案已存在，请新建目录，不覆盖已有标准")
            inventory = scan(args.project, [directory])
            save(directory / "inventory.json", inventory)
            if args.action == "init":
                plan = {"schema_version": SCHEMA_VERSION, "project_root": inventory["project_root"],
                        "scenario": args.scenario, "goal": args.goal, "snapshot": inventory["snapshot"],
                        "environment": {"local_runtime": sys.version.split()[0], "host": "unknown",
                                        "browser": "unknown", "computer_use": "unknown"},
                        "limits": {"execution_seconds": 600, "max_attempts_per_case": 2,
                                   "max_external_cost": 0, "currency": "CNY"},
                        "allow_install": False, "requirements": [], "cases": [], "feedback": [], "acceptance": template(args.scope)}
                save(directory / "plan.json", plan)
            print(json.dumps({"inventory": str(directory / "inventory.json"), "snapshot": inventory["snapshot"],
                              "note": "发现完成；模板预算是起点，可调整。未运行项目、安装依赖或执行测试。"}, ensure_ascii=False))
        elif args.action == "validate":
            validate(load(args.plan))
            print("方案结构与依赖校验通过；尚未执行测试。")
        elif args.action == "readiness":
            plan = validate(load(args.plan))
            root, parent = Path(plan["project_root"]).resolve(), Path(args.plan).resolve().parent
            exclusions = [parent] if parent != root and parent.is_relative_to(root) else []
            snapshot = project_snapshot(root, exclusions)
            result = readiness(plan, snapshot)
            if not snapshot["complete"] or snapshot["digest"] != plan["snapshot"]["digest"]:
                result["gaps"].append("当前项目快照不完整或已改变，请新建轮次")
            print(json.dumps(result, ensure_ascii=False))
            return 2 if result["gaps"] else 0
        elif args.action == "check":
            result = check_case(args.plan, args.session_dir, args.case)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["allowed"] else 2
        elif args.action in {"run", "record"}:
            if args.action == "run":
                run(args.plan, args.session_dir, args.case, args.retry)
            else:
                record(args.plan, args.session_dir, args.observation)
            report = report_session(args.session_dir)
            print(json.dumps({"gate": report["gate"], "scope": report["acceptance"]["scope"], "product_accepted": report["product_accepted"], "counts": report["counts"],
                              "report": str(Path(args.session_dir).resolve() / "report.md")}, ensure_ascii=False))
            return {"passed": 0, "failed": 1, "inconclusive": 2}[report["gate"]]
        else:
            report = report_session(args.session_dir)
            print(json.dumps({"gate": report["gate"], "scope": report["acceptance"]["scope"], "product_accepted": report["product_accepted"],
                              "gaps": report["gaps"], "acceptance": report["acceptance"], "dimensions": report["dimensions"]}, ensure_ascii=False))
            if args.action == "gate" and args.scope == "product" and not report["product_accepted"]:
                return 1 if report["gate"] == "failed" else 2
            return {"passed": 0, "failed": 1, "inconclusive": 2}[report["gate"]]
    except (QAError, KeyError, TypeError, OSError) as exc:
        print(f"受阻：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
