"""Versioned acceptance policy shared by every host, skill and CLI entry point."""
from qa_store import QAError

LAYERS = ("implementation", "need_fit", "interaction")
LAYER_LABELS = {"implementation": "实现符合性", "need_fit": "需求适配", "interaction": "交互与可用性"}
STATES = ("loading", "empty", "error", "interrupted", "permission")
SURFACES = {"gui", "cli", "api", "background", "unknown"}
METHODS = {"analysis", "ui_walkthrough", "human_observation"}


def need(ok, message):
    if not ok:
        raise QAError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def sources(value):
    return isinstance(value, list) and bool(value) and all(text(v) for v in value)


def assessment(case):
    # Unclassified technical cases can never satisfy business or interaction checks.
    return case.get("assessment", {"layer": "implementation", "checkpoints": ["outcome"]})


def template(scope="product"):
    return {"scope": scope, "reason": "", "sources": [], "surfaces": ["unknown"],
            "layers": {layer: {"status": "required"} for layer in LAYERS},
            "journeys": [], "surface_exclusions": []}


def validate_acceptance(plan):
    if plan["schema_version"] == "1.0":
        return  # History is readable; execution and product approval have separate guards.
    policy = plan.get("acceptance")
    need(isinstance(policy, dict), "缺少 acceptance；请用新版 init 建立验收范围")
    need(policy.get("scope") in {"product", "focused"}, "acceptance.scope 必须为 product 或 focused")
    need(text(policy.get("reason")) and sources(policy.get("sources")), "验收范围需要理由与来源")
    surfaces = policy.get("surfaces")
    need(isinstance(surfaces, list) and surfaces and all(s in SURFACES for s in surfaces), "需要声明产品入口类型")
    layers = policy.get("layers")
    need(isinstance(layers, dict) and set(layers) == set(LAYERS), "三类验收必须逐项声明，不得省略")
    for layer, rule in layers.items():
        need(isinstance(rule, dict) and rule.get("status") in {"required", "deferred", "not_applicable"}, "验收适用状态无效")
        if rule["status"] != "required":
            need(text(rule.get("reason")) and sources(rule.get("sources")), f"{layer} 未评估/不适用需要理由与来源")
        if policy["scope"] == "product" and layer in {"implementation", "need_fit"}:
            need(rule["status"] == "required", "整体验收不能略过实现或需求适配")
        if layer == "interaction" and rule["status"] == "not_applicable":
            need(not set(surfaces) & {"gui", "cli", "unknown"}, "存在用户入口或入口未知，交互不能声明不适用")
        if policy["scope"] == "product":
            need(rule["status"] != "deferred", "整体验收的必要板块不能延期后仍申请整体通过")
    need(any(rule["status"] == "required" for rule in layers.values()), "本轮至少需要一类必要验收")
    journeys = policy.get("journeys")
    need(isinstance(journeys, list), "journeys 必须是列表")
    by_id = {}
    req_ids = {r["id"] for r in plan["requirements"]}
    for journey in journeys:
        need(isinstance(journey, dict), "任务必须是对象")
        for key in ["id", "title", "role", "trigger", "entry", "outcome"]:
            need(text(journey.get(key)), f"任务缺少 {key}")
        need(journey["id"] not in by_id, "任务编号重复")
        by_id[journey["id"]] = journey
        need(sources(journey.get("sources")), "任务需要独立于实现的依据")
        refs = journey.get("requirement_ids")
        need(isinstance(refs, list) and refs and all(r in req_ids for r in refs), "任务要求对应关系无效")
        steps = journey.get("steps")
        need(isinstance(steps, list) and steps, "任务需要预期路径")
        ids = set()
        for step in steps:
            need(isinstance(step, dict) and all(text(step.get(k)) for k in ["id", "action", "feedback"]), "路径步骤需要编号、动作和可见反馈")
            need(step["id"] not in ids, "路径步骤编号重复")
            ids.add(step["id"])
        patterns = journey.get("patterns", [])
        need(isinstance(patterns, list), "patterns 必须是列表")
        for pattern in patterns:
            need(isinstance(pattern, dict) and all(text(pattern.get(k)) for k in ["name", "reason", "source"])
                 and pattern.get("decision") in {"adopt", "adapt", "not_applicable"}, "常规模式需要来源、适用判断及理由")
        states = journey.get("states", {})
        need(isinstance(states, dict) and set(states) <= set(STATES), "未知的交互状态")
        for state in states.values():
            need(isinstance(state, dict) and state.get("status") in {"required", "not_applicable", "deferred"}, "交互状态适用性无效")
            need(state["status"] != "deferred" or policy["scope"] == "focused", "整体验收不能延期适用状态")
            if state["status"] != "required":
                need(text(state.get("reason")) and sources(state.get("sources")), "跳过交互状态需要理由与来源")
    exclusions = policy.get("surface_exclusions", [])
    need(isinstance(exclusions, list), "surface_exclusions 必须是列表")
    for item in exclusions:
        need(isinstance(item, dict) and text(item.get("path")) and text(item.get("reason"))
             and sources(item.get("sources")), "排除界面线索需要路径、理由与依据")
    for case in plan["cases"]:
        item = assessment(case)
        need(isinstance(item, dict) and item.get("layer") in LAYERS, "用例验收层面无效")
        if case["required"]:
            need(layers[item["layer"]]["status"] == "required", "必需用例的所属板块不能同时声明未评估或不适用")
        points = item.get("checkpoints")
        need(isinstance(points, list) and points and all(text(p) for p in points) and len(points) == len(set(points)), "用例需要不重复的检查点")
        journey_id = item.get("journey_id")
        if journey_id is not None:
            need(journey_id in by_id, "用例对应的任务不存在")
            need(set(case["requirement_ids"]) & set(by_id[journey_id]["requirement_ids"]), "用例与任务必须关联同一要求")
        if item["layer"] != "implementation":
            need(journey_id in by_id, "需求适配与交互检查必须对应用户任务")
            need(case["executor"]["kind"] == "observation", "语义/交互检查必须导入观察，命令成功不能替代")


