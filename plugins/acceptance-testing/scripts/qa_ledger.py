"""Per-attempt usage receipts and preflight reservations; never infer unknown = zero."""
import math
from qa_store import QAError


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_limits(plan):
    if plan["schema_version"] != "1.2":
        return
    for name in ("max_external_calls", "max_external_tokens"):
        value = plan["limits"].get(name, 0)
        if type(value) is not int or value < 0:
            raise QAError(f"{name} 必须为非负整数")
    for case in plan["cases"]:
        ex = case["executor"]
        for name in ("external_call_bound", "external_token_bound"):
            value = ex.get(name, 0)
            if type(value) is not int or value < 0:
                raise QAError(f"{name} 必须为非负整数")
        if ex.get("external_calls") and ex.get("external_call_bound", 0) < 1:
            raise QAError("外部调用需声明请求数上界，收费未知也不能无限调用")


def prior_events(session):
    events = {}
    for runs in session["results"].values():
        for run in runs:
            for event in run.get("usage", {}).get("requests", []):
                if isinstance(event, dict) and isinstance(event.get("id"), str):
                    events.setdefault(event["id"], event)
    return events


def usage_issues(case, payload, previous=None):
    usage = payload.get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("requests"), list) or not isinstance(usage.get("reused_request_ids", []), list):
        return ["缺少 usage 请求账本；离线也须明确 requests: []"]
    issues, seen = [], set()
    events = usage["requests"]
    for event in events:
        if not isinstance(event, dict):
            issues.append("请求账本条目无效")
            continue
        eid = event.get("id")
        if not isinstance(eid, str) or not eid.strip() or eid in seen:
            issues.append("请求编号缺失或重复")
        else:
            seen.add(eid)
            if previous is not None and eid in previous:
                issues.append("已计量请求应使用 reused_request_ids，不能重复记为新调用")
        if event.get("status") not in {"succeeded", "failed", "unknown"}:
            issues.append("请求需要实际完成状态")
        if event.get("status") == "unknown":
            issues.append("请求结果未知，不能获得通过结论")
        if "tokens" not in event or (event["tokens"] is not None and (type(event["tokens"]) is not int or event["tokens"] < 0)):
            issues.append("tokens 必须为非负整数或明确 null")
        if "cost" not in event or (event["cost"] is not None and not finite(event["cost"])):
            issues.append("费用必须为非负数或明确 null")
        if not isinstance(event.get("evidence"), str) or not event["evidence"].strip():
            issues.append("请求需要原始记录定位")
    reused = usage.get("reused_request_ids", [])
    if any(not isinstance(eid, str) for eid in reused) or len(set(str(e) for e in reused)) != len(reused):
        issues.append("复用请求编号无效")
    elif previous is not None and any(eid not in previous for eid in reused):
        issues.append("只能复用本轮已记录请求；历史材料按 recorded 样本处理")
    reported = payload.get("external_cost_actual")
    known_cost = sum(e["cost"] for e in events if isinstance(e, dict) and finite(e.get("cost")))
    if reported is not None and finite(reported) and (not all(isinstance(e, dict) and finite(e.get("cost")) for e in events) or abs(reported - known_cost) > 1e-9):
        issues.append("旧实际费用字段与逐请求账本不一致；请保留原始费用并补齐账本")
    ex = case["executor"]
    if events and not ex.get("external_calls"):
        issues.append("实际外部调用与无调用声明冲突")
    if ex.get("external_calls") and not events:
        issues.append("声明外部执行但没有请求记录；未执行须记为受阻或跳过")
    if len(events) > ex.get("external_call_bound", 0):
        issues.append("实际请求数超出预留上界")
    tokens = sum(e.get("tokens", 0) or 0 for e in events if isinstance(e, dict) and (e.get("tokens") is None or type(e.get("tokens")) is int))
    cost = sum(e.get("cost", 0) or 0 for e in events if isinstance(e, dict) and (e.get("cost") is None or finite(e.get("cost"))))
    if tokens > ex.get("external_token_bound", 0):
        issues.append("实际 token 超出预留上界")
    if cost > ex.get("external_cost_bound", 0):
        issues.append("实际费用超出预留上界")
    if ex.get("external_calls") and any(e.get("tokens") is None for e in events if isinstance(e, dict)) and ex.get("external_token_bound", 0) == 0:
        issues.append("token 未知且没有 token 上界")
    if ex.get("external_calls") and any(e.get("cost") is None for e in events if isinstance(e, dict)) and ex.get("external_cost_bound", 0) == 0:
        issues.append("费用未知且没有费用上界；免费须明确 cost: 0")
    return issues


