"""Compare one observed workflow transition with a frozen fault-injection decision."""
from pathlib import Path

from qa_store import QAError, load


def text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_transition(row, *, expectation=False):
    if not isinstance(row, dict) or not all(text(row.get(k)) for k in ("stage", "fault", "run_id")):
        raise QAError("流程记录需要 stage、fault 和 run_id")
    if expectation:
        unknown = set(row) - {"stage", "fault", "run_id", "states", "next_inputs", "effects"}
        if unknown:
            raise QAError("未识别的流程预期字段：" + "、".join(sorted(unknown)))
    for key in ("states", "next_inputs", "effects"):
        values = row.get(key)
        if not isinstance(values, dict) or not all(text(k) for k in values):
            raise QAError(f"流程记录 {key} 需要按标识列出实际对象或动作")
    if expectation and not row["states"]:
        raise QAError("预期至少要核对一个对象或批次状态")
    if not all(text(state) for state in row["states"].values()):
        raise QAError("states 需要逐对象状态")
    for inputs in row["next_inputs"].values():
        if not isinstance(inputs, list) or not all(text(i) for i in inputs):
            raise QAError("next_inputs 需要逐阶段列出实际输入标识")
    if any(type(n) is not int or n < 0 for n in row["effects"].values()):
        raise QAError("effects 需要逐动作记录非负整数次数")


def read_result(plan, case, path, returncode, evidence_dir):
    """Only a bound observation with a raw trace can establish a product failure."""
    if returncode != 0:
        raise QAError(f"流程探针未正常完成（退出码 {returncode}），见本次执行日志")
    expected = case["workflow_expectation"]
    sample = next(s for s in plan["assurance"]["samples"] if s["id"] == case["sample_ids"][0])
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 25000000:
        raise QAError("流程探针未生成有效的本轮结果文件")
    actual = load(path)
    validate_transition(actual)
    if (actual.get("sample_id"), actual.get("sha256")) != (sample["id"], sample["sha256"]):
        raise QAError("探针回执与冻结样本不匹配")
    if (actual["stage"], actual["fault"]) != (expected["stage"], expected["fault"]):
        raise QAError("未观察到本例约定的注入阶段和故障")
    ref = actual.get("trace_file")
    if not text(ref) or Path(ref).is_absolute() or not text(actual.get("locator")):
        raise QAError("需要本次原始轨迹文件和具体位置")
    root = Path(evidence_dir).resolve()
    trace = root / ref
    if (not trace.resolve().is_relative_to(root) or trace.resolve() == path.resolve()
            or trace.resolve() != trace or not trace.is_file() or not trace.stat().st_size):
        raise QAError("原始轨迹须为本次证据目录内独立的非空文件")

    differences = []
    if actual["run_id"] != expected["run_id"]:
        differences.append("run_id")
    for field in ("states", "next_inputs", "effects"):
        want, got = expected[field], actual[field]
        for key in sorted(want.keys() | got.keys()):
            if field == "next_inputs" and key in want and key in got:
                matches = sorted(want[key]) == sorted(got[key])
            else:
                matches = want.get(key) == got.get(key)
            if not matches:
                differences.append(f"{field}.{key}")
    status = "failed" if differences else "passed"
    reason = "与冻结预期不符：" + "、".join(differences) if differences else "归属、下游实际输入与副作用符合冻结预期"
    return {"status": status, "tests": 1, "counts": {status: 1}, "reason": reason}