def expected_points(layer, journey):
    if layer == "implementation":
        return ["outcome"]
    if layer == "need_fit":
        return ["goal_alignment", "workflow_fit"]
    return (["entry", "comprehension", "feedback", "completion"]
            + [f"step:{s['id']}" for s in journey["steps"]]
            + [f"state:{name}" for name, state in journey.get("states", {}).items() if state["status"] == "required"])


def matching_cases(plan, layer, journey_id, point):
    return [c for c in plan["cases"] if c["required"] and c["in_scope"]
            and assessment(c)["layer"] == layer and assessment(c).get("journey_id") == journey_id
            and point in assessment(c)["checkpoints"]]


def readiness(plan, snapshot=None):
    """Derive obligations, never trust an agent's aggregate 'coverage complete' flag."""
    if plan["schema_version"] == "1.0":
        return {"scope": "legacy", "obligations": [], "exceptions": [], "layers": {},
                "gaps": ["旧方案未声明三类验收；只能解释历史，不能获得新版整体通过"]}
    policy = plan["acceptance"]
    gaps, obligations, exceptions = [], [], []
    layer_gaps = {layer: [] for layer in LAYERS}

    def gap(message, layer):
        gaps.append(message)
        layer_gaps[layer].append(message)

    if "unknown" in policy["surfaces"]:
        gap("产品入口类型尚未核实", "interaction")
    if "gui" not in policy["surfaces"]:
        excluded = {i["path"] for i in policy.get("surface_exclusions", [])}
        for signal in (snapshot or plan["snapshot"]).get("ui_signals", []):
            if signal not in excluded:
                gap(f"发现界面线索 {signal}；声明 gui 或提供排除依据", "interaction")
    exceptions.extend(policy.get("surface_exclusions", []))
    for layer, rule in policy["layers"].items():
        if rule["status"] != "required":
            exceptions.append({"layer": layer, **rule})
            continue
        journeys = policy["journeys"]
        if not journeys and layer != "implementation":
            gap(f"{LAYER_LABELS[layer]}：缺少关键用户任务", layer)
        targets = journeys or ([None] if layer == "implementation" else [])
        for journey in targets:
            jid = journey["id"] if journey else None
            if journey and layer == "interaction":
                if not journey.get("patterns"):
                    gap(f"{jid}：未评估常规交互模式的适用性", layer)
                for state in STATES:
                    if state not in journey.get("states", {}):
                        gap(f"{jid}：尚未判断 {state} 状态是否适用", layer)
                    elif journey["states"][state]["status"] != "required":
                        exceptions.append({"journey_id": jid, "state": state, **journey["states"][state]})
            for point in expected_points(layer, journey):
                cases = matching_cases(plan, layer, jid, point)
                item = {"layer": layer, "journey_id": jid, "checkpoint": point, "case_ids": [c["id"] for c in cases]}
                obligations.append(item)
                if not cases:
                    gap(f"{jid or '本轮'}/{layer}/{point}：缺少范围内的必需用例", layer)
    return {"scope": policy["scope"], "reason": policy["reason"], "sources": policy["sources"],
            "surfaces": policy["surfaces"], "layers": policy["layers"], "obligations": obligations,
            "exceptions": exceptions, "gaps": gaps, "layer_gaps": layer_gaps}


