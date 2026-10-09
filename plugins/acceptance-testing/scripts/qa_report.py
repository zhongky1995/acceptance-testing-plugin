"""Report only recorded facts; interpretation and feedback stay separately labeled."""
from collections import Counter
from pathlib import Path
from qa_contracts import DIMENSIONS, validate
from qa_runtime import case_status, current_snapshot, totals, verify_evidence, verify_observation
from qa_acceptance import LAYERS, LAYER_LABELS, assessment, readiness
from qa_store import QAError, SCHEMA_VERSION, digest, load, now, save

LABELS = {"passed": "通过", "failed": "失败", "blocked": "受阻", "skipped": "跳过",
          "not_run": "未执行", "flaky": "不稳定", "out_of_scope": "范围外",
          "inconclusive": "证据不足", "not_assessed": "本轮未评估", "deferred": "本轮未评估", "not_applicable": "有依据地不适用"}
DIMENSION_LABELS = {"functional": "功能与业务", "reliability": "稳定性与恢复",
                    "environment": "环境兼容", "delivery": "部署与复制", "cost": "成本负担", "evidence": "证据完整性"}


def checkpoint_results(row, directory):
    points = row["assessment"]["checkpoints"]
    if row["assessment"]["layer"] == "implementation" or row["status"] not in {"passed", "failed", "flaky"}:
        return {point: row["status"] for point in points}
    histories = {point: [] for point in points}
    for attempt in row["attempts"]:
        status = attempt["status"]
        payload = None
        if status in {"passed", "failed"}:
            payload = load(Path(directory) / "evidence" / row["id"] / str(attempt["attempt"]) / "observation.json")
        for point in points:
            state = status
            if payload is not None:
                assertions = [a for a in payload["assertions"] if a.get("checkpoint") == point]
                state = "failed" if any(not a["passed"] for a in assertions) else "passed" if assertions else "inconclusive"
            histories[point].append({"status": state})
    return {point: case_status(history) for point, history in histories.items()}


