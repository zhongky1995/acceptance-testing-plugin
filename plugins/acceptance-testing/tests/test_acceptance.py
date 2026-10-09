"""Adversarial omission/claim and handoff tests. Not evidence about human usability."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from acceptance_fixtures import focused_policy, product_policy
from qa_acceptance import expected_points, readiness
from qa_contracts import validate
from qa_report import report_session
from qa_runtime import check_case, record, run
from qa_store import QAError, digest, load, project_snapshot, save

CLI = Path(__file__).resolve().parents[1] / "scripts/qa.py"


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        (self.root / "PRD.md").write_text("用户保存后可以继续编辑草稿。")
        (self.root / "index.html").write_text('<button>保存</button>')
        self.directory = self.base / "run"
        self.plan_path = self.base / "plan.json"
        command = {"id": "C1", "title": "协议测试中的实现断言", "dimension": "functional", "requirement_ids": ["R1"],
                   "required": True, "in_scope": True, "expected": "保存规则正确", "prerequisites": [],
                   "assessment": {"layer": "implementation", "journey_id": "J1", "checkpoints": ["outcome"]},
                   "executor": {"kind": "command", "argv": ["{python}", "-c", "import json,sys;json.dump({'tests':[{'name':'save','status':'passed'}]},open(sys.argv[1],'w'))", "{evidence_dir}/result.json"],
                                "adapter": "native", "result_path": "{evidence_dir}/result.json", "timeout_seconds": 2,
                                "external_calls": False, "external_cost_bound": 0, "installs": False}}
        self.plan = {"schema_version": "1.1", "project_root": str(self.root), "scenario": "local-iteration", "goal": "验收协议隔离测试",
                     "snapshot": project_snapshot(self.root), "environment": {"host": "offline-test-fixture"},
                     "limits": {"execution_seconds": 60, "max_attempts_per_case": 2, "max_external_cost": 0, "currency": "CNY"},
                     "allow_install": False, "acceptance": product_policy(), "feedback": [],
                     "requirements": [{"id": "R1", "statement": "可以保存并继续编辑草稿", "status": "confirmed", "required": True, "sources": ["PRD.md:1"]}],
                     "cases": [command]}
        for cid, layer in [("N1", "need_fit"), ("U1", "interaction")]:
            case = copy.deepcopy(command)
            case.update({"id": cid, "title": layer, "executor": {"kind": "observation", "external_calls": False, "external_cost_bound": 0, "installs": False},
                         "assessment": {"layer": layer, "journey_id": "J1", "checkpoints": expected_points(layer, self.plan["acceptance"]["journeys"][0])}})
            self.plan["cases"].append(case)
        save(self.plan_path, self.plan)

    def prepare(self, cid):
        save(self.plan_path, self.plan)
        return check_case(self.plan_path, self.directory, cid)

    def payload(self, cid, prepare=True):
        case = next(c for c in self.plan["cases"] if c["id"] == cid)
        proof = self.base / f"{cid}-fixture.txt"
        proof.write_text("Synthetic protocol fixture: not a real user or browser observation.")
        payload = {"case_id": cid, "status": "passed", "reason": "隔离协议样本", "observed_snapshot": self.plan["snapshot"]["digest"],
                   "environment_hash": digest(self.plan["environment"]), "duration_seconds": 1, "external_cost_actual": 0,
                   "observed_by": {"host": "test-fixture"}, "actor_kind": "agent", "method": "analysis" if cid == "N1" else "ui_walkthrough",
                   "evidence_files": [str(proof)], "assertions": [{"checkpoint": p, "expected": "expected fixture", "actual": "actual fixture", "passed": True, "evidence_indices": [0]}
                                    for p in case["assessment"]["checkpoints"]],
                   "execution": {"surface": "gui", "entry": "/editor", "backend_bypass": False, "source_access": "implementation-informed", "assistance": [],
                                 "trace": [{"action": "fixture action", "visible_result": "fixture result", "evidence_indices": [0]}]}}
        if prepare:
            result = self.prepare(cid)
            self.assertTrue(result["allowed"], result)
            payload["check_id"] = result["check_id"]
        return payload

    def observe(self, payload):
        save(self.plan_path, self.plan)
        path = self.base / "observation.json"
        save(path, payload)
        record(self.plan_path, self.directory, path)
        return report_session(self.directory)

    def baseline(self):
        return self.observe(self.payload("N1"))

    def complete(self):
        self.baseline()
        self.observe(self.payload("U1"))
        run(self.plan_path, self.directory)
        return report_session(self.directory)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args], text=True, capture_output=True)

    def test_backend_only_plan_never_passes_product_gate(self):
        self.plan["cases"] = self.plan["cases"][:1]
        save(self.plan_path, self.plan)
        run(self.plan_path, self.directory)
        report = report_session(self.directory)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["acceptance"]["results"]["implementation"], "passed")
        self.assertFalse(report["product_accepted"])
        self.assertTrue(any("interaction" in g for g in report["gaps"]))

    def test_mixed_observation_reports_each_point_without_loosening_gate(self):
        self.baseline()
        payload = self.payload("U1")
        payload["status"] = "failed"
        next(a for a in payload["assertions"] if a["checkpoint"] == "completion")["passed"] = False
        report = self.observe(payload)
        points = {o["checkpoint"]: o["status"] for o in report["acceptance"]["obligations"] if o["layer"] == "interaction"}
        self.assertEqual(points["entry"], "passed")
        self.assertEqual(points["completion"], "failed")
        self.assertEqual(report["gate"], "failed")
        self.assertFalse(report["product_accepted"])
        self.assertIn("| entry | U1 | 通过 |", (self.directory / "report.md").read_text())

    def test_point_failure_then_success_remains_flaky(self):
        self.baseline()
        payload = self.payload("U1")
        payload["status"] = "failed"
        next(a for a in payload["assertions"] if a["checkpoint"] == "completion")["passed"] = False
        self.observe(payload)
        report = self.observe(self.payload("U1"))
        points = {o["checkpoint"]: o["status"] for o in report["acceptance"]["obligations"] if o["layer"] == "interaction"}
        self.assertEqual(points["entry"], "passed")
        self.assertEqual(points["completion"], "flaky")
        self.assertEqual(report["acceptance"]["results"]["interaction"], "inconclusive")
        self.assertFalse(report["product_accepted"])

    def test_corrupt_evidence_cannot_preserve_point_passes(self):
        self.complete()
        proof = next((self.directory / "evidence/U1/1").glob("0-*.txt"))
        proof.write_text("changed")
        report = report_session(self.directory)
        points = [o for o in report["acceptance"]["obligations"] if o["layer"] == "interaction"]
        self.assertTrue(all(o["status"] == "inconclusive" for o in points))
        self.assertFalse(report["product_accepted"])

    def test_optional_or_out_of_scope_ui_cannot_fill_coverage(self):
        case = self.plan["cases"][2]
        for scoped in [True, False]:
            case.update(required=False, in_scope=scoped)
            validate(self.plan)
            self.assertTrue(any(o["layer"] == "interaction" and not o["case_ids"] for o in readiness(self.plan)["obligations"]))

    def test_missing_task_state_or_pattern_is_explicit_gap(self):
        journey = self.plan["acceptance"]["journeys"][0]
        del journey["states"]["error"]
        journey["patterns"] = []
        result = readiness(validate(self.plan))
        self.assertEqual(len(result["layer_gaps"]["interaction"]), 2)

    def test_unmapped_required_state_cannot_disappear_from_gate(self):
        points = self.plan["cases"][2]["assessment"]["checkpoints"]
        points.remove("state:error")
        report = self.complete()
        self.assertEqual(report["gate"], "inconclusive")
        self.assertFalse(report["product_accepted"])
        self.assertTrue(any("state:error" in gap for gap in report["gaps"]))

    def test_focused_state_deferral_is_explicit_and_not_product_pass(self):
        self.plan["acceptance"]["scope"] = "focused"
        self.plan["acceptance"]["journeys"][0]["states"]["error"] = {"status": "deferred", "reason": "本轮只复核保存路径", "sources": ["本轮范围"]}
        self.plan["cases"][2]["assessment"]["checkpoints"].remove("state:error")
        report = self.complete()
        self.assertEqual(report["gate"], "passed")
        self.assertFalse(report["product_accepted"])
        self.plan["acceptance"]["scope"] = "product"
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_required_case_cannot_contradict_deferred_layer(self):
        self.plan["acceptance"]["scope"] = "focused"
        self.plan["acceptance"]["layers"]["interaction"] = {"status": "deferred", "reason": "未评估", "sources": ["范围"]}
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_non_applicable_state_requires_basis_and_is_visible(self):
        state = {"status": "not_applicable", "reason": "约定为无账号隔离样例", "sources": ["协议测试范围"]}
        self.plan["acceptance"]["journeys"][0]["states"]["permission"] = state
        self.plan["cases"][2]["assessment"]["checkpoints"].remove("state:permission")
        report = self.complete()
        self.assertTrue(report["product_accepted"])
        self.assertTrue(any(e.get("state") == "permission" for e in report["acceptance"]["exceptions"]))
        state["reason"] = ""
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_declared_api_cannot_hide_discovered_gui(self):
        self.plan["acceptance"]["surfaces"] = ["api"]
        result = readiness(validate(self.plan), project_snapshot(self.root))
        self.assertTrue(any("index.html" in g for g in result["gaps"]))

    def test_no_ui_signal_does_not_prove_no_ui(self):
        self.plan["acceptance"]["surfaces"] = ["unknown"]
        self.assertTrue(readiness(validate(self.plan))["gaps"])

    def test_surface_exclusion_requires_reason_and_remains_in_report(self):
        policy = self.plan["acceptance"]
        policy["surfaces"] = ["api"]
        policy["surface_exclusions"] = [{"path": "index.html", "reason": "示例静态文件不属于被测服务", "sources": ["范围约定"]}]
        self.assertFalse(any("界面线索" in g for g in readiness(validate(self.plan))["gaps"]))
        policy["surface_exclusions"][0]["reason"] = ""
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_gui_interaction_cannot_be_not_applicable(self):
        self.plan["acceptance"]["layers"]["interaction"] = {"status": "not_applicable", "reason": "跳过", "sources": ["猜测"]}
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_product_scope_cannot_defer_need_fit(self):
        self.plan["acceptance"]["layers"]["need_fit"] = {"status": "deferred", "reason": "稍后", "sources": ["计划"]}
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_interaction_waits_for_task_baseline_automatically(self):
        self.assertFalse(self.prepare("U1")["allowed"])
        self.baseline()
        self.assertTrue(self.prepare("U1")["allowed"])

    def test_all_required_baseline_cases_must_pass(self):
        second = copy.deepcopy(self.plan["cases"][1])
        second["id"] = "N2"
        self.plan["cases"].append(second)
        self.baseline()
        self.assertFalse(self.prepare("U1")["allowed"])

    def test_modified_baseline_evidence_blocks_following_ui(self):
        self.baseline()
        proof = next((self.directory / "evidence/N1/1").glob("0-*.txt"))
        proof.write_text("changed")
        self.assertFalse(self.prepare("U1")["allowed"])

    def test_missing_preflight_preserves_cost_but_cannot_pass(self):
        report = self.observe(self.payload("N1", prepare=False))
        row = next(r for r in report["cases"] if r["id"] == "N1")
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(row["attempts"][0]["observed_status"], "passed")
        self.assertEqual(report["usage"]["execution_seconds"], 1)

    def test_receipt_cannot_be_replayed_for_next_attempt(self):
        payload = self.payload("N1")
        self.observe(payload)
        report = self.observe(payload)
        self.assertEqual(next(r for r in report["cases"] if r["id"] == "N1")["status"], "blocked")

    def test_receipt_cannot_be_borrowed_from_another_case(self):
        payload = self.payload("N1")
        self.observe(payload)
        ui = self.payload("U1", prepare=False)
        ui["check_id"] = payload["check_id"]
        report = self.observe(ui)
        self.assertEqual(report["cases"][2]["status"], "blocked")

    def test_missing_checkpoint_or_evidence_link_is_blocked(self):
        payload = self.payload("N1")
        payload["assertions"] = payload["assertions"][:1]
        payload["assertions"][0]["evidence_indices"] = [99]
        report = self.observe(payload)
        self.assertEqual(report["cases"][1]["status"], "blocked")

    def test_api_result_cannot_be_labeled_interaction(self):
        self.baseline()
        payload = self.payload("U1")
        payload["method"] = "analysis"
        payload["execution"]["backend_bypass"] = True
        report = self.observe(payload)
        self.assertEqual(report["cases"][2]["status"], "blocked")

    def test_agent_observation_cannot_be_labeled_human(self):
        self.baseline()
        payload = self.payload("U1")
        payload["method"] = "human_observation"
        report = self.observe(payload)
        self.assertEqual(report["cases"][2]["status"], "blocked")

    def test_missing_actual_trace_blocks_ui_even_with_passed_assertions(self):
        self.baseline()
        payload = self.payload("U1")
        payload["execution"]["trace"] = []
        report = self.observe(payload)
        self.assertEqual(report["cases"][2]["status"], "blocked")

    def test_command_adapter_cannot_substitute_semantic_review(self):
        self.plan["cases"][2]["executor"] = copy.deepcopy(self.plan["cases"][0]["executor"])
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_complete_protocol_passes_and_scope_gate_matches(self):
        report = self.complete()
        self.assertEqual(report["gate"], "passed")
        self.assertTrue(report["product_accepted"])
        self.assertEqual(set(report["acceptance"]["results"].values()), {"passed"})
        self.assertEqual(self.cli("gate", "--session-dir", str(self.directory)).returncode, 0)

    def test_focused_pass_cannot_satisfy_product_release_gate(self):
        self.plan["acceptance"] = focused_policy()
        self.plan["acceptance"]["surfaces"] = ["gui"]
        self.plan["cases"] = self.plan["cases"][:1]
        self.plan["cases"][0].pop("assessment")
        save(self.plan_path, self.plan)
        run(self.plan_path, self.directory)
        report = report_session(self.directory)
        self.assertEqual(report["gate"], "passed")
        self.assertFalse(report["product_accepted"])
        self.assertEqual(self.cli("gate", "--session-dir", str(self.directory)).returncode, 2)
        self.assertEqual(self.cli("gate", "--session-dir", str(self.directory), "--scope", "focused").returncode, 0)

    def test_api_only_product_can_explain_no_human_interface(self):
        policy = self.plan["acceptance"]
        policy["surfaces"] = ["api"]
        policy["layers"]["interaction"] = {"status": "not_applicable", "reason": "服务只被系统调用", "sources": ["范围约定"]}
        policy["surface_exclusions"] = [{"path": "index.html", "reason": "非产品演示素材", "sources": ["范围约定"]}]
        self.plan["cases"] = self.plan["cases"][:2]
        self.baseline()
        run(self.plan_path, self.directory)
        report = report_session(self.directory)
        self.assertTrue(report["product_accepted"])
        self.assertEqual(report["acceptance"]["results"]["interaction"], "not_applicable")

    def test_report_rechecks_receipt_and_original_observation(self):
        self.complete()
        session = load(self.directory / "session.json")
        session["checks"] = {}
        save(self.directory / "session.json", session)
        self.assertFalse(report_session(self.directory)["product_accepted"])

    def test_handoff_uses_disk_state_without_rerunning_finished_cases(self):
        self.baseline()
        prepared = self.cli("check", "--plan", str(self.plan_path), "--session-dir", str(self.directory), "--case", "U1")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        payload = self.payload("U1", prepare=False)
        payload["check_id"] = json.loads(prepared.stdout)["check_id"]
        path = self.base / "next-agent-observation.json"
        save(path, payload)
        imported = self.cli("record", "--plan", str(self.plan_path), "--session-dir", str(self.directory), "--observation", str(path))
        self.assertEqual(imported.returncode, 2)  # implementation not yet run
        self.assertEqual(self.cli("run", "--plan", str(self.plan_path), "--session-dir", str(self.directory)).returncode, 0)
        self.cli("run", "--plan", str(self.plan_path), "--session-dir", str(self.directory))
        self.assertEqual(len(load(self.directory / "session.json")["results"]["C1"]), 1)

    def test_legacy_plan_cannot_execute_or_claim_new_acceptance(self):
        self.plan["schema_version"] = "1.0"
        self.plan.pop("acceptance")
        self.plan["cases"] = self.plan["cases"][:1]
        save(self.plan_path, self.plan)
        with self.assertRaises(QAError):
            run(self.plan_path, self.directory)
        save(self.directory / "session.json", {"plan": self.plan, "plan_hash": digest(self.plan), "results": {}, "notes": []})
        report = report_session(self.directory)
        self.assertEqual(report["acceptance"]["scope"], "legacy")
        self.assertFalse(report["product_accepted"])

    def test_legacy_passing_results_are_not_upgraded_to_new_product_pass(self):
        self.complete()
        session = load(self.directory / "session.json")
        session["plan"]["schema_version"] = "1.0"
        session["plan"].pop("acceptance")
        session["plan_hash"] = digest(session["plan"])
        save(self.directory / "session.json", session)
        report = report_session(self.directory)
        self.assertEqual(report["counts"]["passed"], 3)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertFalse(report["product_accepted"])

    def test_missing_acceptance_contract_is_rejected(self):
        self.plan.pop("acceptance")
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_init_defaults_to_product_without_inventing_decisions(self):
        directory = self.base / "new-run"
        result = self.cli("init", "--project", str(self.root), "--session-dir", str(directory), "--goal", "实际验收")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = load(directory / "plan.json")
        self.assertEqual(plan["schema_version"], "1.1")
        self.assertEqual(plan["acceptance"]["scope"], "product")
        self.assertEqual(plan["acceptance"]["sources"], [])
        self.assertEqual(plan["snapshot"]["ui_signals"], ["index.html"])

    def test_readiness_handles_plan_outside_project(self):
        result = self.cli("readiness", "--plan", str(self.plan_path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["obligations"])

    def test_session_cannot_exclude_entire_project_from_snapshot(self):
        with self.assertRaises(QAError):
            run(self.plan_path, self.root)
        result = self.cli("init", "--project", str(self.root), "--session-dir", str(self.root), "--goal", "test")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
