#!/usr/bin/env python3
"""Offline project CI adoption: cheap doc change, then real contract regression."""
import argparse
import shutil
import subprocess
from pathlib import Path
from qa_ci import initialize, load, run, save


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    output = Path(parser.parse_args().output).resolve()
    if output.exists():
        raise SystemExit("输出目录已存在，请选新目录以保留历史")
    root = output / "project"
    shutil.copytree(Path(__file__).resolve().parents[1] / "tests/fixtures/contract-project", root, ignore=shutil.ignore_patterns("__pycache__"))
    initialize(root)
    source = root / "contracts.py"
    source.write_text(source.read_text().replace("len(value) <= 2", "len(value) <= 3"))
    boundary = {"id": "export", "producer": "contracts.py:producer_accepts", "consumer": "contracts.py:consumer_accepts"}
    save(root / "contract-spec.json", {"boundary": boundary, "argv": ["{python}", "adapter.py"],
         "samples": [{"id": s, "path": f"{s}.json", "expected_producer": s != "rejected", "expected_consumer": s != "rejected"} for s in ("accepted", "boundary", "rejected")]})
    policy = load(root / ".acceptance-ci/policy.json")
    command = {"argv": ["{python}", "-c", "from contracts import producer_accepts,consumer_accepts;assert producer_accepts([1]) and consumer_accepts([1])"],
               "timeout_seconds": 5, "external_calls": False, "installs": False}
    policy["groups"][0]["commands"] = [command]
    policy["groups"][1].update(paths=["contracts.py", "adapter.py", "*.json"], commands=[{**command, "argv": ["{python}", ".acceptance-ci/engine/contract_check.py", "contract-spec.json", ".acceptance/contract-result.json"]}])
    policy["groups"][2].update(status="not_applicable", paths=["*.md"], reason="示例是无用户界面的 API 边界", sources=["README.md"])
    save(root / ".acceptance-ci/policy.json", policy)
    git(root, "init", "-q")
    git(root, "config", "user.email", "ci@example.invalid")
    git(root, "config", "user.name", "Offline CI demo")
    git(root, "add", "."); git(root, "commit", "-qm", "fixed baseline")
    base = git(root, "rev-parse", "HEAD")
    with (root / "README.md").open("a") as stream:
        stream.write("\n补充示例的使用说明。\n")
    git(root, "add", "."); git(root, "commit", "-qm", "documentation change")
    docs = run(root, policy, "change", base, root / ".acceptance/docs.json")
    # Change file size as well, so same-second Python bytecode cannot hide the edit.
    text = source.read_text()
    pos = text.index("def consumer_accepts")
    source.write_text(text[:pos] + text[pos:].replace("len(value) <= 3", "len(value) < 3"))
    git(root, "add", "contracts.py"); git(root, "commit", "-qm", "consumer boundary regression")
    changed = run(root, policy, "change", base, root / ".acceptance/contract-change.json")
    save(output / "comparison.json", {"docs": docs["status"], "contract_change": changed["status"], "product_accepted": changed["product_accepted"]})
    selected = [d["id"] for d in docs["decisions"] if d["selected"]]
    print(f"说明变更：{docs['status']}（{', '.join(selected)}）；契约回归：{changed['status']}；档案：{output}")
    return 0 if docs["status"] == "passed" and selected == ["fast"] and changed["status"] == "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