def usage_fields(case, payload):
    usage = payload.get("usage", {})
    if not isinstance(usage, dict) or not isinstance(usage.get("requests"), list):
        usage = {"requests": [], "incomplete": True}
    events = [e for e in usage["requests"] if isinstance(e, dict)]
    actual = sum(e["cost"] for e in events if finite(e.get("cost")))
    known = bool(events) and all(finite(e.get("cost")) for e in events)
    ex = case["executor"]
    return {"usage": usage, "external_declared": ex.get("external_calls", False),
            "call_reserved": ex.get("external_call_bound", 0), "token_reserved": ex.get("external_token_bound", 0),
            "cost_reserved": ex.get("external_cost_bound", 0),
            "cost_actual": actual if known or not ex.get("external_calls") else None}


def totals(session, exclude_check=None):
    attempts = [a for entries in session["results"].values() for a in entries]
    pending = [c for key, c in session.get("checks", {}).items() if not c.get("consumed") and key != exclude_check]
    events, duplicate = {}, False
    for a in attempts:
        for event in a.get("usage", {}).get("requests", []):
            if not isinstance(event, dict):
                continue
            eid = event.get("id")
            if not isinstance(eid, str):
                continue
            if eid in events:
                duplicate = True
            else:
                events[eid] = event
    values = list(events.values())
    missing = any(a.get("external_declared") and not a.get("usage", {}).get("requests") for a in attempts)
    unsettled = any(c.get("call_reserved", 0) for c in pending)
    cost_known = sum(e["cost"] for e in values if finite(e.get("cost")))
    tokens_known = sum(e["tokens"] for e in values if type(e.get("tokens")) is int and e["tokens"] >= 0)
    # Keep each attempt's conservative reservation, including failures and missing receipts.
    cost_reserved = sum(max(a.get("cost_reserved", 0), a.get("cost_actual") or 0) for a in attempts + pending)
    calls_reserved = sum(max(a.get("call_reserved", 0), len(a.get("usage", {}).get("requests", []))) for a in attempts + pending)
    tokens_reserved = sum(max(a.get("token_reserved", 0), sum(e.get("tokens") or 0 for e in a.get("usage", {}).get("requests", [])
                             if isinstance(e, dict) and (e.get("tokens") is None or type(e.get("tokens")) is int))) for a in attempts + pending)
    return {"execution_seconds": sum(a.get("duration_seconds", 0) for a in attempts),
            "command_seconds": sum(a.get("duration_seconds", 0) for a in attempts if a.get("evidence_origin") != "host_observation"),
            "observation_window_seconds": sum(a.get("duration_seconds", 0) for a in attempts if a.get("evidence_origin") == "host_observation"),
            "external_cost_reserved": cost_reserved, "external_cost_actual_known": cost_known,
            "external_calls_actual": len(values), "calls_actual_incomplete": missing or unsettled, "external_calls_reserved": calls_reserved,
            "external_tokens_actual_known": tokens_known, "external_tokens_reserved": tokens_reserved,
            "cost_actual_incomplete": duplicate or any(e.get("cost") is None for e in values) or any(a.get("external_declared") and not a.get("usage", {}).get("requests") for a in attempts) or any(c.get("call_reserved", 0) for c in pending),
            "tokens_actual_incomplete": missing or unsettled or any(e.get("tokens") is None for e in values),
            "duplicate_requests": duplicate, "pending_checks": len(pending),
            "host_overhead": "未自动计量宿主对话、规划或平台开销；本账本覆盖已登记测试活动"}
