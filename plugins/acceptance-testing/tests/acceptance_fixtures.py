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
