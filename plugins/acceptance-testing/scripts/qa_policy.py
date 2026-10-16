"""Cheap, host-neutral coverage and evidence constraints. No model or service calls."""
from datetime import datetime
from pathlib import Path
from qa_acceptance import assessment
from qa_store import QAError, digest, file_hash

FEATURES = {
    "collections": ("empty", "typical", "limit"),
    "interfaces": ("accepted", "boundary", "rejected"),
    "persistent_state": ("new", "existing", "repeat"),
    "async_jobs": ("success", "error", "interrupted"),
    "variable_output": ("typical", "format_variation", "rejection"),
}
CLAIMS = ("single_run", "representative", "sustained")


def need(ok, message):
    if not ok:
        raise QAError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def template():
    return {"claim": "single_run", "reason": "", "sources": [],
            "features": {name: {"status": "unknown", "reason": "", "sources": []} for name in FEATURES},
            "samples": [], "boundaries": []}


def validate_policy(plan):
    if plan["schema_version"] != "1.2":
        return
    p = plan.get("assurance")
    need(isinstance(p, dict) and p.get("claim") in CLAIMS, "需要 assurance 结论强度声明")
    need(text(p.get("reason")) and isinstance(p.get("sources"), list) and p["sources"] and all(text(s) for s in p["sources"]), "结论强度需要理由和来源")
    features = p.get("features")
    need(isinstance(features, dict) and set(features) == set(FEATURES), "五类风险适用性必须逐项声明")
    for name, rule in features.items():
        need(isinstance(rule, dict) and rule.get("status") in {"required", "not_applicable", "deferred", "unknown"}, "风险适用性无效")
        if rule["status"] != "unknown":
            need(text(rule.get("reason")) and isinstance(rule.get("sources"), list) and rule["sources"]
                 and all(text(s) for s in rule["sources"]), f"{name} 需要适用依据")
        need(rule["status"] != "deferred" or plan["acceptance"]["scope"] == "focused", "产品验收不能延期适用风险")
    samples = p.get("samples")
    need(isinstance(samples, list), "samples 必须是列表")
    ids = set()
    for sample in samples:
        need(isinstance(sample, dict) and text(sample.get("id")) and sample["id"] not in ids, "样本编号缺失或重复")
        ids.add(sample["id"])
        need(sample.get("kind") in {"fixture", "recorded", "live"} and text(sample.get("purpose")), "样本需要类型和选择理由")
        need(isinstance(sample.get("path"), str) and not Path(sample["path"]).is_absolute(), "样本路径必须相对项目")
        path = (Path(plan["project_root"]) / sample["path"]).resolve()
        need(path.is_relative_to(Path(plan["project_root"]).resolve()) and path.is_file(), "样本必须是项目内现有输入文件")
        need(isinstance(sample.get("sha256"), str) and len(sample["sha256"]) == 64, "样本需要冻结内容摘要")
        factors = sample.get("factors", {})
        need(isinstance(factors, dict) and all(k in FEATURES and v in FEATURES[k] for k, v in factors.items()), "样本风险变体无效")
    for c in plan["cases"]:
        expectations = c.get("point_expectations", {})
        need(isinstance(expectations, dict) and set(expectations) <= set(assessment(c)["checkpoints"]) and all(text(v) for v in expectations.values()), "逐点预期必须对应已有检查点且非空")
        refs = c.get("sample_ids", [])
        need(isinstance(refs, list) and all(text(s) for s in refs) and len(refs) == len(set(refs)) and set(refs) <= ids, "用例样本引用无效")
        if refs and c["executor"]["kind"] == "command":
            need(c["executor"]["adapter"] in {"native", "contract"}, "样本用例需 native/contract 结果逐项回执")
    boundaries = p.get("boundaries")
    need(isinstance(boundaries, list), "boundaries 必须是列表")
    bids = set()
    for b in boundaries:
        need(isinstance(b, dict) and text(b.get("id")) and b["id"] not in bids, "边界编号缺失或重复")
        bids.add(b["id"])
        need(all(text(b.get(k)) for k in ("producer", "consumer", "reason")), "边界需要上下游真实实现来源及选择理由")
    for c in plan["cases"]:
        if c["executor"].get("adapter") == "contract":
            need(c.get("boundary_id") in bids and c.get("sample_ids"), "契约用例必须绑定边界和样本")
    if p["claim"] == "sustained":
        repeat = p.get("repeat", {})
        need(type(repeat.get("min_runs")) is int and 2 <= repeat["min_runs"] <= plan["limits"]["max_attempts_per_case"], "持续观察需要预算内至少两次运行")
        need(type(repeat.get("min_span_seconds")) in (int, float) and 0 < repeat["min_span_seconds"] <= plan["limits"]["execution_seconds"], "持续观察窗口必须明确且在预算内")


