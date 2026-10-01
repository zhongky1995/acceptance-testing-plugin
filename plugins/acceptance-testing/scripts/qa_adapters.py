"""Parse isolated reports without treating exit code zero as test coverage."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from qa_store import QAError


def summarize(states, returncode):
    allowed = {"passed", "failed", "skipped", "flaky"}
    if not states or any(s not in allowed for s in states):
        raise QAError("结果为空或存在未知测试状态")
    counts = {s: states.count(s) for s in allowed}
    if returncode != 0 or counts["failed"]:
        status = "failed"
    elif counts["flaky"]:
        status = "flaky"
    elif counts["skipped"]:
        status = "skipped"
    else:
        status = "passed"
    return {"status": status, "counts": counts, "tests": len(states)}


def parse(adapter, report_path, returncode):
    if adapter == "exit":
        return {"status": "passed" if returncode == 0 else "failed", "tests": None,
                "counts": {}, "note": "命令断言；退出码仅证明方案中声明的检查，不代表测试套件覆盖。"}
    path = Path(report_path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 25000000:
        raise QAError("未生成有效的本轮结构化结果")
    try:
        if adapter == "junit":
            text = path.read_text(encoding="utf-8")
            if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
                raise QAError("JUnit 不接受实体声明")
            tree = ET.fromstring(text)
            states = []
            declared_failure = False
            for suite in tree.iter():
                if suite.tag.split("}")[-1] in {"testsuite", "testsuites"}:
                    actual = sum(1 for t in suite.iter() if t.tag.split("}")[-1] == "testcase")
                    if "tests" in suite.attrib and int(suite.attrib["tests"]) != actual:
                        raise QAError("JUnit 声明数量与 testcase 不一致，结果不完整")
                    declared_failure = declared_failure or any(int(suite.attrib.get(k, "0")) > 0 for k in ("errors", "failures"))
            for test in tree.iter():
                if test.tag.split("}")[-1] != "testcase":
                    continue
                tags = {child.tag.split("}")[-1] for child in test}
                states.append("failed" if tags & {"failure", "error"} else "skipped" if "skipped" in tags else "passed")
            return summarize(states, returncode if not declared_failure else 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        if adapter == "native":
            items = data.get("tests", [])
            if not isinstance(items, list) or any(not isinstance(t, dict) or not t.get("name") for t in items):
                raise QAError("native tests 格式无效")
            return summarize([t.get("status") for t in items], returncode)
        if adapter == "playwright":
            states = []

            def walk(suite):
                for spec in suite.get("specs", []):
                    for test in spec.get("tests", []):
                        status = test.get("status")
                        if status == "expected":
                            states.append("passed" if test.get("expectedStatus", "passed") == "passed" else "skipped")
                        elif status == "unexpected":
                            states.append("failed")
                        elif status in {"flaky", "skipped"}:
                            states.append(status)
                        else:
                            raise QAError("Playwright 测试缺少最终状态")
                for child in suite.get("suites", []):
                    walk(child)

            for suite in data.get("suites", []):
                walk(suite)
            result = summarize(states, returncode)
            if data.get("errors"):
                result["status"] = "failed"
            return result
    except (ValueError, ET.ParseError, AttributeError, TypeError, OSError) as exc:
        raise QAError(f"无法解析 {adapter} 结果：{exc}") from exc
    raise QAError("未知适配器")
