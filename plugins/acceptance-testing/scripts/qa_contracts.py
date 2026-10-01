"""Authoritative cross-field validation; descriptive schema lives in references."""
import math
import re
from pathlib import Path
from qa_store import QAError, SCHEMA_VERSION

SCENARIOS = {"local-iteration", "third-party", "target-delivery"}
DIMENSIONS = {"functional", "reliability", "environment", "delivery", "cost", "evidence"}
ADAPTERS = {"exit", "junit", "playwright", "native"}
STATES = {"passed", "failed", "blocked", "skipped", "not_run", "flaky"}


def need(condition, message):
    if not condition:
        raise QAError(message)


def number(value, label, positive=False):
    need(type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0),
         f"{label} 必须是有限的{'正' if positive else '非负'}数")


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value)


def validate(plan):
    need(isinstance(plan, dict), "方案必须是对象")
    need(plan.get("schema_version") == SCHEMA_VERSION, "不支持的方案版本")
    need(plan.get("scenario") in SCENARIOS, "未知场景")
    root = Path(plan.get("project_root", ""))
    need(root.is_absolute() and root.is_dir(), "project_root 必须是存在的绝对目录")
    need(isinstance(plan.get("goal"), str) and plan["goal"].strip(), "需要本轮目标")
    snapshot = plan.get("snapshot", {})
    need(isinstance(snapshot.get("digest"), str) and re.fullmatch(r"[0-9a-f]{64}", snapshot["digest"]), "缺少有效的项目快照")
    need(type(snapshot.get("complete")) is bool, "快照 complete 必须是布尔值")
    need(isinstance(plan.get("environment"), dict) and bool(plan["environment"]), "需要环境标识，不得写入密钥")
    limits = plan.get("limits", {})
    number(limits.get("execution_seconds"), "execution_seconds", True)
    number(limits.get("max_external_cost"), "max_external_cost")
    need(type(limits.get("max_attempts_per_case")) is int and 1 <= limits["max_attempts_per_case"] <= 10,
         "max_attempts_per_case 必须在 1..10")
    need(isinstance(limits.get("currency"), str) and limits["currency"], "需要费用币种或 unit")
    need(type(plan.get("allow_install")) is bool, "allow_install 必须是布尔值")
    requirements = plan.get("requirements")
    need(isinstance(requirements, list) and requirements, "至少需要一项要求；空白模板不能执行")
    req_ids = set()
    for item in requirements:
        need(isinstance(item, dict) and identifier(item.get("id")), "要求编号无效")
        need(item["id"] not in req_ids, "要求编号重复")
        req_ids.add(item["id"])
        need(isinstance(item.get("statement"), str) and item["statement"].strip(), "要求缺少内容")
        need(item.get("status") in {"confirmed", "proposed", "conflict"}, "要求状态无效")
        need(type(item.get("required")) is bool, "要求 required 必须是布尔值")
        need(isinstance(item.get("sources"), list) and item["sources"] and
             all(isinstance(s, str) and s.strip() for s in item["sources"]), "要求必须有来源")
    need(any(r["required"] for r in requirements), "至少需要一项本轮必须验证的要求")
    cases = plan.get("cases")
    need(isinstance(cases, list) and cases, "至少需要一条用例；零用例不能验收")
    ids = set()
    for item in cases:
        need(isinstance(item, dict) and identifier(item.get("id")), "用例编号无效")
        need(item["id"] not in ids, "用例编号重复")
        ids.add(item["id"])
        need(isinstance(item.get("title"), str) and item["title"].strip(), "用例缺少标题")
        need(item.get("dimension") in DIMENSIONS, "用例维度无效")
        need(type(item.get("in_scope")) is bool and type(item.get("required")) is bool, "范围和门禁必须是布尔值")
        need(not item["required"] or item["in_scope"], "范围外用例不能成为本轮门禁")
        references = item.get("requirement_ids", [])
        need(isinstance(references, list) and references and set(references) <= req_ids, "用例要求对应关系无效")
        need(isinstance(item.get("expected"), str) and item["expected"].strip(), "需要明确的预期结果")
        need(isinstance(item.get("prerequisites", []), list), "prerequisites 必须是列表")
        executor = item.get("executor", {})
        need(executor.get("kind") in {"command", "observation"}, "执行类型无效")
        number(executor.get("external_cost_bound", 0), "external_cost_bound")
        need(type(executor.get("external_calls", False)) is bool and type(executor.get("installs", False)) is bool,
             "执行副作用声明必须是布尔值")
        if executor.get("external_calls"):
            need("external_cost_bound" in executor, "外部调用需要明确费用上界；未知费用先记录受阻")
        if executor["kind"] == "command":
            need(executor.get("adapter") in ADAPTERS, "未知适配器")
            argv = executor.get("argv")
            need(isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv), "argv 必须是非空字符串数组")
            number(executor.get("timeout_seconds"), "timeout_seconds", True)
            cwd = (root / executor.get("cwd", ".")).resolve()
            need(cwd.is_relative_to(root.resolve()) and cwd.is_dir(), "执行目录必须位于项目内")
            if executor["adapter"] != "exit":
                result = executor.get("result_path", "")
                need(isinstance(result, str) and result.startswith("{evidence_dir}/") and ".." not in Path(result).parts,
                     "结构化结果必须写入本次独立 evidence_dir，避免旧报告假通过")
    for case in cases:
        deps = case.get("prerequisites", [])
        need(all(isinstance(d, str) and d in ids and d != case["id"] for d in deps), "用例依赖不存在或指向自身")
    graph = {c["id"]: c.get("prerequisites", []) for c in cases}
    visiting, done = set(), set()

    def visit(node):
        need(node not in visiting, "用例依赖形成循环")
        if node in done:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        done.add(node)

    for node in graph:
        visit(node)
    return plan