def baseline_blocker(plan, case, statuses):
    item = assessment(case)
    policy = plan.get("acceptance", {})
    if item["layer"] != "interaction" or policy.get("layers", {}).get("need_fit", {}).get("status") != "required":
        return None
    for point in ["goal_alignment", "workflow_fit"]:
        cases = matching_cases(plan, "need_fit", item["journey_id"], point)
        if not cases or not all(statuses.get(c["id"]) == "passed" for c in cases):
            return "交互检查前需完成同一任务的需求与路径基线核对"
    return None


def observation_issues(plan, case, payload):
    """Validate point-level observations, not the truth of their semantic judgment."""
    item = assessment(case)
    if item["layer"] == "implementation" or payload.get("status") in {"blocked", "skipped"}:
        return []
    issues = []
    method, actor = payload.get("method"), payload.get("actor_kind")
    if method not in METHODS or actor not in {"agent", "human"}:
        issues.append("需要真实观察方法与执行者类型")
    if method == "human_observation" and actor != "human":
        issues.append("Agent 走查不能登记为真实用户观察")
    if item["layer"] == "interaction" and method not in {"ui_walkthrough", "human_observation"}:
        issues.append("接口结果或文档分析不能替代交互走查")
    files = payload.get("evidence_files", [])

    def linked(value):
        return (isinstance(value, list) and bool(value) and all(type(v) is int and 0 <= v < len(files) for v in value))

    assertions = payload.get("assertions", [])
    for point in item["checkpoints"]:
        found = [a for a in assertions if a.get("checkpoint") == point]
        if not found or any(not text(a.get("expected")) or not text(a.get("actual")) or not linked(a.get("evidence_indices")) for a in found):
            issues.append(f"{point}：缺少预期、实际与原始文件对应关系")
    if item["layer"] == "interaction":
        execution = payload.get("execution", {})
        if not isinstance(execution, dict):
            return issues + ["缺少实际界面操作记录"]
        if execution.get("surface") not in {"gui", "cli"} or execution.get("surface") not in plan["acceptance"]["surfaces"]:
            issues.append("走查入口与方案的用户界面类型不一致")
        if not text(execution.get("entry")) or type(execution.get("backend_bypass")) is not bool or execution.get("backend_bypass"):
            issues.append("需要实际用户入口；后台绕过不能证明交互通过")
        if execution.get("source_access") not in {"none", "implementation-informed"}:
            issues.append("需声明走查是否利用了实现知识")
        if not isinstance(execution.get("assistance"), list) or not all(text(v) for v in execution["assistance"]):
            issues.append("需记录辅助说明/人工补救，无辅助填写空列表")
        trace = execution.get("trace")
        if not isinstance(trace, list) or not trace or any(not isinstance(s, dict) or not text(s.get("action"))
                or not text(s.get("visible_result")) or not linked(s.get("evidence_indices")) for s in trace):
            issues.append("缺少有原始文件定位的实际操作轨迹")
    return issues
