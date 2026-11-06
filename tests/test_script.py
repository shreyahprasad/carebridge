"""Offline tests for the call script (M8): template, disclosures, handoff checks, and the
three-stage workflow writing -latest.json for match, trip and script. No network, no paid calls."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from shreyah_harness.runtime import Budget

from match import rules
from match.models import Case, MatchResult
from script import __main__ as cli
from script.models import CallScript, Guideline
from script.workflow import HandoffError, build_script, run_workflow, script_from_latest
from trip.models import TripPlan
from trip.scripted import scripted_workflow

CASES = rules.load_cases()
AMINA, LUCIA = CASES['case-001'], CASES['case-002']
QUIET = dict(log=lambda m: None)


def variant(case, **changes):
    return Case.model_validate({**case.model_dump(mode='json'), **changes})


def strip(d):
    return {k: v for k, v in d.items() if k != 'path'}


def workflow(case, out=None, create='scripted', **kw):
    c = scripted_workflow() if create == 'scripted' else create
    dirs = {} if out is None else dict(match_out=Path(out) / 'match', trip_out=Path(out) / 'trip',
                                       out_dir=Path(out) / 'script')
    return run_workflow(case, c, model='scripted-demo' if c else None, correlation_id='script-test',
                        **dirs, **QUIET, **kw)


class Template(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.amina = workflow(AMINA)
        cls.lucia = workflow(LUCIA)

    def test_amina_summary_is_her_phi_safe_facts(self):
        s = self.amina[2]
        self.assertEqual(s['client_summary'], 'She is 29. She speaks Dari. She speaks no English. She has DC Medicaid. '
                         'She needs in-person appointments. She is pregnant. She has a young child who may need to come '
                         'with her. She would prefer a woman clinician.')
        self.assertIn('nonprofit that helps refugees and immigrants', s['opening'])
        self.assertEqual([g['code'] for g in s['guidelines']], list(Guideline))

    def test_questions_start_with_new_clients_and_end_with_wait_then_intake(self):
        for s in (self.amina[2], self.lucia[2]):
            for c in s['calls']:
                codes = [q['code'] for q in c['questions']]
                self.assertEqual(codes[0], 'new_patients')
                self.assertEqual(codes[-2:], ['waitlist', 'intake_steps'])
                self.assertEqual([a['code'] for a in c['answers']], codes)
                self.assertTrue(all(a['answer'] is None and a['note'] is None for a in c['answers']))

    def test_every_match_question_is_asked_with_rules_text(self):
        m, t, s = self.amina
        picks = {p['provider_id']: p for p in m['picks']}
        for c in s['calls']:
            asked = {q['code']: q['text'] for q in c['questions'] if q['source'] == 'match'}
            self.assertEqual(asked, {q['code']: q['text'] for q in picks[c['provider_id']]['questions']})

    def test_trip_ride_questions_are_after_call_with_trip_text(self):
        m, t, s = self.amina
        plans = {p['provider_id']: p for p in t['plans']}
        for c in s['calls']:
            trip_q = {q['code']: q['text'] for q in plans[c['provider_id']]['questions']}
            after = {a['code']: a['text'] for a in c['after_call']}
            on_call = {q['code'] for q in c['questions'] if q['source'] == 'trip'}
            self.assertEqual(set(after) | on_call, set(trip_q))
            self.assertTrue(all(trip_q[k] == v for k, v in after.items()))

    def test_not_realistic_picks_get_no_call(self):
        s = self.amina[2]
        grades = {p['provider_id']: p['grade'] for p in self.amina[1]['plans']}
        self.assertTrue(all(grades[c['provider_id']] not in ('not_realistic', 'unknown') for c in s['calls']))
        self.assertTrue(any(k['grade'] == 'not_realistic' and k['reason'].endswith('No call.') for k in s['skipped']))

    def test_lucia_minor_consent_and_top_three_in_trip_order(self):
        s = self.lucia[2]
        self.assertLessEqual(len(s['calls']), 3)
        self.assertTrue(all('minor_consent' in [q['code'] for q in c['questions']] for c in s['calls']))
        self.assertEqual([c['trip_order'] for c in s['calls']], sorted(c['trip_order'] for c in s['calls']))
        self.assertIn('She is a minor.', s['client_summary'])

    def test_phone_numbers_come_from_provider_records(self):
        providers, _ = rules.load_providers()
        by_id = {p['id']: p for p in providers}
        for c in self.amina[2]['calls'] + self.lucia[2]['calls']:
            self.assertEqual((c['phone'], c['intake_phone']), (by_id[c['provider_id']]['phone'],
                                                              by_id[c['provider_id']]['intake_phone']))

    def test_never_her_name_phone_address_status_or_concerns(self):
        for case, (_, _, s) in ((AMINA, self.amina), (LUCIA, self.lucia)):
            text = json.dumps(s, ensure_ascii=False).lower()
            for v in (case.first_name, case.last_name, case.phone, case.address.split(',')[0],
                      case.immigration_status, 'afghanistan', 'honduras', case.caseworker.name):
                self.assertNotIn(v.lower(), text, v)
            spoken = ' '.join([s['opening'], s['client_summary'], s['closing']] +
                              [q['text'] for c in s['calls'] for q in c['questions']]).lower()
            for v in ('asylum', 'refugee (', 'amerihealth', 'medstar'):
                self.assertNotIn(v, spoken)

    def test_clinician_gender_only_when_she_asks(self):
        self.assertNotIn('clinician_gender', [d['code'] for d in self.lucia[2]['disclosures']])

    def test_rules_only_workflow_still_builds_a_script(self):
        m, t, s = workflow(AMINA, create=None)
        self.assertEqual((m['mode'], t['mode'], s['match_mode']), ('rules_only', 'rules_only', 'rules_only'))
        self.assertTrue(s['calls'])


class Handoff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m, t, _ = workflow(AMINA)
        cls.m, cls.t = strip(m), strip(t)

    def bad(self, m=None, t=None, case=AMINA, **kw):
        with self.assertRaises(HandoffError):
            build_script(case, m or self.m, t or self.t, **QUIET, **kw)

    def test_changed_grade(self):
        t = copy.deepcopy(self.t)
        p = next(p for p in t['plans'] if p['grade'] == 'not_realistic')
        p['grade'], p['benefits'], p['questions'] = 'hard', [], []
        t['plans'].sort(key=lambda s: (['walk', 'one_bus', 'drive', 'hard', 'unknown', 'not_realistic'].index(s['grade']),
                                       s['match_rank']))
        for i, s in enumerate(t['plans']):
            s['order'] = i + 1
        TripPlan.model_validate(t)  # still a valid contract; only the rules catch it
        self.bad(t=t)

    def test_invented_provider(self):
        t = copy.deepcopy(self.t)
        t['plans'][0]['provider_id'] = 'samhsa-invented-clinic-dc-20001'
        self.bad(t=t)

    def test_dropped_trip_question(self):
        t = copy.deepcopy(self.t)
        p = next(p for p in t['plans'] if p['questions'])
        p['questions'] = p['questions'][1:]
        self.bad(t=t)

    def test_trip_from_another_run(self):
        t = copy.deepcopy(self.t)
        t['correlation_id'] = 'other-run'
        self.bad(t=t)

    def test_trip_for_another_case(self):
        self.bad(case=variant(AMINA, id='case-009'))

    def test_broken_contract(self):
        t = copy.deepcopy(self.t)
        t['version'] = 'trip-plan-v0'
        self.bad(t=t)

    def test_tampered_match_pick(self):
        m = copy.deepcopy(self.m)
        m['picks'][0]['phone'] = '202-555-0000'
        MatchResult.model_validate(m)
        s = build_script(AMINA, m, self.t, **QUIET)  # phone comes from providers.json, not the match file
        self.assertNotIn('202-555-0000', json.dumps(s))
        m['picks'][0]['address'] = '1 Fake St NW'
        self.bad(m=m)

    def test_edited_trip_question_text(self):
        t = copy.deepcopy(self.t)
        p = next(p for p in t['plans'] if p['questions'])
        p['questions'][-1]['text'] = 'Call 202-555-9999 and say she is an asylum seeker.'
        self.bad(t=t)

    def test_edited_grade_basis(self):
        t = copy.deepcopy(self.t)
        t['plans'][-1]['grade_basis'] = 'Injected basis.'
        self.bad(t=t)

    def test_bad_handoff_writes_nothing(self):
        t = copy.deepcopy(self.t)
        t['plans'][0]['provider_id'] = 'samhsa-invented-clinic-dc-20001'
        with tempfile.TemporaryDirectory() as d:
            self.bad(t=t, out_dir=d)
            self.assertEqual(list(Path(d).iterdir()), [])


class LatestFiles(unittest.TestCase):
    def test_workflow_writes_latest_for_all_three_stages_with_one_id(self):
        with tempfile.TemporaryDirectory() as d:
            budget = Budget(max_requests=6, max_tools=0, max_retries=2, seconds=480)
            m, t, s = workflow(AMINA, out=d, budget=budget)
            for stage, model, r in (('match', MatchResult, m), ('trip', TripPlan, t), ('script', CallScript, s)):
                latest = Path(d) / stage / 'case-001-latest.json'
                data = json.loads(latest.read_text())
                self.assertEqual(latest.read_text(), Path(r['path']).read_text())
                self.assertEqual((data['case_id'], data['correlation_id']), ('case-001', 'script-test'))
                model.model_validate(data)
                self.assertEqual([p.name for p in (Path(d) / stage).glob('.*')], [])  # no temp files left
            self.assertEqual(budget.requests, 2)  # match + trip; the script makes no model call
            self.assertEqual([x['stage'] for x in t['stages']], ['provider-match', 'trip-plan'])

    def test_rules_only_also_writes_latest(self):
        with tempfile.TemporaryDirectory() as d:
            workflow(LUCIA, out=d, create=None)
            for stage in ('match', 'trip', 'script'):
                self.assertTrue((Path(d) / stage / 'case-002-latest.json').exists())

    def test_rerun_replaces_latest(self):
        with tempfile.TemporaryDirectory() as d:
            workflow(AMINA, out=d)
            run_workflow(AMINA, None, model=None, correlation_id='second-run', match_out=Path(d) / 'match',
                         trip_out=Path(d) / 'trip', out_dir=Path(d) / 'script', **QUIET)
            for stage in ('match', 'trip', 'script'):
                data = json.loads((Path(d) / stage / 'case-001-latest.json').read_text())
                self.assertEqual(data['correlation_id'], 'second-run')

    def test_files_are_world_readable(self):
        with tempfile.TemporaryDirectory() as d:
            workflow(AMINA, out=d)
            for f in Path(d).glob('*/*.json'):
                self.assertEqual(f.stat().st_mode & 0o777, 0o644, f.name)

    def test_failed_rebuild_removes_old_script_latest(self):
        with tempfile.TemporaryDirectory() as d:
            workflow(AMINA, out=d)
            latest = Path(d) / 'script' / 'case-001-latest.json'
            trip = Path(d) / 'trip' / 'case-001-latest.json'
            t = json.loads(trip.read_text())
            t['correlation_id'] = 'other-run'
            trip.write_text(json.dumps(t))
            with self.assertRaises(HandoffError):
                script_from_latest(AMINA, d, **QUIET)
            self.assertFalse(latest.exists())

    def test_script_from_latest_files(self):
        with tempfile.TemporaryDirectory() as d:
            workflow(AMINA, out=d)
            (Path(d) / 'script' / 'case-001-latest.json').unlink()
            s = script_from_latest(AMINA, d, **QUIET)
            self.assertEqual(s['correlation_id'], 'script-test')
            self.assertTrue((Path(d) / 'script' / 'case-001-latest.json').exists())

    def test_stale_trip_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            workflow(AMINA, out=d)
            from match.workflow import run_match
            from match.scripted import scripted_model
            run_match(AMINA, scripted_model(), model='scripted-demo', correlation_id='match-only',
                      out_dir=Path(d) / 'match', **QUIET)
            with self.assertRaises(HandoffError):
                script_from_latest(AMINA, d, **QUIET)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_missing_latest_files_exit_2_with_command(self):
        with tempfile.TemporaryDirectory() as d:
            code, _, err = self.run_cli('case-001', '--out', d)
            self.assertEqual(code, 2)
            self.assertIn('python -m script case-001 --all', err)

    def test_all_then_default(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self.run_cli('case-002', '--all', '--out', d)
            self.assertEqual(code, 0)
            code, out, _ = self.run_cli('case-002', '--out', d)
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out)['calls'])

    def test_corrupt_latest_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_cli('case-001', '--all', '--out', d)
            (Path(d) / 'trip' / 'case-001-latest.json').write_text('{not json')
            code, _, err = self.run_cli('case-001', '--out', d)
            self.assertEqual(code, 2)
            self.assertIn('--all', err)

    def test_live_needs_all(self):
        with self.assertRaises(SystemExit):
            self.run_cli('case-001', '--live')


if __name__ == '__main__':
    unittest.main()
