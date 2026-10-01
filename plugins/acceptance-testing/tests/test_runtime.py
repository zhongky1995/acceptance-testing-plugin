"""Offline behavioral checks using disposable projects, no installs or model calls."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qa_adapters import parse
from qa_contracts import validate
from qa_report import evaluate, report_session
from qa_runtime import record, run
from qa_store import QAError, digest, load, project_snapshot, save, scan


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "app.py").write_text("value = 1\n")
        self.session = Path(self.temp.name) / "run"
        self.plan_path = Path(self.temp.name) / "plan.json"
        self.plan = {"schema_version": "1.0", "project_root": str(self.root), "scenario": "local-iteration",
                     "goal": "验证本地规则", "snapshot": project_snapshot(self.root),
                     "environment": {"python": sys.version.split()[0], "model": "offline"},
                     "limits": {"execution_seconds": 10, "max_attempts_per_case": 2, "max_external_cost": 0, "currency": "CNY"},
                     "allow_install": False,
                     "requirements": [{"id": "R1", "statement": "规则正确", "status": "confirmed", "required": True,
                                       "sources": ["测试用户明确要求"]}],
                     "cases": [self.command("C1")], "feedback": []}

    def command(self, name, status="passed", requirement="R1"):
        code = "import json,sys; json.dump({'tests':[{'name':'rule','status':" + repr(status) + "}]},open(sys.argv[1],'w'))"
        return {"id": name, "title": "规则检查", "dimension": "functional", "requirement_ids": [requirement],
                "required": True, "in_scope": True, "expected": "断言正确", "prerequisites": [],
                "executor": {"kind": "command", "argv": ["{python}", "-c", code, "{evidence_dir}/results.json"],
                             "adapter": "native", "result_path": "{evidence_dir}/results.json", "timeout_seconds": 2,
                             "external_calls": False, "external_cost_bound": 0, "installs": False}}

    def execute(self, retry=False, case=None):
        save(self.plan_path, self.plan)
        return run(self.plan_path, self.session, case, retry)

    def report(self):
        return report_session(self.session)

    def test_local_run_passes_without_installs(self):
        self.execute()
        report = self.report()
        self.assertEqual(report["gate"], "passed")
        self.assertEqual(report["dimensions"]["delivery"], "not_assessed")
        self.assertEqual(report["usage"]["external_cost_reserved"], 0)
        self.assertEqual(load(self.session / "frozen-plan.json"), self.plan)

    def test_zero_cases_cannot_validate(self):
        self.plan["cases"] = []
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_zero_tests_cannot_pass(self):
        self.plan["cases"][0]["executor"]["argv"][2] = "import sys,json; json.dump({'tests':[]},open(sys.argv[1],'w'))"
        self.execute()
        self.assertEqual(self.report()["gate"], "inconclusive")

    def test_missing_result_not_exit_success(self):
        self.plan["cases"][0]["executor"]["argv"] = ["{python}", "-c", "print('ok')"]
        self.execute()
        self.assertEqual(self.report()["cases"][0]["status"], "blocked")

    def test_known_failure_blocks_gate(self):
        self.plan["cases"] = [self.command("C1", "failed")]
        self.execute()
        self.assertEqual(self.report()["gate"], "failed")

    def test_required_skip_is_inconclusive(self):
        self.plan["cases"] = [self.command("C1", "skipped")]
        self.execute()
        self.assertEqual(self.report()["gate"], "inconclusive")

    def test_retry_preserves_flaky(self):
        self.plan["cases"][0]["executor"]["argv"][2] = (
            "from pathlib import Path; import json,sys; p=Path(sys.argv[1]); "
            "status='failed' if p.parent.name=='1' else 'passed'; "
            "json.dump({'tests':[{'name':'rule','status':status}]},p.open('w'))")
        self.execute()
        self.execute(retry=True)
        report = self.report()
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["cases"][0]["status"], "flaky")
        self.assertEqual([a["status"] for a in report["cases"][0]["attempts"]], ["failed", "passed"])

    def test_plan_cannot_be_weakened_after_run(self):
        self.execute()
        self.plan["cases"][0]["required"] = False
        with self.assertRaises(QAError):
            self.execute()

    def test_changed_code_invalidates_pass(self):
        self.execute()
        (self.root / "app.py").write_text("value = 2\n")
        self.assertEqual(self.report()["gate"], "inconclusive")
        with self.assertRaises(QAError):
            self.execute(retry=True)

    def test_evidence_tamper_invalidates_pass(self):
        self.execute()
        (self.session / "evidence/C1/1/output.log").write_text("edited")
        self.assertEqual(self.report()["gate"], "inconclusive")

    def test_uncovered_required_requirement(self):
        self.plan["requirements"].append({"id": "R2", "statement": "另一重要要求", "status": "confirmed", "required": True,
                                          "sources": ["业务确认"]})
        self.execute()
        self.assertEqual(self.report()["gate"], "inconclusive")

    def test_conflicting_requirement_not_auto_confirmed(self):
        self.plan["requirements"][0]["status"] = "conflict"
        self.execute()
        self.assertEqual(self.report()["gate"], "inconclusive")

    def test_out_of_scope_delivery_not_failed(self):
        extra = self.command("D1")
        extra.update({"dimension": "delivery", "in_scope": False, "required": False})
        self.plan["cases"].append(extra)
        self.execute()
        report = self.report()
        self.assertEqual(report["gate"], "passed")
        self.assertEqual(report["cases"][1]["status"], "out_of_scope")

    def test_delivery_failure_reported_separately(self):
        extra = self.command("D1", "failed")
        extra["dimension"] = "delivery"
        self.plan["cases"].append(extra)
        self.execute()
        report = self.report()
        self.assertEqual(report["dimensions"]["functional"], "passed")
        self.assertEqual(report["dimensions"]["delivery"], "failed")
        self.assertEqual(report["gate"], "failed")

    def test_budget_blocks_external_execution(self):
        self.plan["cases"][0]["executor"].update({"external_calls": True, "external_cost_bound": 1})
        self.execute()
        self.assertEqual(self.report()["gate"], "inconclusive")
        self.assertFalse((self.session / "evidence/C1/1").exists())

    def test_install_not_enabled_for_local(self):
        self.plan["cases"][0]["executor"]["installs"] = True
        self.execute()
        self.assertEqual(self.report()["gate"], "inconclusive")

    def test_time_budget_is_cumulative(self):
        self.plan["limits"]["execution_seconds"] = 0.1
        self.plan["cases"][0]["executor"]["argv"] = ["{python}", "-c", "import time;time.sleep(2)"]
        self.plan["cases"].append(self.command("C2"))
        self.execute()
        report = self.report()
        self.assertEqual(report["cases"][0]["status"], "blocked")
        self.assertIn("预算", report["cases"][1]["attempts"][0]["reason"])

    def test_prerequisite_failure_does_not_block_independent_case(self):
        self.plan["cases"] = [self.command("C1", "failed"), self.command("C2"), self.command("C3")]
        self.plan["cases"][1]["prerequisites"] = ["C1"]
        self.execute()
        self.assertEqual([r["status"] for r in self.report()["cases"]], ["failed", "blocked", "passed"])

    def test_retry_limit(self):
        self.execute()
        self.execute(retry=True)
        self.execute(retry=True)
        self.assertEqual(len(self.report()["cases"][0]["attempts"]), 2)

    def test_resume_does_not_rerun_passed_cases(self):
        self.execute()
        self.execute()
        self.assertEqual(len(self.report()["cases"][0]["attempts"]), 1)

    def test_no_commands_executed_during_scan(self):
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "touch installed.txt"}}))
        result = scan(self.root)
        self.assertIn("package.json", result["dependency_files"])
        self.assertFalse((self.root / "installed.txt").exists())

    def test_observation_requires_evidence_and_assertions(self):
        case = self.plan["cases"][0]
        case["executor"] = {"kind": "observation", "external_calls": False, "external_cost_bound": 0, "installs": False}
        save(self.plan_path, self.plan)
        payload = {"case_id": "C1", "status": "passed", "reason": "界面结果已核验", "duration_seconds": 1,
                   "observed_snapshot": self.plan["snapshot"]["digest"], "environment_hash": digest(self.plan["environment"]),
                   "assertions": [{"expected": "正确", "actual": "正确", "passed": True}], "evidence_files": []}
        observation = Path(self.temp.name) / "observation.json"
        save(observation, payload)
        with self.assertRaises(QAError):
            record(self.plan_path, self.session, observation)
        proof = Path(self.temp.name) / "proof.txt"
        proof.write_text("Recorded data assertion, not a generated screenshot")
        payload["evidence_files"] = [str(proof)]
        save(observation, payload)
        record(self.plan_path, self.session, observation)
        self.assertEqual(self.report()["gate"], "passed")

    def test_observation_failed_assertion_cannot_pass(self):
        self.plan["cases"][0]["executor"] = {"kind": "observation"}
        save(self.plan_path, self.plan)
        observation = Path(self.temp.name) / "observation.json"
        save(observation, {"case_id": "C1", "status": "passed", "reason": "错误状态", "duration_seconds": 1,
                           "observed_snapshot": self.plan["snapshot"]["digest"], "environment_hash": digest(self.plan["environment"]),
                           "assertions": [{"expected": "1", "actual": "2", "passed": False}], "evidence_files": [str(self.root / "app.py")]})
        with self.assertRaises(QAError):
            record(self.plan_path, self.session, observation)

    def test_stale_result_path_rejected(self):
        self.plan["cases"][0]["executor"]["result_path"] = "old-result.json"
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_cycle_rejected(self):
        self.plan["cases"].append(self.command("C2"))
        self.plan["cases"][0]["prerequisites"] = ["C2"]
        self.plan["cases"][1]["prerequisites"] = ["C1"]
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_rejected_nonfinite_budget(self):
        self.plan["limits"]["max_external_cost"] = float("nan")
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_snapshot_is_bounded_and_fail_closed(self):
        result = project_snapshot(self.root, max_files=0)
        self.assertFalse(result["complete"])

    def test_declared_free_external_call_with_zero_budget(self):
        self.plan["cases"][0]["executor"].update({"external_calls": True, "external_cost_bound": 0})
        self.execute()
        self.assertEqual(self.report()["gate"], "passed")

    def test_unknown_external_cost_rejected(self):
        self.plan["cases"][0]["executor"]["external_calls"] = True
        del self.plan["cases"][0]["executor"]["external_cost_bound"]
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_junit_incomplete_summary_not_passed(self):
        xml = Path(self.temp.name) / "bad.xml"
        xml.write_text('<testsuite tests="2"><testcase name="a"/></testsuite>')
        with self.assertRaises(QAError):
            parse("junit", xml, 0)

    def test_playwright_expected_failure_not_gate_pass(self):
        js = Path(self.temp.name) / "pw.json"
        save(js, {"suites": [{"specs": [{"tests": [{"status": "expected", "expectedStatus": "failed"}]}]}]})
        self.assertEqual(parse("playwright", js, 0)["status"], "skipped")

    def test_interrupted_attempt_reserves_budget(self):
        self.execute()
        session = load(self.session / "session.json")
        attempt = session["results"]["C1"][0]
        attempt.update({"status": "running", "duration_seconds": 0, "time_reserved": 10})
        save(self.session / "session.json", session)
        self.execute(retry=True)
        report = self.report()
        self.assertEqual(report["gate"], "inconclusive")
        self.assertGreaterEqual(report["usage"]["execution_seconds"], 10)

    def test_command_source_change_stops_following_case(self):
        self.plan["cases"][0]["executor"] = {"kind": "command", "argv": ["{python}", "-c", "open('app.py','w').write('changed')"],
                                               "adapter": "exit", "timeout_seconds": 2}
        self.plan["cases"].append(self.command("C2"))
        self.execute()
        report = self.report()
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["cases"][1]["status"], "not_run")

    def test_stale_failure_does_not_claim_current_failure(self):
        self.plan["cases"] = [self.command("C1", "failed")]
        self.execute()
        (self.root / "app.py").write_text("fixed = True")
        report = self.report()
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["cases"][0]["attempts"][0]["status"], "failed")

    def test_posthoc_overbudget_observation_preserves_actual_cost(self):
        self.plan["cases"][0]["executor"] = {"kind": "observation", "external_calls": True, "external_cost_bound": 1}
        save(self.plan_path, self.plan)
        observation = Path(self.temp.name) / "observation.json"
        save(observation, {"case_id": "C1", "status": "passed", "reason": "操作实际已发生，应保留证据而非漏记费用", "duration_seconds": 1,
                           "observed_snapshot": self.plan["snapshot"]["digest"], "environment_hash": digest(self.plan["environment"]),
                           "external_cost_actual": 2,
                           "assertions": [{"expected": "成功", "actual": "成功", "passed": True}],
                           "evidence_files": [str(self.root / "app.py")]})
        record(self.plan_path, self.session, observation)
        report = self.report()
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["usage"]["external_cost_actual_known"], 2)
        self.assertEqual(report["usage"]["external_cost_reserved"], 2)
        self.assertEqual(report["cases"][0]["attempts"][0]["observed_status"], "passed")

    def test_adapter_junit_and_playwright(self):
        xml = Path(self.temp.name) / "report.xml"
        xml.write_text('<testsuite><testcase name="a"/><testcase name="b"><failure/></testcase></testsuite>')
        self.assertEqual(parse("junit", xml, 0)["status"], "failed")
        xml.write_text('<testsuite tests="0"/>')
        with self.assertRaises(QAError):
            parse("junit", xml, 0)
        js = Path(self.temp.name) / "report.json"
        save(js, {"suites": [{"specs": [{"tests": [{"status": "flaky"}]}]}]})
        self.assertEqual(parse("playwright", js, 0)["status"], "flaky")


if __name__ == "__main__":
    unittest.main()
