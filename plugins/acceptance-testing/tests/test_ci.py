"""Offline project CI tests: actual git changes, generated files, real commands/gate."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('qa_ci', SCRIPTS / 'qa_ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class ProjectCITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project CI ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git('init', '-q')
        self.git('config', 'user.email', 'ci@example.invalid')
        self.git('config', 'user.name', 'Offline CI fixture')
        self.write('server/rule.py', 'VALUE = 1\n')
        self.write('ui/page.html', '<button>save</button>')
        self.write('docs/guide.md', 'User task')
        ci.initialize(self.root)
        self.policy = ci.load(self.root / '.acceptance-ci/policy.json')
        for g in self.policy['groups']:
            g['commands'] = [{'argv': ['{python}', '-c', 'assert 1+1==2'], 'timeout_seconds': 2, 'external_calls': False, 'installs': False}]
        self.policy['groups'][1]['paths'] = ['server/**', 'db/**']
        self.policy['groups'][2]['paths'] = ['ui/**', 'docs/**']
        self.commit('base')
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL, text=True)

    def write(self, path, text):
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')

    def commit(self, msg):
        self.git('add', '.')
        self.git('commit', '-qm', msg)

    def selected(self, files, profile='change'):
        return {d['id'] for d in ci.select(ci.validate(self.policy), files, profile) if d['selected']}

    def execute(self, profile='change', base=None, name='selection.json'):
        return ci.run(self.root, ci.validate(self.policy), profile, base or self.base, self.root / '.acceptance' / name)

    def test_frontend_and_backend_select_their_risk(self):
        self.assertEqual(self.selected(['server/rule.py']), {'fast', 'integration'})
        self.assertEqual(self.selected(['ui/page.html']), {'fast', 'experience'})
        self.assertEqual(self.selected(['docs/guide.md']), {'fast', 'experience'})

    def test_unknown_files_and_ci_configuration_expand_coverage(self):
        self.assertEqual(self.selected(['new-language/Main.xyz']), {'fast', 'integration', 'experience'})
        self.assertEqual(self.selected(['.acceptance-ci/policy.json']), {'fast', 'integration', 'experience'})
        self.assertEqual(self.selected(['.github/workflows/test.yml']), {'fast', 'integration', 'experience'})

    def test_missing_base_does_not_skip_risk_checks(self):
        files, _ = ci.changed_files(self.root, '0'*40)
        self.assertIsNone(files)
        self.assertEqual(self.selected(files), {'fast', 'integration', 'experience'})
        files, _ = ci.changed_files(self.root, 'abc1234')
        self.assertIsNone(files)

    def test_actual_rename_evaluates_old_and_new_path(self):
        (self.root / 'server/rule.py').rename(self.root / 'ui/rule.py')
        self.commit('rename')
        files, _ = ci.changed_files(self.root, self.base)
        self.assertIn('server/rule.py', files)
        self.assertIn('ui/rule.py', files)
        self.assertEqual(self.selected(files), {'fast', 'integration', 'experience'})

    def test_deleted_file_and_space_in_name_are_not_lost(self):
        (self.root / 'server/rule.py').unlink()
        self.write('ui/with spaces.html', 'new')
        self.commit('delete and add')
        files, _ = ci.changed_files(self.root, self.base)
        self.assertEqual(set(files), {'server/rule.py', 'ui/with spaces.html'})

    def test_full_profile_stays_offline_and_delivery_is_explicit(self):
        self.assertEqual(self.selected([], 'full'), {'fast', 'integration', 'experience'})
        self.assertEqual(self.selected([], 'delivery'), {'fast', 'integration', 'experience', 'delivery'})

    def test_unconfigured_selected_group_fails_closed(self):
        self.policy['groups'][0]['commands'] = []
        report = self.execute()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['results'][0]['status'], 'blocked')
        self.assertFalse(report['product_accepted'])

    def test_not_applicable_needs_reason_and_is_visible(self):
        g = self.policy['groups'][2]
        g.update(status='not_applicable', reason='headless service; no user entry', sources=['architecture.md'])
        report = self.execute(profile='full')
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(next(d for d in report['decisions'] if d['id']=='experience')['selected'])
        g['reason'] = ''
        with self.assertRaises(ci.CIError): ci.validate(self.policy)

    def test_zero_commands_cannot_be_used_for_base_check(self):
        for status in ['not_applicable', 'optional']:
            self.policy['groups'][0]['status'] = status
            with self.assertRaises(ci.CIError): ci.validate(self.policy)

    def test_paid_or_install_commands_are_rejected(self):
        c = self.policy['groups'][0]['commands'][0]
        c['external_calls'] = True
        with self.assertRaises(ci.CIError): ci.validate(self.policy)
        c.update(external_calls=False, installs=True)
        with self.assertRaises(ci.CIError): ci.validate(self.policy)

    def test_failure_stops_more_expensive_work(self):
        self.policy['groups'][0]['commands'][0]['argv'] = ['{python}', '-c', 'raise SystemExit(1)']
        self.policy['groups'][1]['commands'][0]['argv'] = ['{python}', '-c', "open('should-not-exist','w').write('bad')"]
        report = self.execute('full')
        self.assertEqual(report['status'], 'failed')
        self.assertFalse((self.root/'should-not-exist').exists())
        self.assertTrue(any(r['status']=='not_run' for r in report['results']))

    def test_missing_executable_and_timeout_block(self):
        cmd = self.policy['groups'][0]['commands'][0]
        cmd['argv'] = ['unavailable-project-ci-fixture-command']
        self.assertEqual(self.execute(name='missing.json')['results'][0]['status'], 'blocked')
        cmd['argv'] = ['{python}', '-c', 'import time;time.sleep(10)']
        cmd['timeout_seconds'] = .03
        self.assertEqual(self.execute(name='timeout.json')['results'][0]['status'], 'blocked')

    def test_report_cannot_be_reused_or_overwritten(self):
        self.execute()
        with self.assertRaises(ci.CIError): self.execute()

    def test_init_never_overwrites_existing_project_files(self):
        target = self.root / '.github/workflows/acceptance-ci.yml'
        before = target.read_bytes()
        with self.assertRaises(ci.CIError): ci.initialize(self.root)
        self.assertEqual(target.read_bytes(), before)

    def test_existing_workflow_collision_does_not_create_half_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            target=root/'.github/workflows/acceptance-ci.yml'
            target.parent.mkdir(parents=True);target.write_text('user workflow')
            with self.assertRaises(ci.CIError): ci.initialize(root)
            self.assertFalse((root/'.acceptance-ci').exists())

    def test_existing_ci_can_reuse_runner_without_new_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            existing=root/'.github/workflows/existing.yml'
            existing.parent.mkdir(parents=True);existing.write_text('original CI')
            ci.initialize(root, workflow=False)
            self.assertEqual(existing.read_text(),'original CI')
            self.assertFalse((root/'.github/workflows/acceptance-ci.yml').exists())
            self.assertTrue((root/'.acceptance-ci/engine/qa.py').is_file())

    def test_generated_cli_runs_offline_in_fresh_process(self):
        ci.save(self.root/'.acceptance-ci/policy.json', self.policy)
        proc=subprocess.run([sys.executable, '.acceptance-ci/ci.py', 'run', '--base', self.base], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        report=json.loads(proc.stdout)
        self.assertEqual(report['status'],'passed')
        self.assertFalse(report['product_accepted'])

    def test_delivery_cannot_pass_without_fresh_product_evidence(self):
        report=self.execute('delivery')
        self.assertEqual(report['status'],'failed')
        self.assertEqual(report['results'][-1]['group'],'product-gate')
        self.assertFalse(report['product_accepted'])

    def test_delivery_rejects_focused_even_if_all_technical_checks_pass(self):
        # Generate genuine current-CLI evidence using the installed copy, no forged report.
        sys.path.insert(0,str(SCRIPTS))
        from acceptance_fixtures import assurance_policy, focused_policy
        from qa_store import project_snapshot, save
        from qa_runtime import run
        directory=self.root/'.acceptance/ci'
        plan={'schema_version':'1.2','project_root':str(self.root),'scenario':'local-iteration','goal':'offline focused fixture',
              'snapshot':project_snapshot(self.root),'environment':{'mode':'CI fixture'},'allow_install':False,
              'limits':{'execution_seconds':10,'max_attempts_per_case':2,'max_external_cost':0,'currency':'unit'},
              'acceptance':focused_policy(),'assurance':assurance_policy(),
              'requirements':[{'id':'R1','statement':'rule','status':'confirmed','required':True,'sources':['fixture']}],
              'cases':[{'id':'C1','title':'rule','dimension':'functional','requirement_ids':['R1'],'required':True,'in_scope':True,'expected':'value valid',
                        'executor':{'kind':'command','argv':['{python}','-c','assert True'],'adapter':'exit','timeout_seconds':2}}]}
        save(directory/'plan.json',plan);run(directory/'plan.json',directory)
        report=self.execute('delivery')
        self.assertEqual(report['status'],'failed')
        self.assertFalse(report['product_accepted'])

    def product_fixture(self):
        # Synthetic observations test the CLI protocol, not real user acceptance.
        import test_acceptance as fixtures
        fixture=fixtures.AcceptanceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ci.initialize(fixture.root)
        fixture.directory=fixture.root/'.acceptance/ci'
        from qa_store import project_snapshot
        fixture.plan['snapshot']=project_snapshot(fixture.root)
        self.assertTrue(fixture.complete()['product_accepted'])
        return fixture

    def test_delivery_accepts_current_complete_product_evidence(self):
        fixture=self.product_fixture()
        report=ci.run(fixture.root,self.policy,'delivery','',fixture.root/'.acceptance/selection.json')
        self.assertEqual(report['status'],'passed')
        self.assertTrue(report['product_accepted'])

    def test_delivery_rechecks_snapshot_instead_of_trusting_old_pass(self):
        fixture=self.product_fixture()
        (fixture.root/'PRD.md').write_text('Changed after acceptance')
        report=ci.run(fixture.root,self.policy,'delivery','',fixture.root/'.acceptance/selection.json')
        self.assertEqual(report['status'],'failed')
        self.assertFalse(report['product_accepted'])

    def test_untrusted_base_is_never_executed_as_shell(self):
        files,_=ci.changed_files(self.root,'$(touch untrusted)')
        self.assertIsNone(files)
        self.assertFalse((self.root/'untrusted').exists())

    def test_ci_demo_selects_cheap_path_and_catches_real_regression(self):
        proc = subprocess.run([sys.executable, str(SCRIPTS/'ci_demo.py'), '--output', str(self.root/'demo')], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        self.assertEqual(ci.load(self.root/'demo/comparison.json'), {'docs':'passed','contract_change':'failed','product_accepted':False})

    def test_paths_cannot_escape_the_project(self):
        with self.assertRaises(ci.CIError):ci.within(self.root,'../private')
        with self.assertRaises(ci.CIError):ci.within(self.root,str(self.root))

    def test_budget_must_be_finite_and_bounded(self):
        for value in [float('nan'),float('inf'),0,600,True]:
            self.policy['max_seconds']=value
            with self.assertRaises(ci.CIError):ci.validate(self.policy)


if __name__=='__main__':
    unittest.main()
