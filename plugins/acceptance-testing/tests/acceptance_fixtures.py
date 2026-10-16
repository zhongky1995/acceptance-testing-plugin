"""Explicitly scoped policy fixtures; fabricated observations are test data only."""


def focused_policy():
    return {"scope": "focused", "reason": "只验证本轮执行内核行为", "sources": ["隔离测试约定"],
            "surfaces": ["api"], "journeys": [], "surface_exclusions": [],
            "layers": {"implementation": {"status": "required"},
                       "need_fit": {"status": "deferred", "reason": "本轮不评审产品需求", "sources": ["隔离测试约定"]},
                       "interaction": {"status": "deferred", "reason": "本轮不做界面验收", "sources": ["隔离测试约定"]}}}


def product_policy():
    return {"scope": "product", "reason": "隔离协议测试中的完整任务", "sources": ["PRD.md"], "surfaces": ["gui"],
            "layers": {key: {"status": "required"} for key in ["implementation", "need_fit", "interaction"]},
            "journeys": [{"id": "J1", "title": "保存草稿", "role": "作者", "trigger": "需要稍后继续编辑", "entry": "/editor",
                          "outcome": "草稿可再次打开并继续编辑", "requirement_ids": ["R1"], "sources": ["PRD.md:1"],
                          "steps": [{"id": "S1", "action": "保存草稿", "feedback": "出现已保存状态"}],
                          "patterns": [{"name": "显式保存及状态反馈", "decision": "adopt", "reason": "降低保存状态的不确定性", "source": "PRD.md:1"}],
                          "states": {key: {"status": "required"} for key in ["loading", "empty", "error", "interrupted", "permission"]}}],
            "surface_exclusions": []}


def assurance_policy():
    from qa_policy import FEATURES
    return {"claim": "single_run", "reason": "离线协议内核回归，不推断业务可靠性", "sources": ["隔离测试约定"],
            "features": {k: {"status": "not_applicable", "reason": "本用例只验证协议机制", "sources": ["隔离测试约定"]} for k in FEATURES},
            "samples": [], "boundaries": []}


def add_product_samples(plan, root):
    from qa_store import file_hash
    plan["assurance"] = assurance_policy()
    plan["assurance"]["claim"] = "representative"
    for sid, name in [("A", "PRD.md"), ("B", "index.html")]:
        plan["assurance"]["samples"].append({"id": sid, "kind": "fixture", "path": name, "sha256": file_hash(root / name), "purpose": "协议回执测试数据；不代表实际浏览器执行", "factors": {}})
    for case in plan["cases"]:
        case["sample_ids"] = ["A", "B"]
    command = plan["cases"][0]
    receipts = [{"id": s["id"], "sha256": s["sha256"], "status": "passed"} for s in plan["assurance"]["samples"]]
    command["executor"]["argv"][2] = "import json,sys;json.dump(" + repr({"tests": [{"name": "save", "status": "passed"}], "sample_results": receipts}) + ",open(sys.argv[1],'w'))"


def bind_payload(plan, case, payload):
    from qa_policy import bindings
    payload["usage"] = {"requests": [], "reused_request_ids": []}
    payload["sample_ids"] = case.get("sample_ids", [])
    payload["assertions"] = [{**b, "actual": "synthetic protocol fixture", "passed": True, "evidence_indices": [0], "locator": "fixture:1", "trace_ids": [f"T{i}-{sid}" for sid in case.get("sample_ids", []) or ["none"]]} for i, b in enumerate(bindings(plan, case))]
    samples = {s["id"]: s for s in plan["assurance"]["samples"]}
    payload["sample_evidence"] = [{"id": sid, "sha256": samples[sid]["sha256"], "evidence_indices": [0], "locator": f"synthetic sample {sid}"} for sid in case.get("sample_ids", [])]
    if "execution" in payload:
        payload["execution"]["trace"] = [{"id": f"T{i}-{sid}", "sample_id": sid, "binding_id": b["binding_id"], "planned_action": b["planned_action"], "action": b["planned_action"], "visible_result": "synthetic fixture result", "evidence_indices": [0], "locator": "fixture:1"} for i, b in enumerate(bindings(plan, case)) for sid in case.get("sample_ids", []) or ["none"]]
    payload["method"] = payload.get("method") or "analysis"
    payload["actor_kind"] = payload.get("actor_kind") or "agent"
    return payload
