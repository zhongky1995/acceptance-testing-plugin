"""Regression tests for omissions, cross-contract drift, evidence binding and cost."""
import copy
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import test_acceptance as acceptance_tests
import test_runtime as runtime_tests
from qa_contracts import validate
from qa_policy import coverage
from qa_runtime import check_case, record, run
from qa_report import report_session
from qa_store import QAError, digest, load, save


class AssuranceTests(unittest.TestCase):
    setUp = acceptance_tests.AcceptanceTests.setUp
    prepare = acceptance_tests.AcceptanceTests.prepare
    payload = acceptance_tests.AcceptanceTests.payload
    observe = acceptance_tests.AcceptanceTests.observe
    baseline = acceptance_tests.AcceptanceTests.baseline
    complete = acceptance_tests.AcceptanceTests.complete
    cli = acceptance_tests.AcceptanceTests.cli

    def test_missing_risk_category_is_not_silently_optional(self):
        del self.plan["assurance"]["features"]["collections"]
        with self.assertRaises(QAError):
            validate(self.plan)

    def test_unknown_risk_blocks_conclusion(self):
        self.plan["assurance"]["features"]["collections"]["status"] = "unknown"
        self.assertEqual(self.complete()["gate"], "inconclusive")

    def test_limit_sample_is_required_even_with_typical_success(self):
        self.plan["assurance"]["features"]["collections"]["status"] = "required"
        self.plan["assurance"]["samples"][0]["factors"] = {"collections": "typical"}
        result = coverage(self.plan)
        self.assertTrue(any("collections/limit" in g for g in result["gaps"]))
        self.assertTrue(any("collections/empty" in g for g in result["gaps"]))

    def test_interface_requires_real_contract_adapter(self):
        self.plan["assurance"]["features"]["interfaces"]["status"] = "required"
        self.plan["assurance"]["boundaries"] = [{"id": "B1", "producer": "producer.py", "consumer": "consumer.py", "reason": "验证序列化边界"}]
        self.assertTrue(any("B1/boundary" in g for g in coverage(self.plan)["gaps"]))

    def test_same_input_under_two_ids_is_not_representative(self):
        samples = self.plan["assurance"]["samples"]
        samples[1].update(path=samples[0]["path"], sha256=samples[0]["sha256"])
        self.assertTrue(any("两份内容不同" in g for g in coverage(self.plan)["gaps"]))

    def test_unbound_sample_output_cannot_pass(self):
        self.plan["cases"][0]["executor"]["argv"][2] = "import json,sys;json.dump({'tests':[{'name':'ok','status':'passed'}]},open(sys.argv[1],'w'))"
        self.assertEqual(self.complete()["cases"][0]["status"], "blocked")

    def test_single_run_cannot_claim_product_acceptance(self):
        self.plan["assurance"]["claim"] = "single_run"
        report = self.complete()
        self.assertEqual(report["gate"], "passed")
        self.assertFalse(report["product_accepted"])
        self.assertEqual(self.cli("gate", "--session-dir", str(self.directory)).returncode, 2)

    def test_unobserved_repeat_window_cannot_be_claimed(self):
        self.plan["assurance"].update(claim="sustained", repeat={"min_runs": 2, "min_span_seconds": 30})
        report = self.complete()
        self.assertFalse(report["product_accepted"])
        self.assertTrue(any("持续观察" in g for g in report["gaps"]))

    def test_observed_repeats_can_satisfy_bounded_window(self):
        self.plan["assurance"].update(claim="sustained", repeat={"min_runs": 2, "min_span_seconds": 0.001})
        self.complete()
        self.observe(self.payload("N1"))
        self.observe(self.payload("U1"))
        run(self.plan_path, self.directory, retry=True)
        self.assertTrue(report_session(self.directory)["product_accepted"])

    def test_copied_expected_text_blocked(self):
        self.baseline()
        payload = self.payload("U1")
        next(a for a in payload["assertions"] if a["checkpoint"] == "step:S1")["expected"] = "其他任务的缓存取材已完成"
        report = self.observe(payload)
        self.assertEqual(report["cases"][2]["status"], "blocked")
        self.assertIn("冻结方案", report["cases"][2]["attempts"][0]["reason"])

    def test_cross_case_binding_is_not_reusable_as_new_evidence(self):
        old = self.payload("N1")
        self.observe(old)
        payload = self.payload("U1")
        payload["assertions"][0]["binding_id"] = old["assertions"][0]["binding_id"]
        self.assertEqual(self.observe(payload)["cases"][2]["status"], "blocked")

    def test_wrong_step_trace_is_blocked(self):
        self.baseline()
        payload = self.payload("U1")
        payload["execution"]["trace"][-1]["planned_action"] = "复制另一个页面"
        self.assertEqual(self.observe(payload)["cases"][2]["status"], "blocked")

    def test_second_sample_needs_its_own_trace(self):
        self.baseline()
        payload = self.payload("U1")
        for trace in payload["execution"]["trace"]:
            trace["sample_id"] = "A"
        self.assertEqual(self.observe(payload)["cases"][2]["status"], "blocked")

    def test_missing_sample_locator_is_blocked(self):
        payload = self.payload("N1")
        payload["sample_evidence"][1]["locator"] = ""
        self.assertEqual(self.observe(payload)["cases"][1]["status"], "blocked")

    def test_zero_self_reported_time_does_not_erase_observation_window(self):
        payload = self.payload("N1")
        payload["duration_seconds"] = 0
        session = load(self.directory / "session.json")
        session["checks"][payload["check_id"]]["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=4)).isoformat()
        save(self.directory / "session.json", session)
        report = self.observe(payload)
        self.assertGreater(report["usage"]["observation_window_seconds"], 3)

    def test_old_protocol_is_readable_but_cannot_execute_or_approve(self):
        self.complete()
        session = load(self.directory / "session.json")
        session["plan"]["schema_version"] = "1.1"
        session["plan_hash"] = digest(session["plan"])
        save(self.directory / "session.json", session)
        report = report_session(self.directory)
        self.assertFalse(report["product_accepted"])
        save(self.plan_path, session["plan"])
        with self.assertRaises(QAError):
            run(self.plan_path, self.directory)


class LedgerTests(unittest.TestCase):
    setUp = runtime_tests.RuntimeTests.setUp
    command = runtime_tests.RuntimeTests.command
    execute = runtime_tests.RuntimeTests.execute
    report = runtime_tests.RuntimeTests.report

    def observation(self, cid="C1", external=True):
        from acceptance_fixtures import bind_payload
        case = next(c for c in self.plan["cases"] if c["id"] == cid)
        case["executor"] = {"kind": "observation", "external_calls": external, "external_call_bound": 1 if external else 0,
                            "external_token_bound": 100 if external else 0, "external_cost_bound": 1 if external else 0}
        self.plan["limits"].update(max_external_calls=2, max_external_tokens=200, max_external_cost=2)
        save(self.plan_path, self.plan)
        ticket = check_case(self.plan_path, self.session, cid)
        self.assertTrue(ticket["allowed"], ticket)
        payload = {**ticket["observation_template"], "status": "passed", "reason": "离线计量协议样本", "evidence_files": [str(self.root / "app.py")]}
        bind_payload(self.plan, case, payload)
        if external:
            payload["usage"]["requests"] = [{"id": "request-1", "status": "succeeded", "tokens": 80, "cost": 0.4, "evidence": "0-app.py:1 synthetic request"}]
        return payload

    def submit(self, payload):
        path = Path(self.temp.name) / "observation.json"
        save(path, payload)
        record(self.plan_path, self.session, path)
        return self.report()

    def test_unknown_price_is_incomplete_not_zero_or_free(self):
        payload = self.observation()
        payload["usage"]["requests"][0]["cost"] = None
        report = self.submit(payload)
        self.assertEqual(report["gate"], "passed")
        self.assertTrue(report["usage"]["cost_actual_incomplete"])
        self.assertEqual(report["usage"]["external_cost_reserved"], 1)
        self.assertEqual(report["usage"]["external_calls_actual"], 1)
        self.assertEqual(report["usage"]["external_tokens_actual_known"], 80)

    def test_missing_usage_is_blocked_and_reservation_kept(self):
        payload = self.observation()
        del payload["usage"]
        report = self.submit(payload)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertTrue(report["usage"]["cost_actual_incomplete"])
        self.assertEqual(report["usage"]["external_calls_reserved"], 1)
        self.assertTrue(report["usage"]["calls_actual_incomplete"])
        self.assertTrue(report["usage"]["tokens_actual_incomplete"])

    def test_undeclared_calls_preserved_and_blocked(self):
        payload = self.observation(external=False)
        payload["usage"]["requests"] = [{"id": "surprise", "status": "succeeded", "tokens": 20, "cost": 0.2, "evidence": "fixture:1"}]
        report = self.submit(payload)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertEqual(report["usage"]["external_calls_actual"], 1)
        self.assertEqual(report["usage"]["external_cost_actual_known"], 0.2)

    def test_failed_request_still_consumes_budget(self):
        payload = self.observation()
        payload["usage"]["requests"][0]["status"] = "failed"
        payload["status"] = "failed"
        payload["assertions"][0]["passed"] = False
        report = self.submit(payload)
        self.assertEqual(report["gate"], "failed")
        self.assertEqual(report["usage"]["external_cost_actual_known"], 0.4)
        self.assertEqual(report["usage"]["external_calls_actual"], 1)

    def test_unknown_request_outcome_blocks(self):
        payload = self.observation()
        payload["usage"]["requests"][0]["status"] = "unknown"
        self.assertEqual(self.submit(payload)["gate"], "inconclusive")

    def test_pending_check_reserves_budget_and_is_idempotent(self):
        self.plan["cases"].append(copy.deepcopy(self.plan["cases"][0]))
        self.plan["cases"][1]["id"] = "C2"
        for case in self.plan["cases"]:
            case["executor"] = {"kind": "observation", "external_calls": True, "external_call_bound": 1, "external_cost_bound": 1, "external_token_bound": 10}
        self.plan["limits"].update(max_external_calls=1, max_external_tokens=10, max_external_cost=1)
        save(self.plan_path, self.plan)
        first = check_case(self.plan_path, self.session, "C1")
        second = check_case(self.plan_path, self.session, "C1")
        self.assertEqual(first["check_id"], second["check_id"])
        self.assertFalse(check_case(self.plan_path, self.session, "C2")["allowed"])
        self.assertEqual(self.report()["usage"]["pending_checks"], 1)

    def test_same_request_on_retry_cannot_masquerade_as_new_execution(self):
        payload = self.observation()
        self.submit(payload)
        ticket = check_case(self.plan_path, self.session, "C1")
        payload["check_id"] = ticket["check_id"]
        report = self.submit(payload)
        self.assertEqual(report["gate"], "inconclusive")
        self.assertTrue(report["usage"]["duplicate_requests"])
        self.assertEqual(report["usage"]["external_calls_actual"], 1)

    def test_explicit_request_reuse_is_counted_once(self):
        from acceptance_fixtures import bind_payload
        second = copy.deepcopy(self.plan["cases"][0])
        second.update(id="C2", executor={"kind": "observation", "external_calls": False})
        self.plan["cases"].append(second)
        self.submit(self.observation())
        ticket = check_case(self.plan_path, self.session, "C2")
        payload = {**ticket["observation_template"], "status": "passed", "reason": "复核同一请求的另一断言", "evidence_files": [str(self.root / "app.py")]}
        bind_payload(self.plan, second, payload)
        payload["usage"]["reused_request_ids"] = ["request-1"]
        report = self.submit(payload)
        self.assertEqual(report["gate"], "passed")
        self.assertEqual(report["usage"]["external_calls_actual"], 1)
        self.assertEqual(report["usage"]["external_cost_actual_known"], 0.4)

    def test_nonexistent_reuse_cannot_hide_a_call(self):
        payload = self.observation(external=False)
        payload["usage"]["reused_request_ids"] = ["not-in-this-run"]
        self.assertEqual(self.submit(payload)["gate"], "inconclusive")

    def test_changed_ledger_metadata_fails_readback(self):
        self.submit(self.observation())
        session = load(self.session / "session.json")
        session["results"]["C1"][0]["cost_reserved"] = 0
        save(self.session / "session.json", session)
        self.assertEqual(self.report()["cases"][0]["status"], "blocked")

    def test_external_command_without_sidecar_cannot_pass(self):
        self.plan["cases"][0]["executor"].update(external_calls=True, external_call_bound=1, external_token_bound=10, external_cost_bound=1)
        self.plan["limits"].update(max_external_calls=1, max_external_tokens=10, max_external_cost=1)
        self.execute()
        self.assertEqual(self.report()["gate"], "inconclusive")
        self.assertTrue(self.report()["usage"]["cost_actual_incomplete"])

    def test_contract_demo_reproduces_drift_and_fixed_version_passes(self):
        path = Path(__file__).resolve().parents[1] / "scripts/contract_demo.py"
        output = Path(self.temp.name) / "contract-demo"
        proc = subprocess.run([sys.executable, str(path), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(load(output / "comparison.json"), {"before": "failed", "after": "passed", "product_accepted": False})
        detail = load(output / "before/evidence/C1/1/result.json")
        boundary = next(r for r in detail["sample_results"] if r["id"] == "boundary")
        self.assertTrue(boundary["actual"]["producer_accepts"])
        self.assertFalse(boundary["actual"]["consumer_accepts"])

    def test_forged_contract_pass_flag_is_recomputed(self):
        from qa_adapters import parse
        path = Path(self.temp.name) / "forged.json"
        save(path, {"sample_results": [{"id": "B", "status": "passed", "returncode": 0, "expected_producer": True, "expected_consumer": True,
                                      "actual": {"producer_accepts": True, "consumer_accepts": False, "producer_evidence": "p:1", "consumer_evidence": "c:1"}}]})
        self.assertEqual(parse("contract", path, 0)["status"], "failed")
