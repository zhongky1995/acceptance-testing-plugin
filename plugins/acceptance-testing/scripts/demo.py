#!/usr/bin/env python3
"""Offline example: detect a real rule defect, repair an isolated copy, retest."""
import argparse
import shutil
import sys
from pathlib import Path
from qa_report import report_session
from qa_runtime import run
from qa_store import save, scan


def make_plan(project, directory):
    inventory = scan(project, [directory])
    save(directory / "inventory.json", inventory)
    plan = {"schema_version": "1.1", "project_root": str(project), "scenario": "local-iteration",
            "goal": "本地审批业务规则验收", "snapshot": inventory["snapshot"],
            "environment": {"python": sys.version.split()[0], "mode": "offline-local-fixture"},
            "limits": {"execution_seconds": 30, "max_attempts_per_case": 2, "max_external_cost": 0, "currency": "CNY"},
            "allow_install": False,
            "requirements": [{"id": "R1", "statement": "角色、本人审批、金额与防重复规则符合 PRD",
                              "status": "confirmed", "required": True, "sources": ["PRD.md:3-5"]}],
            "cases": [{"id": "C1", "title": "实际审批规则与边界", "dimension": "functional", "requirement_ids": ["R1"],
                       "required": True, "in_scope": True, "expected": "全部八个行为断言通过", "prerequisites": [],
                       "executor": {"kind": "command", "argv": ["{python}", "check_rules.py", "--output", "{evidence_dir}/result.json"],
                                    "adapter": "native", "result_path": "{evidence_dir}/result.json", "timeout_seconds": 10,
                                    "external_calls": False, "external_cost_bound": 0, "installs": False}}],
            "acceptance": {"scope": "focused", "reason": "只演示审批规则缺陷的发现与修复复测", "sources": ["PRD.md:3-5"],
                           "surfaces": ["gui", "api"], "journeys": [], "surface_exclusions": [],
                           "layers": {"implementation": {"status": "required"},
                                      "need_fit": {"status": "deferred", "reason": "样例只验证既有规则的实现", "sources": ["PRD.md:3-5"]},
                                      "interaction": {"status": "deferred", "reason": "该命令样例未执行浏览器", "sources": ["ARCHITECTURE.md"]}}},
            "feedback": []}
    save(directory / "plan.json", plan)
    return directory / "plan.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit("输出目录已存在，请选新目录以保留历史证据。")
    project = output / "project"
    source = Path(__file__).resolve().parents[1] / "tests/fixtures/approval-project"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns("__pycache__"))
    first = output / "before"
    run(make_plan(project, first), first)
    before = report_session(first)
    app = project / "app.py"
    text = app.read_text()
    text = text.replace('    if request["state"] == "approved":',
                        '    if actor == request["requester"]:\n        raise PermissionError("self approval forbidden")\n    if request["state"] == "approved":')
    app.write_text(text)
    second = output / "after"
    run(make_plan(project, second), second)
    after = report_session(second)
    save(output / "comparison.json", {"before": before["gate"], "after": after["gate"],
                                      "before_report": str(first / "report.md"), "after_report": str(second / "report.md"),
                                      "note": "仅修复隔离样例，真实项目不会自动修改；初次失败证据保留。"})
    print(f"初轮：{before['gate']}；修复后新轮：{after['gate']}；报告：{output}")
    return 0 if before["gate"] == "failed" and after["gate"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
