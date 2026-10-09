"""Bounded serial execution, frozen plans, preserved attempts and evidence."""
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from qa_adapters import parse
from qa_contracts import need, number, validate
from qa_acceptance import assessment, baseline_blocker, observation_issues
from qa_store import QAError, SCHEMA_VERSION, digest, file_hash, load, now, project_snapshot, redact, save


@contextlib.contextmanager
def session_lock(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = directory / ".lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            pid = int(lock.read_text())
            os.kill(pid, 0)
        except (ProcessLookupError, ValueError):
            lock.unlink(missing_ok=True)
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        else:
            raise QAError("本轮已有执行进程，请等待或停止该进程")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield directory
    finally:
        lock.unlink(missing_ok=True)


def current_snapshot(plan, directory):
    return project_snapshot(plan["project_root"], [directory])


def open_session(plan_path, directory):
    plan = validate(load(plan_path))
    need(plan["schema_version"] == SCHEMA_VERSION, "旧方案仅支持历史报告；请用新版 init 建立新轮次，不能降级绕过验收协议")
    directory = Path(directory).resolve()
    need(not Path(plan["project_root"]).resolve().is_relative_to(directory), "档案目录不能等于项目根目录或其祖先，避免排除整个被测项目")
    current = current_snapshot(plan, directory)
    need(current["complete"] and plan["snapshot"]["complete"], "快照不完整，先缩小项目范围或补齐条件")
    need(current["digest"] == plan["snapshot"]["digest"], "项目已变化，请新建一轮方案；不能沿用旧快照执行")
    path = directory / "session.json"
    if path.exists():
        session = load(path)
        need(session.get("plan_hash") == digest(plan), "本轮方案已冻结；改变标准、环境或范围需要新建一轮")
    else:
        session = {"schema_version": SCHEMA_VERSION, "created_at": now(), "plan_hash": digest(plan),
                   "plan": plan, "results": {}, "checks": {}, "notes": []}
        save(path, session)
        save(directory / "frozen-plan.json", plan)
    return session


def case_status(attempts):
    if not attempts:
        return "not_run"
    latest = attempts[-1].get("status", "blocked")
    if latest == "running":
        return "blocked"
    if latest == "passed" and any(a.get("status") in {"failed", "flaky"} for a in attempts[:-1]):
        return "flaky"
    return latest


def totals(session):
    attempts = [a for entries in session["results"].values() for a in entries]
    return {"execution_seconds": sum(a.get("duration_seconds", 0) for a in attempts),
            "external_cost_reserved": sum(max(a.get("cost_reserved", 0), a.get("cost_actual") or 0) for a in attempts),
            "external_cost_actual_known": sum(a.get("cost_actual") or 0 for a in attempts),
            "cost_actual_incomplete": any(a.get("cost_reserved", 0) > 0 and a.get("cost_actual") is None for a in attempts)}


def permitted(session, case, directory=None):
    limits, used, executor = session["plan"]["limits"], totals(session), case["executor"]
    if executor.get("installs") and not session["plan"]["allow_install"]:
        return "本轮复用环境，未启用依赖安装"
    if used["execution_seconds"] >= limits["execution_seconds"]:
        return "已达到执行时间预算"
    if used["external_cost_reserved"] + executor.get("external_cost_bound", 0) > limits["max_external_cost"]:
        return "外部费用上界超过剩余预算"
    for dep in case.get("prerequisites", []):
        if case_status(session["results"].get(dep, [])) != "passed":
            return f"前置用例 {dep} 尚未稳定通过"
    statuses = {}
    cases = {c["id"]: c for c in session["plan"]["cases"]}
    for cid, attempts in session["results"].items():
        state = case_status(attempts)
        if state == "passed" and directory and not all(verify_evidence(a, directory)
                and not verify_observation(session, cases[cid], a, directory) for a in attempts if a.get("status") == "passed"):
            state = "blocked"
        statuses[cid] = state
    return baseline_blocker(session["plan"], case, statuses)


def ordered_cases(plan):
    by_id = {c["id"]: c for c in plan["cases"]}
    result, visited = [], set()

    def visit(case):
        if case["id"] in visited:
            return
        for dep in case.get("prerequisites", []):
            visit(by_id[dep])
        visited.add(case["id"])
        result.append(case)

    for case in plan["cases"]:
        visit(case)
    return result


def evidence_manifest(directory):
    return [{"path": str(p.relative_to(directory.parent.parent.parent)), "sha256": file_hash(p)}
            for p in sorted(directory.rglob("*")) if p.is_file() and not p.is_symlink()]


def verify_evidence(attempt, directory):
    files = attempt.get("evidence", [])
    if not files:
        return False
    root = Path(directory).resolve()
    for item in files:
        path = (root / item.get("path", "")).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            return False
        try:
            if file_hash(path) != item["sha256"]:
                return False
        except (OSError, KeyError):
            return False
    return True


def stop_process(proc):
    if proc.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(proc.pid, signal.SIGTERM)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        proc.wait()


def execute_command(case, session, directory, evidence_dir):
    executor, plan = case["executor"], session["plan"]
    substitutions = {"{python}": sys.executable, "{project_root}": plan["project_root"],
                     "{evidence_dir}": str(evidence_dir)}

    def expand(text):
        for key, value in substitutions.items():
            text = text.replace(key, value)
        return text

    argv = [expand(a) for a in executor["argv"]]
    remaining = plan["limits"]["execution_seconds"] - totals(session)["execution_seconds"]
    timeout = min(executor["timeout_seconds"], remaining)
    output = evidence_dir / "output.log"
    started, proc = time.monotonic(), None
    result = {"status": "blocked", "reason": "尚未完成", "returncode": None}
    interrupted = False
    try:
        with output.open("w", encoding="utf-8") as stream:
            proc = subprocess.Popen(argv, cwd=str((Path(plan["project_root"]) / executor.get("cwd", ".")).resolve()),
                                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
            code = proc.wait(timeout=timeout)
        result_path = expand(executor.get("result_path", ""))
        if result_path:
            resolved = Path(result_path).resolve()
            need(resolved.is_relative_to(evidence_dir.resolve()), "结果文件越出本次证据目录")
        try:
            result = parse(executor["adapter"], result_path, code)
            result["returncode"] = code
        except QAError as exc:
            result = {"status": "failed" if code != 0 else "blocked", "reason": str(exc), "returncode": code}
    except subprocess.TimeoutExpired:
        stop_process(proc)
        result = {"status": "blocked", "reason": "执行超时，需区分产品、环境或预算原因", "returncode": proc.returncode}
    except (OSError, QAError) as exc:
        result = {"status": "blocked", "reason": str(exc), "returncode": None}
    except KeyboardInterrupt:
        if proc:
            stop_process(proc)
        result = {"status": "blocked", "reason": "执行被中断，可以在预算内继续", "returncode": proc.returncode if proc else None}
        interrupted = True
    finally:
        if proc and proc.poll() is None:
            stop_process(proc)
        if output.exists():
            output.write_text(redact(output.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    result.update({"duration_seconds": round(time.monotonic() - started, 6), "interrupted": interrupted,
                   "cost_reserved": executor.get("external_cost_bound", 0), "cost_actual": None})
    return result


def run(plan_path, directory, case_id=None, retry=False):
    with session_lock(directory) as directory:
        session = open_session(plan_path, directory)
        plan = session["plan"]
        need(case_id is None or any(c["id"] == case_id for c in plan["cases"]), "用例不存在")
        for case in ordered_cases(plan):
            if not case["in_scope"] or (case_id and case["id"] != case_id) or case["executor"]["kind"] != "command":
                continue
            entries = session["results"].setdefault(case["id"], [])
            if entries and entries[-1].get("status") == "running":
                entries[-1].update({"status": "blocked", "reason": "上次执行未完成；需要复核残留进程和业务副作用后重试",
                                   "duration_seconds": entries[-1].get("time_reserved", case["executor"].get("timeout_seconds", 0))})
                save(directory / "session.json", session)
            if entries and not retry:
                continue
            if len(entries) >= plan["limits"]["max_attempts_per_case"]:
                session["notes"].append(f"{case['id']} 已达到重试上限")
                continue
            reason = permitted(session, case, directory)
            attempt = {"attempt": len(entries) + 1, "started_at": now(), "status": "running",
                       "snapshot_digest": plan["snapshot"]["digest"], "environment_hash": digest(plan["environment"])}
            entries.append(attempt)
            if reason:
                attempt.update({"status": "blocked", "reason": reason, "duration_seconds": 0, "cost_reserved": 0})
                save(directory / "session.json", session)
                continue
            evidence_dir = directory / "evidence" / case["id"] / str(attempt["attempt"])
            evidence_dir.mkdir(parents=True, exist_ok=False)
            attempt["cost_reserved"] = case["executor"].get("external_cost_bound", 0)
            attempt["time_reserved"] = min(case["executor"]["timeout_seconds"],
                                           plan["limits"]["execution_seconds"] - totals(session)["execution_seconds"])
            save(directory / "session.json", session)
            result = execute_command(case, session, directory, evidence_dir)
            attempt.update(result)
            attempt["finished_at"] = now()
            attempt["evidence"] = evidence_manifest(evidence_dir)
            save(directory / "session.json", session)
            if result.get("interrupted"):
                break
            snapshot_after = current_snapshot(plan, directory)
            if not snapshot_after["complete"] or snapshot_after["digest"] != plan["snapshot"]["digest"]:
                session["notes"].append("执行后项目快照改变，停止后续命令；先检查修改并新建一轮。")
                break
        save(directory / "session.json", session)
        return session


def record(plan_path, directory, observation_path):
    """Import browser/computer-use evidence; artifact checks do not certify semantics."""
    payload = load(observation_path)
    with session_lock(directory) as directory:
        session = open_session(plan_path, directory)
        case = next((c for c in session["plan"]["cases"] if c["id"] == payload.get("case_id")), None)
        need(case is not None and case["in_scope"] and case["executor"]["kind"] == "observation", "不是范围内的观察用例")
        status = payload.get("status")
        need(status in {"passed", "failed", "blocked", "skipped", "flaky"}, "观察结果状态无效")
        need(isinstance(payload.get("reason"), str) and payload["reason"].strip(), "观察结果必须说明实际情况")
        need(payload.get("observed_snapshot") == session["plan"]["snapshot"]["digest"], "观察证据未绑定本轮快照")
        need(payload.get("environment_hash") == digest(session["plan"]["environment"]), "观察证据环境不匹配")
        number(payload.get("duration_seconds"), "duration_seconds")
        if payload.get("external_cost_actual") is not None:
            number(payload["external_cost_actual"], "external_cost_actual")
        entries = session["results"].setdefault(case["id"], [])
        need(len(entries) < session["plan"]["limits"]["max_attempts_per_case"], "已达到记录/重试上限")
        policy_issue = permitted(session, case, directory)
        assertions = payload.get("assertions", [])
        files = payload.get("evidence_files", [])
        if status in {"passed", "failed", "flaky"}:
            need(isinstance(assertions, list) and assertions and all(isinstance(a, dict) and
                 isinstance(a.get("expected"), str) and isinstance(a.get("actual"), str) and
                 type(a.get("passed")) is bool for a in assertions), "需要可检查的预期/实际断言")
            need(isinstance(files, list) and files, "需要截图、轨迹或数据核验等原始证据文件")
        if status == "passed":
            need(all(a["passed"] for a in assertions), "失败断言不能记录为通过")
        if status == "failed":
            need(any(not a["passed"] for a in assertions), "失败结果需要失败断言")
        issues = observation_issues(session["plan"], case, payload)
        check_id = payload.get("check_id")
        receipt = session.get("checks", {}).get(check_id) if isinstance(check_id, str) else None
        if not valid_receipt(session, case["id"], receipt, len(entries) + 1, consumed=False):
            issues.append("缺少本次观察前的有效 check 记录，或记录已被使用")
        if policy_issue:
            issues.insert(0, policy_issue)
        policy_issue = "；".join(issues)
        resolved_files = []
        for raw in files:
            path = Path(raw)
            if not path.is_absolute():
                path = Path(observation_path).resolve().parent / path
            need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 25000000, "证据文件缺失或超出大小上限")
            resolved_files.append(path)
        attempt_dir = directory / "evidence" / case["id"] / str(len(entries) + 1)
        attempt_dir.mkdir(parents=True, exist_ok=False)
        for index, path in enumerate(resolved_files):
            shutil.copyfile(path, attempt_dir / f"{index}-{path.name}")
        saved_payload = dict(payload)
        saved_payload["reason"] = redact(saved_payload["reason"])
        save(attempt_dir / "observation.json", saved_payload)
        entries.append({"attempt": len(entries) + 1, "status": status, "reason": saved_payload["reason"],
                        "started_at": now(), "finished_at": now(), "duration_seconds": payload["duration_seconds"],
                        "cost_reserved": case["executor"].get("external_cost_bound", 0),
                        "cost_actual": payload.get("external_cost_actual"),
                        "snapshot_digest": payload["observed_snapshot"], "environment_hash": payload["environment_hash"],
                        "evidence": evidence_manifest(attempt_dir), "evidence_origin": "host_observation",
                        "check_id": check_id, "method": payload.get("method"), "actor_kind": payload.get("actor_kind")})
        if receipt and valid_receipt(session, case["id"], receipt, len(entries), consumed=False):
            receipt["consumed"] = True
        if policy_issue:
            entries[-1].update({"observed_status": status, "status": "blocked", "reason": f"{policy_issue}；实际观察已保留：{saved_payload['reason']}"})
            session["notes"].append(f"{case['id']} 的宿主操作未满足执行条件；保留实际时间、费用与证据，不能用其放行。")
        save(directory / "session.json", session)
        return session


def check_case(plan_path, directory, case_id):
    with session_lock(directory) as directory:
        session = open_session(plan_path, directory)
        case = next((c for c in session["plan"]["cases"] if c["id"] == case_id), None)
        need(case is not None and case["in_scope"], "用例不存在或不在本轮范围内")
        attempt = len(session["results"].get(case_id, [])) + 1
        reason = "已达到尝试上限" if attempt > session["plan"]["limits"]["max_attempts_per_case"] else permitted(session, case, directory)
        result = {"allowed": reason is None, "reason": reason, "case_id": case_id,
                  "required_checkpoints": assessment(case)["checkpoints"], "note": "仅允许执行，不代表测试通过。"}
        if not reason and case["executor"]["kind"] == "observation":
            checks = session.setdefault("checks", {})
            check_id = next((key for key, value in checks.items() if valid_receipt(session, case_id, value, attempt, False)), None)
            if check_id is None:
                check_id = uuid.uuid4().hex
                checks[check_id] = {"case_id": case_id, "attempt": attempt, "plan_hash": session["plan_hash"],
                                    "snapshot": session["plan"]["snapshot"]["digest"], "environment_hash": digest(session["plan"]["environment"]),
                                    "created_at": now(), "consumed": False}
                save(directory / "session.json", session)
            result["check_id"] = check_id
            result["observation_template"] = {"case_id": case_id, "check_id": check_id, "status": "blocked", "reason": "尚未实际观察",
                "observed_snapshot": session["plan"]["snapshot"]["digest"], "environment_hash": digest(session["plan"]["environment"]),
                "duration_seconds": 0, "external_cost_actual": None, "method": "", "actor_kind": "", "evidence_files": [],
                "assertions": [{"checkpoint": p, "expected": "", "actual": "", "passed": False, "evidence_indices": []}
                               for p in assessment(case)["checkpoints"]]}
            if assessment(case)["layer"] == "interaction":
                result["observation_template"]["execution"] = {"surface": "", "entry": "", "backend_bypass": None,
                    "source_access": "", "assistance": [], "trace": []}
        return result


def valid_receipt(session, case_id, receipt, attempt, consumed):
    return (isinstance(receipt, dict) and receipt.get("case_id") == case_id and receipt.get("attempt") == attempt
            and receipt.get("consumed") is consumed and receipt.get("plan_hash") == session["plan_hash"]
            and receipt.get("snapshot") == session["plan"]["snapshot"]["digest"]
            and receipt.get("environment_hash") == digest(session["plan"]["environment"]))


def verify_observation(session, case, attempt, directory):
    if session["plan"]["schema_version"] == "1.0" or case["executor"]["kind"] != "observation":
        return []
    path = Path(directory) / "evidence" / case["id"] / str(attempt["attempt"]) / "observation.json"
    try:
        payload = load(path)
        issues = observation_issues(session["plan"], case, payload)
        check_id = attempt.get("check_id")
        receipt = session.get("checks", {}).get(check_id) if isinstance(check_id, str) else None
        if not valid_receipt(session, case["id"], receipt, attempt["attempt"], consumed=True) or payload.get("check_id") != check_id:
            issues.append("观察前检查记录不完整或不匹配")
        if payload.get("status") != attempt["status"]:
            issues.append("观察原始状态与执行记录不匹配")
        return issues
    except (QAError, TypeError, AttributeError):
        return ["无法核验结构化观察记录"]
