import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
from acceptance_fixtures import assurance_policy, focused_policy
from qa_contracts import validate
from qa_store import QAError, file_hash, load, project_snapshot, save
from qa_workflow import read_result


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "project"
        shutil.copytree(PLUGIN / "tests/fixtures/batch-project", self.root)
        self.session = Path(tmp.name) / "run"
        sample = self.root / "mixed.json"
        save(sample, {"batch": "batch-7", "states": {"A": "posted"},
                      "rows": [{"id": "A", "amount": 2}, {"id": "B"}, {"id": "C", "amount": 3}]})
        assurance = assurance_policy()
        assurance["samples"] = [{"id": "mixed", "kind": "fixture", "path": sample.name,
                                 "sha256": file_hash(sample), "purpose": "batch recovery control"}]
        self.expected = {"stage": "validate", "fault": "missing-amount", "run_id": "batch-7",
                         "states": {"A": "posted", "B": "held", "C": "posted"},
                         "next_inputs": {"post": ["C"]}, "effects": {"post:A": 0, "post:B": 0, "post:C": 1}}
        self.case = {"id": "resume", "title": "同批续办", "dimension": "reliability", "expected": "C 实际入账一次",
                     "in_scope": True, "required": True, "requirement_ids": ["R1"], "sample_ids": ["mixed"],
                     "workflow_expectation": self.expected, "executor": {"kind": "command", "adapter": "workflow",
                     "argv": ["{python}", "probe.py", sample.name, "{evidence_dir}"], "timeout_seconds": 5,
                     "result_path": "{evidence_dir}/result.json"}}
        self.plan = {"schema_version": "1.2", "project_root": str(self.root), "snapshot": project_snapshot(self.root),
                     "goal": "verify recovery", "scenario": "local-iteration", "environment": {"mode": "offline"},
                     "limits": {"execution_seconds": 20, "max_external_cost": 0, "currency": "CNY", "max_attempts_per_case": 2},
                     "allow_install": False, "requirements": [{"id": "R1", "status": "confirmed", "required": True,
                     "statement": "独立输入继续入账，已完成动作不重复", "sources": ["example decision"]}],
                     "acceptance": focused_policy(), "assurance": assurance, "cases": [self.case]}

    def run_plan(self):
        plan_path = self.session / "plan.json"
        save(plan_path, self.plan)
        proc = self.cli("run", "--plan", str(plan_path))
        return proc.returncode, load(self.session / "report.json")

    def cli(self, action, *args):
        return subprocess.run([sys.executable, str(PLUGIN / "scripts/qa.py"), action,
                               "--session-dir", str(self.session), *args], text=True, capture_output=True)

    def test_same_batch_recovery_passes_focused_gate_only(self):
        code, report = self.run_plan()
        self.assertEqual((code, report["gate"], report["product_accepted"]), (0, "passed", False))
        self.assertEqual(self.cli("gate", "--scope", "focused").returncode, 0)
        (self.session / "evidence/resume/1/events.json").unlink()
        self.assertEqual(self.cli("gate", "--scope", "focused").returncode, 2)

    def test_batch_stall_is_failed_and_an_independent_control_still_runs(self):
        src = self.root / "probe.py"
        src.write_text(src.read_text().replace('batch["states"][key] = "held"\n            continue',
                                               'batch["states"][key] = "held"\n            return'))
        control = copy.deepcopy(self.case)
        control["id"] = "normal"
        path = self.root / "normal.json"
        save(path, {"batch": "batch-8", "states": {}, "rows": [{"id": "X", "amount": 8}]})
        self.plan["assurance"]["samples"].append({"id": "normal", "path": path.name, "kind": "fixture",
                                                  "sha256": file_hash(path), "purpose": "normal control"})
        control["sample_ids"] = ["normal"]
        control["executor"]["argv"][2] = path.name
        control["workflow_expectation"].update(fault="none", run_id="batch-8", states={"X": "posted"},
                                              next_inputs={"post": ["X"]}, effects={"post:X": 1})
        self.plan["cases"].append(control)
        self.plan["snapshot"] = project_snapshot(self.root)
        code, report = self.run_plan()
        self.assertEqual((code, report["gate"]), (1, "failed"))
        self.assertEqual([c["status"] for c in report["cases"]], ["failed", "passed"])
        self.assertIn("next_inputs.post", report["cases"][0]["attempts"][0]["reason"])

    def test_probe_error_is_blocked(self):
        self.case["executor"]["argv"] = ["{python}", "-c", "raise SystemExit(3)"]
        code, report = self.run_plan()
        self.assertEqual((code, report["cases"][0]["status"]), (2, "blocked"))

    def test_wrong_object_duplicate_dispatch_wrong_batch_and_extra_effect_fail(self):
        self.run_plan()
        folder = self.session / "evidence/resume/1"
        path = folder / "result.json"
        original = load(path)
        for key, value in (("next_inputs", {"post": ["B"]}), ("next_inputs", {"post": ["C", "C"]}),
                           ("run_id", "batch-8"), ("effects", {**original["effects"], "post:X": 1}),
                           ("effects", {**original["effects"], "post:A": 1}), ("states", {})):
            with self.subTest(key=key, value=value):
                save(path, {**original, key: value})
                self.assertEqual(read_result(self.plan, self.case, path, 0, folder)["status"], "failed")

    def test_evidence_must_match_sample_injection_and_attempt(self):
        self.run_plan()
        folder = self.session / "evidence/resume/1"
        path = folder / "result.json"
        original = load(path)
        for key, value in (("sha256", "other"), ("sample_id", "other"), ("fault", "none"), ("stage", "other"),
                           ("trace_file", "result.json"), ("trace_file", "../old.json"), ("locator", ""),
                           ("effects", {"post:C": True})):
            with self.subTest(key=key, value=value), self.assertRaises(QAError):
                save(path, {**original, key: value})
                read_result(self.plan, self.case, path, 0, folder)

    def test_shared_dependency_and_atomic_stop_follow_the_decision_table(self):
        self.run_plan()
        folder = self.session / "evidence/resume/1"
        path = folder / "result.json"
        receipt = load(path)
        for states, inputs in (({"A": "held", "B": "held", "C": "posted"}, ["C"]),
                               ({"batch-7": "rolled_back"}, [])):
            with self.subTest(states=states):
                self.expected.update(states=states, next_inputs={"post": inputs}, effects={"post": len(inputs)})
                save(path, {**receipt, **self.expected})
                self.assertEqual(read_result(self.plan, self.case, path, 0, folder)["status"], "passed")
                save(path, {**receipt, **self.expected, "next_inputs": {"post": inputs + ["B"]}})
                self.assertEqual(read_result(self.plan, self.case, path, 0, folder)["status"], "failed")

    def test_incomplete_expectation_cannot_be_frozen_or_downgraded(self):
        del self.expected["effects"]
        with self.assertRaises(QAError):
            validate(self.plan)
        self.case["executor"]["adapter"] = "native"
        with self.assertRaises(QAError):
            validate(self.plan)