def evaluate(session, directory):
    plan = validate(session["plan"])
    if digest(plan) != session.get("plan_hash"):
        raise QAError("冻结方案校验失败")
    snapshot = current_snapshot(plan, directory)
    fresh = snapshot["complete"] and plan["snapshot"]["complete"] and snapshot["digest"] == plan["snapshot"]["digest"]
    rows, failures, gaps = [], [], []
    if not fresh:
        gaps.append("项目快照已变化或不完整，已有结果不能作为当前版本的通过证据")
    environment_hash = digest(plan["environment"])
    for case in plan["cases"]:
        attempts = session.get("results", {}).get(case["id"], [])
        status = case_status(attempts) if case["in_scope"] else "out_of_scope"
        issues = []
        if status in {"passed", "failed", "flaky"}:
            if not all(verify_evidence(a, directory) for a in attempts if a.get("status") in {"passed", "failed", "flaky"}):
                issues.append("原始证据缺失或校验不一致")
            if any(a.get("snapshot_digest") != plan["snapshot"]["digest"] or a.get("environment_hash") != environment_hash for a in attempts):
                issues.append("结果版本或环境不匹配")
            for attempt in attempts:
                if attempt.get("status") in {"passed", "failed", "flaky"}:
                    issues.extend(verify_observation(session, case, attempt, directory))
            if issues:
                status = "blocked"
        if not fresh and status in {"passed", "failed", "flaky"}:
            issues.append("需针对当前版本重新验证")
            status = "blocked"
        row = {"id": case["id"], "title": case["title"], "dimension": case["dimension"],
               "requirement_ids": case["requirement_ids"], "required": case["required"],
               "status": status, "attempts": attempts, "issues": issues, "assessment": assessment(case)}
        try:
            row["checkpoint_results"] = checkpoint_results(row, directory)
        except (QAError, KeyError, TypeError):
            issues.append("无法读取逐点观察，需重新核验证据")
            row["status"] = status = "blocked"
            row["checkpoint_results"] = {point: "blocked" for point in row["assessment"]["checkpoints"]}
        rows.append(row)
        if case["required"]:
            if status == "failed":
                failures.append(case["id"])
            elif status != "passed":
                gaps.append(f"{case['id']}：{LABELS.get(status, status)}")
    coverage = []
    for req in plan["requirements"]:
        matching = [r for r in rows if req["id"] in r["requirement_ids"] and r["status"] != "out_of_scope"]
        proven = any(r["required"] and r["status"] == "passed" for r in matching)
        coverage.append({"id": req["id"], "statement": req["statement"], "required": req["required"],
                         "status": req["status"], "sources": req["sources"], "case_ids": [r["id"] for r in matching],
                         "has_required_pass": proven})
        if req["required"] and (req["status"] != "confirmed" or not proven):
            gaps.append(f"{req['id']}：要求未确认或缺少范围内的门禁用例通过证据")
    used = totals(session)
    if used["execution_seconds"] > plan["limits"]["execution_seconds"] + 0.1:
        gaps.append("实际执行时间超出约定预算")
    if used["external_cost_reserved"] > plan["limits"]["max_external_cost"] or used["external_cost_actual_known"] > plan["limits"]["max_external_cost"]:
        gaps.append("外部费用超出约定预算")
    dimensions = {}
    for dimension in sorted(DIMENSIONS):
        scoped = [r for r in rows if r["dimension"] == dimension and r["status"] != "out_of_scope"]
        if not scoped:
            state = "not_assessed"
        elif any(r["status"] == "failed" for r in scoped):
            state = "failed"
        elif any(r["status"] != "passed" for r in scoped):
            state = "inconclusive"
        else:
            state = "passed"
        dimensions[dimension] = state
    acceptance = readiness(plan, snapshot)
    gaps.extend(acceptance["gaps"])
    by_id = {row["id"]: row for row in rows}
    for item in acceptance["obligations"]:
        matching = [by_id[cid] for cid in item["case_ids"]]
        states = [r["checkpoint_results"][item["checkpoint"]] for r in matching]
        item["status"] = ("failed" if "failed" in states else "flaky" if "flaky" in states else
                          "passed" if states and all(s == "passed" for s in states) else "inconclusive")
    layer_results = {}
    for layer in LAYERS:
        rule = acceptance["layers"].get(layer, {"status": "deferred"})
        obligations = [o for o in acceptance["obligations"] if o["layer"] == layer]
        selected = [r for r in rows if r["required"] and r["status"] != "out_of_scope" and r["assessment"]["layer"] == layer]
        if any(r["status"] == "failed" for r in selected):
            state = "failed"
        elif acceptance.get("layer_gaps", {}).get(layer):
            state = "inconclusive"
        elif rule["status"] != "required":
            state = "not_applicable" if rule["status"] == "not_applicable" else "not_assessed"
        elif not obligations or any(o["status"] != "passed" for o in obligations) or any(r["status"] != "passed" for r in selected):
            state = "inconclusive"
        else:
            state = "passed"
        layer_results[layer] = state
    acceptance["results"] = layer_results
    acceptance["methods"] = sorted({a["method"] for row in rows for a in row["attempts"] if a.get("method")})
    gate = "failed" if failures else "inconclusive" if gaps else "passed"
    product_accepted = gate == "passed" and acceptance["scope"] == "product"
    return {"schema_version": SCHEMA_VERSION, "generated_at": now(), "goal": plan["goal"], "scenario": plan["scenario"],
            "project_root": plan["project_root"], "environment": plan["environment"],
            "plan_hash": session["plan_hash"], "snapshot": snapshot, "fresh": fresh, "gate": gate,
            "blocking_failures": failures, "gaps": gaps, "dimensions": dimensions,
            "acceptance": acceptance, "product_accepted": product_accepted,
            "counts": dict(Counter(r["status"] for r in rows)), "coverage": coverage, "cases": rows,
            "usage": used, "limits": plan["limits"], "notes": session.get("notes", []),
            "feedback": plan.get("feedback", [])}


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def render(report, path):
    acceptance = report["acceptance"]
    scope_label = {"product": "本轮产品验收", "focused": "限定范围检查", "legacy": "历史方案复核"}[acceptance["scope"]]
    lines = ["# 验收测试报告", "", f"**本轮结论：{LABELS[report['gate']]}**", "",
             f"结论范围：{scope_label}；产品验收门禁：{'满足' if report['product_accepted'] else '未获得通过结论'}。", "",
             f"目标：{report['goal']}", f"场景：{report['scenario']}", f"项目：{report['project_root']}",
             f"生成时间（UTC）：{report['generated_at']}", f"方案标识：`{report['plan_hash']}`", "",
             "结论只覆盖本轮约定范围。范围外能力不作为本轮失败，也不意味着已经通过。", "",
             "## 三类验收结论", "", "| 板块 | 结论 |", "| --- | --- |"]
    for layer, status in acceptance["results"].items():
        lines.append(f"| {LAYER_LABELS[layer]} | {LABELS[status]} |")
    lines += ["", "需求适配通过仅代表已定义标准及任务匹配检查；不自动证明真实业务效果。Agent 走查不等于真实用户研究。",
              "", "## 自动推导的检查点", "", "| 任务 | 板块 | 检查点 | 用例 | 结论 |", "| --- | --- | --- | --- | --- |"]
    for item in acceptance["obligations"]:
        lines.append(f"| {cell(item['journey_id'] or '本轮')} | {LAYER_LABELS[item['layer']]} | {cell(item['checkpoint'])} | {', '.join(item['case_ids']) or '无'} | {LABELS[item['status']]} |")
    lines += ["", "## 未评估与不适用依据", ""]
    if acceptance["scope"] == "focused":
        lines.append(f"- 限定范围：{cell(acceptance['reason'])}；来源：{cell('; '.join(acceptance['sources']))}。")
    for exception in acceptance["exceptions"]:
        label = exception.get("layer") or exception.get("path") or f"{exception.get('journey_id')}/{exception.get('state')}"
        state = LABELS.get(exception.get("status"), "界面线索排除")
        lines.append(f"- {cell(label)}（{state}）：{cell(exception['reason'])}；来源：{cell('; '.join(exception['sources']))}。")
    lines += ["", "## 各维度结果", "", "| 维度 | 结论 |", "| --- | --- |"]
    for dimension, status in report["dimensions"].items():
        lines.append(f"| {DIMENSION_LABELS[dimension]} | {LABELS[status]} |")
    lines += ["", "## 阻断与证据缺口", ""]
    for failure in report["blocking_failures"]:
        lines.append(f"- 门禁用例 {failure} 失败；见原始执行记录。")
    lines += [f"- {gap}" for gap in report["gaps"]]
    if not report["blocking_failures"] and not report["gaps"]:
        lines.append("本轮已定义的门禁要求具有通过证据。业务适配性判断以用例及相应负责人验收为准。")
    lines += ["", "## 用例与证据", "", "| 编号 | 用例 | 结果 | 门禁 | 尝试次数 |", "| --- | --- | --- | --- | --- |"]
    for case in report["cases"]:
        lines.append(f"| {case['id']} | {cell(case['title'])} | {LABELS[case['status']]} | {'是' if case['required'] else '否'} | {len(case['attempts'])} |")
    for case in report["cases"]:
        if not case["attempts"]:
            continue
        lines += ["", f"### {case['id']} · {case['title']}"]
        for attempt in case["attempts"]:
            lines.append(f"- 第 {attempt['attempt']} 次：{LABELS.get(attempt['status'], attempt['status'])}；{cell(attempt.get('reason', attempt.get('note', '见证据')))}")
            for evidence in attempt.get("evidence", []):
                lines.append(f"  - [{evidence['path']}]({evidence['path']}) · SHA256 `{evidence['sha256']}`")
    lines += ["", "## 要求覆盖", "", "| 要求 | 确认状态 | 对应用例 | 来源 |", "| --- | --- | --- | --- |"]
    for req in report["coverage"]:
        lines.append(f"| {cell(req['id'] + ' ' + req['statement'])} | {req['status']} | {', '.join(req['case_ids']) or '无'} | {cell('; '.join(req['sources']))} |")
    used, limits = report["usage"], report["limits"]
    lines += ["", "## 测试投入", "", f"- 执行累计：{used['execution_seconds']:.3f} 秒；预算 {limits['execution_seconds']} 秒。",
              f"- 外部费用占用上界：{used['external_cost_reserved']} {limits['currency']}；预算 {limits['max_external_cost']}。",
              f"- 已提供的实际外部费用：{used['external_cost_actual_known']}；完整性：{'未完整提供' if used['cost_actual_incomplete'] else '已提供/无费用声明'}。",
              "- 模型与宿主费用由宿主计量；本工具不直接调用模型，也不将未获得的费用数据估算为零。", "",
              "## 方案反馈", ""]
    if report["feedback"]:
        for item in report["feedback"]:
            lines.append(f"- [{cell(item.get('kind', '待验证'))}] {cell(item.get('statement', ''))}；依据：{cell(item.get('evidence', '未提供'))}")
    else:
        lines.append("本轮未录入额外方案反馈；不据此推断不存在需求或架构问题。")
    lines += ["", "## 复测与适用限制", "",
              "- 同一版本重试使用原方案，保留首次失败；失败后成功记为不稳定。",
              "- 修复代码、改变环境或修改标准后新建一轮，在新快照中复测并记录原问题关联。",
              "- 该工具检查文件证据与记录一致性；computer use / 人工观察的语义判断由观察者负责。",
              "- 文件快照排除构建产物、依赖目录和本轮档案；外部服务、模型、浏览器及部署配置须另行核验。"]
    lines += [f"- {cell(note)}" for note in report["notes"]]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def report_session(directory):
    directory = Path(directory).resolve()
    report = evaluate(load(directory / "session.json"), directory)
    save(directory / "report.json", report)
    render(report, directory / "report.md")
    return report