def coverage(plan, statuses=None, results=None):
    """A fixed small applicability matrix, not a promise to discover all requirements."""
    if plan["schema_version"] != "1.2":
        return {"claim": "legacy", "gaps": ["历史协议缺少风险、样本与计量约束；不能升级为新版验收结论"], "matrix": []}
    p = plan["assurance"]
    gaps, matrix = [], []
    samples = {s["id"]: s for s in p["samples"]}
    selected = [c for c in plan["cases"] if c["in_scope"] and c["required"]]
    def usable(c):
        return statuses is None or statuses.get(c["id"]) == "passed"
    for s in samples.values():
        try:
            if file_hash(Path(plan["project_root"]) / s["path"]) != s["sha256"]:
                gaps.append(f"样本 {s['id']} 内容与冻结摘要不符")
        except OSError:
            gaps.append(f"样本 {s['id']} 无法读取")
    for name, rule in p["features"].items():
        if rule["status"] == "unknown":
            gaps.append(f"{name} 适用性尚未判断")
        if rule["status"] != "required":
            continue
        for variant in FEATURES[name]:
            matching = [c for c in selected if any(samples[s].get("factors", {}).get(name) == variant for s in c.get("sample_ids", []))]
            ids = [c["id"] for c in matching]
            proven = any(usable(c) for c in matching)
            matrix.append({"feature": name, "variant": variant, "case_ids": ids, "covered": proven})
            if not proven:
                gaps.append(f"{name}/{variant} 缺少必需样本用例{'通过证据' if statuses is not None else ''}")
    if p["features"]["interfaces"]["status"] == "required" and not p["boundaries"]:
        gaps.append("接口风险适用但未声明上下游边界")
    for boundary in p["boundaries"]:
        for variant in FEATURES["interfaces"]:
            matches = [c for c in selected if c.get("boundary_id") == boundary["id"] and c["executor"].get("adapter") == "contract"
                       and any(samples[s].get("factors", {}).get("interfaces") == variant for s in c.get("sample_ids", []))]
            if not any(usable(c) for c in matches):
                gaps.append(f"边界 {boundary['id']}/{variant} 缺少真实双向契约检查")
    if p["claim"] != "single_run":
        targets = [(j["id"], layer) for j in plan["acceptance"]["journeys"]
                   for layer, rule in plan["acceptance"]["layers"].items() if rule["status"] == "required"] or [(None, "implementation")]
        for jid, layer in targets:
            hashes = {samples[s]["sha256"] for c in selected if usable(c) and assessment(c).get("journey_id") == jid
                      and assessment(c)["layer"] == layer for s in c.get("sample_ids", [])}
            if len(hashes) < 2:
                gaps.append(f"{jid or '本轮'}/{layer} 代表性结论至少需要两份内容不同的输入样本；数量不代表统计可靠性")
    if p["claim"] == "sustained" and results is not None:
        for c in selected:
            runs = results.get(c["id"], [])
            passed = [a for a in runs if a.get("status") == "passed"]
            try:
                span = (datetime.fromisoformat(passed[-1]["finished_at"]) - datetime.fromisoformat(passed[0]["started_at"])).total_seconds() if passed else 0
            except (ValueError, KeyError):
                span = 0
            if len(passed) < p["repeat"]["min_runs"] or span < p["repeat"]["min_span_seconds"] or any(a.get("status") != "passed" for a in runs):
                gaps.append(f"{c['id']} 未满足声明的持续观察次数/窗口或含非通过记录")
    return {"claim": p["claim"], "reason": p["reason"], "features": p["features"], "samples": p["samples"],
            "boundaries": p["boundaries"], "matrix": matrix, "gaps": gaps,
            "limit": "代表性仅相对于声明的任务与样本矩阵；持续观察仅相对于声明窗口，不保证未来或全部需求。"}


