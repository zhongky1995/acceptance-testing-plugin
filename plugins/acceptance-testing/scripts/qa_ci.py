#!/usr/bin/env python3
"""Portable risk-selected project CI. Standard library only; no implicit installs."""
import argparse
import fnmatch
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


class CIError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise CIError(message)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def within(root, raw):
    root = root.resolve()
    need(isinstance(raw, str) and raw and not Path(raw).is_absolute(), "路径必须相对项目")
    path = (root / raw).resolve()
    need(path.is_relative_to(root), "路径越出项目")
    return path


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate(policy):
    need(isinstance(policy, dict) and policy.get("schema_version") == "1.0", "未知 CI 配置版本")
    seconds = policy.get("max_seconds")
    need(type(seconds) in (float, int) and math.isfinite(seconds) and 0 < seconds <= 540, "CI 累计预算须为 0..540 秒")
    groups = policy.get("groups")
    need(isinstance(groups, list) and groups, "CI 必须有检查组")
    ids = set()
    for group in groups:
        need(isinstance(group, dict), "检查组必须为对象")
        gid = group.get("id")
        need(isinstance(gid, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", gid) and gid not in ids, "检查组编号无效或重复")
        ids.add(gid)
        need(group.get("trigger") in {"always", "changed", "delivery"}, "未知测试触发层级")
        need(group.get("status") in {"required", "not_applicable"}, "检查组需明确适用性")
        need(nonempty(group.get("reason")) and isinstance(group.get("sources"), list) and group["sources"] and all(nonempty(s) for s in group["sources"]), "检查组需要具体理由与来源")
        paths = group.get("paths")
        need(isinstance(paths, list) and all(nonempty(p) and not p.startswith(("/", "!")) and ".." not in p.split("/") for p in paths), "风险路径模式无效")
        need(group["trigger"] != "changed" or paths, "按改动触发的检查组需要路径模式")
        commands = group.get("commands")
        need(isinstance(commands, list), "commands 必须为数组")
        for command in commands:
            need(isinstance(command, dict), "命令必须为对象")
            argv = command.get("argv")
            need(isinstance(argv, list) and argv and all(nonempty(a) for a in argv), "命令 argv 必须为非空数组")
            timeout = command.get("timeout_seconds")
            need(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= seconds, "命令超时须在累计预算内")
            need(command.get("external_calls") is False and command.get("installs") is False, "本模板仅运行无外部付费调用、无安装的检查；准备环境使用项目已有流程")
    fast = next((g for g in groups if g["id"] == "fast"), {})
    need(fast.get("trigger") == "always" and fast.get("status") == "required", "fast 基础检查必须始终必需")
    need(any(g["trigger"] == "changed" for g in groups), "至少需要一组按风险触发的检查")
    need(any(g["trigger"] == "delivery" and g["status"] == "required" for g in groups), "需要独立的交付检查组")
    return policy


def matches(path, pattern):
    # **/ also matches the root; fnmatch's * includes '/', deliberately conservative.
    return fnmatch.fnmatchcase(path, pattern) or (pattern.startswith("**/") and matches(path, pattern[3:]))


def changed_files(root, base):
    if not base or not re.fullmatch(r"[0-9a-fA-F]{7,40}", base) or set(base) == {"0"}:
        return None, "无可比较基线，扩大至所有自动检查"
    try:
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=root, capture_output=True, timeout=15)
        if ancestor.returncode:
            return None, "基线不在当前历史中，扩大至所有自动检查"
        result = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", base, "HEAD", "--"], cwd=root, capture_output=True, timeout=15)
        if result.returncode:
            return None, "比较基线不可用，扩大至所有自动检查"
        return [s.decode("utf-8", errors="surrogateescape") for s in result.stdout.split(b"\0") if s], "基线比较成功"
    except (OSError, subprocess.TimeoutExpired):
        return None, "无法比较改动，扩大至所有自动检查"


def select(policy, files, profile):
    groups = policy["groups"]
    applicable = [g for g in groups if g["status"] == "required"]
    patterns = [p for g in groups if g["trigger"] == "changed" for p in g["paths"]]
    control = files is not None and any(p.startswith((".acceptance-ci/", ".github/")) for p in files)
    unknown = files is not None and any(not any(matches(p, pat) for pat in patterns) for p in files)
    wide = profile in {"full", "delivery"} or files is None or control or unknown
    decisions = []
    for group in groups:
        selected = group in applicable and (group["trigger"] == "always" or
                   (group["trigger"] == "delivery" and profile == "delivery") or
                   (group["trigger"] == "changed" and (wide or any(matches(p, pat) for p in files or [] for pat in group["paths"]))))
        reason = ("有依据地不适用" if group["status"] != "required" else "未触及对应风险" if not selected else
                  "扩大自动覆盖" if wide and group["trigger"] == "changed" else "符合触发条件")
        decisions.append({"id": group["id"], "selected": selected, "reason": reason, "basis": group["reason"], "sources": group["sources"]})
    return decisions


def initialize(root, workflow=True):
    source = Path(__file__).resolve().parent
    assets = source.parent / "assets/project-ci"
    need(assets.is_dir(), "init 请使用已安装插件中的 scripts/qa_ci.py")
    copies = {".acceptance-ci/ci.py": Path(__file__), ".acceptance-ci/policy.json": assets / "policy.json",
              ".github/workflows/acceptance-ci.yml": assets / "acceptance-ci.yml"}
    if not workflow:
        copies.pop(".github/workflows/acceptance-ci.yml")
    copies.update({f".acceptance-ci/engine/{p.name}": p for p in source.glob("qa*.py") if p.name != "qa_ci.py"})
    copies[".acceptance-ci/engine/contract_check.py"] = source / "contract_check.py"
    for target in copies:
        need(not within(root, target).exists(), f"文件已存在，未覆盖：{target}")
    for target, src in copies.items():
        dest = within(root, target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    return {"created": list(copies), "note": "填写真实命令和风险路径后提交；空命令会阻断，尚未替目标仓库设置分支保护。"}


def stop(proc):
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif proc.poll() is None:
        proc.kill()
    proc.wait()


def execute(root, command, seconds, log):
    engine = root / ".acceptance-ci/engine/qa.py"
    replacements = {"{python}": sys.executable, "{qa}": str(engine), "{project_root}": str(root)}
    argv = command["argv"][:]
    for i, value in enumerate(argv):
        for key, replacement in replacements.items():
            value = value.replace(key, replacement)
        argv[i] = value
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    proc = None
    try:
        cwd = within(root, command.get("cwd", "."))
        need(cwd.is_dir(), "命令目录不存在")
        with log.open("w", encoding="utf-8") as stream:
            proc = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
            code = proc.wait(timeout=min(seconds, command["timeout_seconds"]))
        return {"status": "passed" if code == 0 else "failed", "returncode": code, "seconds": time.monotonic() - start, "log": str(log.relative_to(root))}
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if proc:
            stop(proc)
        return {"status": "blocked", "reason": "达到超时或执行被中断", "seconds": time.monotonic() - start}
    except (OSError, CIError) as exc:
        return {"status": "blocked", "reason": str(exc), "seconds": time.monotonic() - start}
    finally:
        if proc:
            stop(proc)


def run(root, policy, profile, base, output):
    files, baseline = changed_files(root, base)
    decisions = select(policy, files, profile)
    groups = {g["id"]: g for g in policy["groups"]}
    need(not output.exists(), "报告已存在；请使用新目录或先归档本轮结果")
    log_root = output.parent / (output.stem + "-logs")
    need(not log_root.exists(), "日志目录已存在，请归档旧轮次")
    report = {"schema_version": "1.0", "status": "running", "profile": profile, "baseline": baseline,
              "changed_files": files, "decisions": decisions, "results": [], "product_accepted": False}
    try:
        report["head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        report["head"] = "unknown"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    start = time.monotonic()
    for decision in decisions:
        if not decision["selected"]:
            continue
        group = groups[decision["id"]]
        if not group["commands"]:
            report["results"].append({"group": group["id"], "status": "blocked", "reason": "已选中的检查没有实际命令"})
            break
        for index, command in enumerate(group["commands"]):
            remaining = policy["max_seconds"] - (time.monotonic() - start)
            if remaining <= 0:
                result = {"status": "blocked", "reason": "累计预算用尽"}
            else:
                result = execute(root, command, remaining, log_root / f"{group['id']}-{index}.log")
            report["results"].append({"group": group["id"], **result})
            save(output, report)
            if result["status"] != "passed":
                break
        # Fail early: don't spend on deeper groups after a known failure/gap.
        if any(r["status"] != "passed" for r in report["results"]):
            break
    completed = {r["group"] for r in report["results"]}
    report["results"].extend({"group": d["id"], "status": "not_run", "reason": "前序检查未通过，已停止投入"} for d in decisions if d["selected"] and d["id"] not in completed)
    passed = bool(report["results"]) and all(r["status"] == "passed" for r in report["results"])
    if profile == "delivery" and passed:
        session = within(root, policy.get("product_session", ""))
        gate = {"argv": ["{python}", "{qa}", "gate", "--session-dir", str(session)], "timeout_seconds": policy["max_seconds"]}
        remaining = policy["max_seconds"] - (time.monotonic() - start)
        result = execute(root, gate, remaining, log_root / "product-gate.log") if remaining > 0 else {"status": "blocked", "reason": "产品 gate 前预算已用尽"}
        report["results"].append({"group": "product-gate", **result})
        report["product_accepted"] = result["status"] == "passed"
        passed = report["product_accepted"]
    report.update(status="passed" if passed else "failed", seconds=time.monotonic() - start)
    save(output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--project", required=True)
    init.add_argument("--runner-only", action="store_true", help="复用现有 CI，不生成新工作流")
    for action in ("plan", "run"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--project", default=".")
        cmd.add_argument("--policy", default=".acceptance-ci/policy.json")
        cmd.add_argument("--profile", choices=("change", "full", "delivery"), default="change")
        cmd.add_argument("--base", default=os.environ.get("CI_BASE", ""))
        cmd.add_argument("--output", default=".acceptance/ci-selection.json")
    args = parser.parse_args()
    try:
        root = Path(args.project).resolve()
        need(root.is_dir(), "项目目录不存在")
        if args.action == "init":
            print(json.dumps(initialize(root, workflow=not args.runner_only), ensure_ascii=False))
            return 0
        policy = validate(load(within(root, args.policy)))
        within(root, policy.get("product_session", ""))
        if args.action == "plan":
            files, reason = changed_files(root, args.base)
            print(json.dumps({"changed_files": files, "baseline": reason, "decisions": select(policy, files, args.profile)}, ensure_ascii=False))
            return 0
        result = run(root, policy, args.profile, args.base, within(root, args.output))
        print(json.dumps(result, ensure_ascii=False))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"Acceptance CI: {result['status']} / {args.profile}; product_accepted={result['product_accepted']}\n")
        return 0 if result["status"] == "passed" else 1
    except (CIError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"CI 受阻：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
