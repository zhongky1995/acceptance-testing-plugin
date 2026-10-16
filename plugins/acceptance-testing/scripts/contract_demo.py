#!/usr/bin/env python3
"""Disposable, offline producer/consumer mismatch and repaired-version example."""
import argparse
import shutil
from pathlib import Path
from qa_policy import FEATURES
from qa_report import report_session
from qa_runtime import run
from qa_store import file_hash, project_snapshot, save


def make_plan(project, directory):
    boundary = {"id": "export", "producer": "contracts.py:producer_accepts", "consumer": "contracts.py:consumer_accepts", "reason": "序列化输出必须能被消费方接收"}
    samples = [{"id": variant, "kind": "fixture", "path": f"{variant}.json", "sha256": file_hash(project / f"{variant}.json"),
                "purpose": f"接口 {variant} 输入", "factors": {"interfaces": variant}} for variant in FEATURES["interfaces"]]
    save(project / "contract-spec.json", {"boundary": boundary, "argv": ["{python}", "adapter.py"],
         "samples": [{"id": s["id"], "path": s["path"], "expected_producer": s["id"] != "rejected", "expected_consumer": s["id"] != "rejected"} for s in samples]})
    features = {k: {"status": "required" if k == "interfaces" else "not_applicable", "reason": "本轮限定离线接口边界", "sources": ["README.md"]} for k in FEATURES}
    plan = {"schema_version": "1.2", "project_root": str(project), "scenario": "local-iteration", "goal": "确认上下游接受相同的合法输入",
            "snapshot": project_snapshot(project), "environment": {"mode": "offline-contract-demo"}, "allow_install": False,
            "limits": {"execution_seconds": 30, "max_attempts_per_case": 2, "max_external_cost": 0, "currency": "CNY"},
            "requirements": [{"id": "R1", "statement": "合法生产结果能被消费方接收", "status": "confirmed", "required": True, "sources": ["README.md"]}],
            "acceptance": {"scope": "focused", "reason": "仅检查序列化边界", "sources": ["README.md"], "surfaces": ["api"], "journeys": [],
                           "layers": {"implementation": {"status": "required"}, **{k: {"status": "deferred", "reason": "本轮不做产品或界面验收", "sources": ["README.md"]} for k in ("need_fit", "interaction")}}},
            "assurance": {"claim": "representative", "reason": "覆盖此边界的有效、上界及拒绝样本", "sources": ["README.md"], "features": features, "samples": samples, "boundaries": [boundary]},
            "cases": [{"id": "C1", "title": "生产与消费契约一致", "dimension": "functional", "requirement_ids": ["R1"], "required": True, "in_scope": True,
                       "expected": "三个样本的两端判断符合输入类别，合法生产输出不被拒绝", "sample_ids": [s["id"] for s in samples], "boundary_id": "export",
                       "executor": {"kind": "command", "adapter": "contract", "argv": ["{python}", "{plugin_root}/scripts/contract_check.py", "contract-spec.json", "{evidence_dir}/result.json"],
                                    "result_path": "{evidence_dir}/result.json", "timeout_seconds": 10, "external_calls": False}}]}
    save(directory / "plan.json", plan)
    return directory / "plan.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    output = Path(parser.parse_args().output).resolve()
    if output.exists():
        raise SystemExit("输出目录已存在，请使用新目录")
    project = output / "project"
    shutil.copytree(Path(__file__).resolve().parents[1] / "tests/fixtures/contract-project", project, ignore=shutil.ignore_patterns("__pycache__"))
    run(make_plan(project, output / "before"), output / "before")
    before = report_session(output / "before")
    source = project / "contracts.py"
    source.write_text(source.read_text().replace("len(value) <= 2", "len(value) <= 3"))
    run(make_plan(project, output / "after"), output / "after")
    after = report_session(output / "after")
    save(output / "comparison.json", {"before": before["gate"], "after": after["gate"], "product_accepted": after["product_accepted"]})
    print(f"契约初轮：{before['gate']}；修复后新轮：{after['gate']}；档案：{output}")
    return 0 if before["gate"] == "failed" and after["gate"] == "passed" and not after["product_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