def bindings(plan, case):
    result = []
    item = assessment(case)
    journey = next((j for j in plan["acceptance"]["journeys"] if j["id"] == item.get("journey_id")), None)
    for point in item["checkpoints"]:
        expected = case.get("point_expectations", {}).get(point, case["expected"])
        action = point
        if journey:
            expected = f"任务 {journey['id']}（{journey['title']}）：{journey['outcome']}；{point}：{expected}"
            step = next((s for s in journey["steps"] if point == f"step:{s['id']}"), None)
            if step:
                action, expected = step["action"], f"任务 {journey['id']} / {point}：{step['action']} → {step['feedback']}"
        bound = {"plan": digest(plan), "case": case["id"], "point": point, "expected": expected, "samples": case.get("sample_ids", [])}
        result.append({"checkpoint": point, "expected": expected, "binding_id": digest(bound), "planned_action": action})
    return result


def binding_issues(plan, case, payload):
    if plan["schema_version"] != "1.2" or payload.get("status") in {"blocked", "skipped"}:
        return []
    issues = []
    if payload.get("sample_ids", []) != case.get("sample_ids", []):
        issues.append("实际样本列表与冻结用例不一致")
    samples = {s["id"]: s for s in plan["assurance"]["samples"]}
    sample_evidence = payload.get("sample_evidence", [])
    for sid in case.get("sample_ids", []):
        found = [s for s in sample_evidence if isinstance(s, dict) and s.get("id") == sid]
        if len(found) != 1 or found[0].get("sha256") != samples[sid]["sha256"] or not text(found[0].get("locator")) or not found[0].get("evidence_indices") or any(type(i) is not int or not 0 <= i < len(payload.get("evidence_files", [])) for i in found[0].get("evidence_indices", [])):
            issues.append(f"样本 {sid} 缺少独立的内容及观察证据定位")
    assertions = payload.get("assertions", [])
    trace = payload.get("execution", {}).get("trace", [])
    expected_bindings = bindings(plan, case)
    if len(assertions) != len(expected_bindings):
        issues.append("断言必须逐点对应，不能重复或夹带未冻结检查点")
    for bound in expected_bindings:
        found = [a for a in assertions if a.get("checkpoint") == bound["checkpoint"]]
        if len(found) != 1 or any(a.get(k) != bound[k] for a in found for k in ("expected", "binding_id")):
            issues.append(f"{bound['checkpoint']} 预期/绑定与冻结方案不一致")
            continue
        a = found[0]
        if not text(a.get("locator")):
            issues.append(f"{bound['checkpoint']} 缺少原始文件内定位")
        if assessment(case)["layer"] == "interaction":
            matching = [t for t in trace if t.get("id") in a.get("trace_ids", [])]
            if not matching or len(matching) != len(a.get("trace_ids", [])) or any(
                t.get("binding_id") != bound["binding_id"] or t.get("planned_action") != bound["planned_action"]
                or not text(t.get("locator")) or not set(t.get("evidence_indices", [])) & set(a.get("evidence_indices", [])) for t in matching):
                issues.append(f"{bound['checkpoint']} 缺少对应动作及反馈的专属轨迹")
            for sid in case.get("sample_ids", []):
                if not any(t.get("sample_id") == sid for t in matching):
                    issues.append(f"{bound['checkpoint']}/{sid} 缺少逐样本轨迹")
    if assessment(case)["layer"] == "interaction" and (len({t.get("id") for t in trace}) != len(trace)):
        issues.append("轨迹编号重复")
    return issues


def result_issues(plan, case, data, require_pass=True):
    """Structured command receipts prove what the project adapter actually checked."""
    issues = []
    samples = {s["id"]: s for s in plan["assurance"]["samples"]}
    actual = data.get("sample_results", [])
    if case.get("sample_ids"):
        if not isinstance(actual, list):
            return ["样本执行回执无效"]
        for sid in case["sample_ids"]:
            matches = [r for r in actual if isinstance(r, dict) and r.get("id") == sid]
            if len(matches) != 1 or matches[0].get("sha256") != samples[sid]["sha256"] or matches[0].get("status") not in ({"passed"} if require_pass else {"passed", "failed"}):
                issues.append(f"样本 {sid} 缺少匹配内容的通过回执")
    if case["executor"].get("adapter") == "contract":
        b = next(b for b in plan["assurance"]["boundaries"] if b["id"] == case["boundary_id"])
        for row in actual:
            if row.get("id") in case.get("sample_ids", []):
                variant = samples[row["id"]].get("factors", {}).get("interfaces")
                expected = variant != "rejected"
                if variant not in FEATURES["interfaces"] or row.get("expected_producer") is not expected or row.get("expected_consumer") is not expected:
                    issues.append("契约回执的预期与冻结输入类别不一致")
        for k in ("id", "producer", "consumer"):
            if data.get("boundary", {}).get(k) != b[k]:
                issues.append("契约输出未绑定冻结的上下游实现")
    return issues
