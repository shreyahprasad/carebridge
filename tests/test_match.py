"""Offline tests for the provider-match workflow: real rules, real runtime, scripted agent.
No network, no paid calls."""
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError
from shreyah_harness.runtime import Budget

from match import agent, rules
from match.models import EnglishLevel, Fact, MatchResult, Mode, Provider, Question, load_match_result
from match.scripted import scripted_model
from match.workflow import run_match

PROVIDERS, DATA_VERSION = rules.load_providers()
CASES = rules.load_cases()
AMINA, LUCIA = CASES['case-001'], CASES['case-002']
GIO = 'Gio Health Services Inc'
QUIET = dict(log=lambda m: None)


def match(case, tamper=None, **kw):
    calls = []
    report = run_match(case, scripted_model(tamper, calls), model='scripted-demo', **QUIET, **kw)
    return report, calls


class Rules(unittest.TestCase):
    def test_amina_tiers_match_approved_prototype(self):
        _, cands, counts = rules.candidates(AMINA, PROVIDERS, DATA_VERSION)
        self.assertEqual((counts['A'], counts['B'], counts['C']), (1, 3, 13))
        self.assertEqual(cands[0]['provider']['name'], GIO)
        self.assertEqual(cands[0]['tier'], 'A')

    def test_lucia_needs_spanish_low_cost_in_person_for_a_minor(self):
        _, cands, counts = rules.candidates(LUCIA, PROVIDERS, DATA_VERSION)
        self.assertEqual((counts['A'], counts['B'], counts['C']), (5, 11, 0))  # no interpreter wanted -> no C
        for c in cands:
            p = c['provider']
            self.assertIn('Spanish', p['languages'])
            self.assertTrue(p['ages']['children_adolescents'] and p['in_person_outpatient'] and p['programs']['trauma'])
            self.assertIn('minor_consent', c['required_questions'])
            self.assertIn('confirm_cost', c['required_questions'])

    def test_every_candidate_passes_hard_filters_and_has_evidence(self):
        for case in (AMINA, LUCIA):
            _, cands, _ = rules.candidates(case, PROVIDERS, DATA_VERSION)
            for c in cands:
                d = c['decision']
                self.assertTrue(d['eligible'])
                self.assertTrue(all(p['passed'] is True and p['evidence_ids'] for p in d['predicates']))
                self.assertFalse(c['provider']['out_of_area'] or c['provider']['location_unknown'])

    def test_unknowns_are_questions_never_facts(self):
        _, cands, _ = rules.candidates(AMINA, PROVIDERS, DATA_VERSION)
        for c in cands:
            self.assertIn('woman_clinician', c['required_questions'])
            self.assertIn('waitlist', c['required_questions'])
            self.assertEqual('interpreter' in c['required_questions'], c['tier'] == 'C')
            self.assertEqual('confirm_dc_medicaid' in c['required_questions'], c['provider']['state'] != 'DC')
        gio = cands[0]
        self.assertIn('dari_speaker', gio['required_questions'])
        self.assertEqual(rules.fact_text('speaks_client_language', gio['required_questions']),
                         'Lists Farsi (closest listed language to Dari)')


class Workflow(unittest.TestCase):
    def test_scripted_run_produces_validated_match_result(self):
        out = Path(tempfile.mkdtemp())
        report, _ = match(AMINA, out_dir=out)
        self.assertEqual(report['mode'], 'scripted')
        self.assertEqual(report['stages'][0]['status'], 'complete')
        self.assertTrue(3 <= len(report['picks']) <= 5)
        self.assertEqual(report['picks'][0]['name'], GIO)
        self.assertEqual(json.loads(Path(report['path']).read_text())['correlation_id'], report['correlation_id'])

    def test_handoff_fields_come_from_the_provider_record(self):
        report, _ = match(LUCIA)
        records = {p['id']: p for p in PROVIDERS}
        for pick in report['picks']:
            rec = records[pick['provider_id']]
            for field in ('name', 'address', 'phone', 'lat', 'lng', 'state', 'website'):
                self.assertEqual(pick[field], rec[field])
            self.assertIsInstance(pick['lat'], float)

    def test_agent_never_sees_client_identity(self):
        _, calls = match(AMINA)
        sent = json.dumps(calls[0])
        for value in ('Amina', 'Rahimi', '202-555-0141', 'Kennedy', 'refugee', 'caseworker@example.org',
                      str(AMINA.lat), 'AmeriHealth'):
            self.assertNotIn(value, sent)
        self.assertEqual(len(calls[0]['candidates']), 17)

    def test_shared_budget_and_correlation_id(self):
        budget = Budget(max_requests=10, max_tools=0, max_retries=1, seconds=60)
        r1, _ = match(AMINA, budget=budget, correlation_id='wf-1')
        r2, _ = match(LUCIA, budget=budget, correlation_id='wf-1')
        self.assertEqual(budget.requests, 2)
        self.assertEqual({r1['correlation_id'], r2['correlation_id']}, {'wf-1'})

    def test_rules_only_mode(self):
        report = run_match(AMINA, None, model=None, **QUIET)
        self.assertEqual(report['mode'], 'rules_only')
        self.assertEqual(report['picks'][0]['name'], GIO)
        self.assertIsNone(report['picks'][0]['why'])
        self.assertEqual(report['stages'][0]['status'], 'skipped')


class InvalidHandoff(unittest.TestCase):
    """A rejected agent output never reaches the MatchResult or the next stage."""

    def check_rejected(self, tamper, case=AMINA):
        out = Path(tempfile.mkdtemp())
        self.assertIsNone(run_match(case, scripted_model(tamper), model='scripted-demo', fallback=False,
                                    out_dir=out, **QUIET))
        self.assertEqual(list(out.iterdir()), [], 'nothing written for transportation to consume')
        report, _ = match(case, tamper)
        self.assertEqual(report['mode'], 'rules_only')
        self.assertEqual(report['fallback_reason'], 'invalid_output')
        self.assertEqual(report['stages'][0]['requests'], 2, 'one repair attempt, then stop')
        expected = [c['provider']['id'] for c in rules.candidates(case, PROVIDERS, DATA_VERSION)[1][:agent.MAX_PICKS]]
        self.assertEqual([p['provider_id'] for p in report['picks']], expected)
        return report

    def test_invented_provider_id(self):
        report = self.check_rejected('invent_id')
        self.assertNotIn('samhsa-invented-clinic-dc-20001', json.dumps(report))

    def test_raised_tier(self):
        self.check_rejected('raise_tier')

    def test_fact_not_in_record(self):
        self.check_rejected('false_fact')

    def test_missing_woman_clinician_question(self):
        self.check_rejected('drop_question')

    def test_question_that_does_not_apply(self):
        self.check_rejected('extra_question')

    def test_tier_a_left_out(self):
        self.check_rejected('drop_tier_a')

    def test_non_json(self):
        self.check_rejected('not_json')

    def test_budget_exhausted_falls_back(self):
        budget = Budget(max_requests=1, max_tools=0, max_retries=0, seconds=60)
        budget.requests = 1
        report, calls = match(AMINA, budget=budget)
        self.assertEqual(calls, [])
        self.assertEqual((report['mode'], report['fallback_reason']), ('rules_only', 'request_limit'))



class Contracts(unittest.TestCase):
    """Typed edges: bad cases, providers and handoffs fail loudly before or instead of matching."""

    def bad_case(self, **change):
        data = AMINA.model_dump(mode='json')
        for k, v in change.items():
            if v is DROP:
                data.pop(k)
            else:
                data[k] = v
        return data

    def test_case_typo_in_enum_is_rejected_before_any_model_call(self):
        calls = []
        with self.assertRaises(ValidationError):
            run_match(self.bad_case(care_mode_needed='in-person'), scripted_model(None, calls),
                      model='scripted-demo', **QUIET)
        self.assertEqual(calls, [])

    def test_case_unknown_or_missing_field_is_rejected(self):
        for change in ({'langauges': ['Dari']}, {'urgency': DROP}, {'insurance': {'type': 'Medicaid'}},
                       {'preferences': {'provider_gender': 'female'}}, {'pregnant': False}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                rules.as_case(self.bad_case(**change))

    def test_lucia_speaks_spanish_only(self):
        self.assertEqual((LUCIA.languages, LUCIA.english_level), (['Spanish'], EnglishLevel.none))

    def test_provider_contract(self):
        bad = dict(PROVIDERS[0], woman_clinician_available=True)
        with self.assertRaises(ValidationError):
            Provider.model_validate(bad)
        with self.assertRaises(ValidationError):
            Provider.model_validate(dict(PROVIDERS[0], location_unknown=False, lat=None))

    def test_agent_schema_lists_come_from_enums(self):
        item = agent.SCHEMA['properties']['shortlist']['items']['properties']
        self.assertEqual(item['facts']['items']['enum'], [f.value for f in Fact])
        self.assertEqual(item['questions']['items']['enum'], [q.value for q in Question])
        self.assertEqual(set(rules.FACTS), set(Fact))
        self.assertEqual(set(rules.QUESTIONS), set(Question))

    def test_transportation_loads_the_handoff(self):
        out = Path(tempfile.mkdtemp())
        report, _ = match(AMINA, out_dir=out)
        loaded = load_match_result(report['path'])
        self.assertEqual(loaded.mode, Mode.scripted)
        self.assertEqual([(p.provider_id, p.lat, p.lng) for p in loaded.picks],
                         [(p['provider_id'], p['lat'], p['lng']) for p in report['picks']])

    def test_broken_handoff_is_rejected(self):
        report, _ = match(AMINA)
        report.pop('path', None)
        picks = report['picks']
        breaks = {
            'duplicate pick': {'picks': picks + [dict(picks[0], rank=len(picks) + 1)]},
            'rank gap': {'picks': [dict(picks[0], rank=2)] + picks[1:]},
            'rules_only with model text': {'mode': 'rules_only'},
            'unknown mode': {'mode': 'cached'},
            'unknown fact code': {'picks': [dict(picks[0], facts=[{'code': 'woman_clinician', 'text': 'x'}])] + picks[1:]},
            'in-person pick without coordinates': {'picks': [dict(picks[0], lat=None)] + picks[1:]},
            'tier differs from decision': {'picks': [dict(picks[0], tier='B')] + picks[1:]},
        }
        for name, change in breaks.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                MatchResult.model_validate({**report, **change})


DROP = object()


class InPersonOnly(unittest.TestCase):
    def test_telehealth_never_offered_to_in_person_only_client(self):
        report, calls = match(AMINA)
        for card in calls[0]['candidates']:
            self.assertNotIn('telehealth', card)
            self.assertNotIn('telehealth', card['facts'])
        self.assertFalse(any(f['code'] == 'telehealth' for p in report['picks'] for f in p['facts']))

    def test_telehealth_stays_for_in_person_preferred(self):
        _, calls = match(LUCIA)
        self.assertTrue(all('telehealth' in card for card in calls[0]['candidates']))


class ReviewFixes(unittest.TestCase):
    """Edge cases from the code review."""

    def variant(self, **change):
        return rules.as_case({**AMINA.model_dump(mode='json'), **change})

    def test_question_text_never_states_untrue_case_facts(self):
        for case in (AMINA, LUCIA):
            report, _ = match(case)
            text = json.dumps([q for p in report['picks'] for q in p['questions']])
            self.assertEqual('She is 17' in text, case is LUCIA)
            self.assertEqual('uninsured' in text, case is LUCIA)
            self.assertNotIn('aunt', text)

    def test_dari_plus_english_does_not_claim_farsi(self):
        n, cands, _ = rules.candidates(self.variant(languages=['Dari', 'English']), PROVIDERS, DATA_VERSION)
        for c in cands:
            farsi_only = 'Farsi' in c['provider']['languages'] and 'English' not in c['provider']['languages']
            self.assertEqual('dari_speaker' in c['required_questions'], farsi_only)

    def test_medicaid_client_gets_coverage_question_when_listing_lacks_medicaid(self):
        n = rules.needs(AMINA)
        for p in PROVIDERS:
            ev = rules.evaluate(n, p, DATA_VERSION)
            q = ev['required_questions']
            if not p['payment']['medicaid']:
                self.assertIn('confirm_cost', q)
                self.assertNotIn('confirm_dc_medicaid', q)
            elif p['state'] != 'DC':
                self.assertIn('confirm_dc_medicaid', q)

    def test_telehealth_case_only_gets_telehealth_providers(self):
        case = self.variant(care_mode_needed='telehealth', phone_type='smartphone')
        _, cands, _ = rules.candidates(case, PROVIDERS, DATA_VERSION)
        self.assertTrue(cands)
        self.assertTrue(all(c['provider']['telehealth'] for c in cands))

    def test_trauma_inference_ignores_case(self):
        self.assertTrue(rules.needs(self.variant(immigration_status='Refugee'))['trauma_informed'])

    def test_identifiers_typed_into_concerns_are_scrubbed(self):
        case = self.variant(mental_health_concerns='Amina Rahimi (202-555-0141) has nightmares; Jordan Lee referred.')
        sent = json.dumps(rules.agent_view(rules.needs(case)))
        for value in ('Amina', 'Rahimi', '202-555-0141', 'Jordan Lee'):
            self.assertNotIn(value, sent)

    def test_lucia_task_privacy(self):
        _, calls = match(LUCIA)
        sent = json.dumps(calls[0])
        for value in ('Lucía', 'Morales', '202-555-0172', '14th St', 'asylum', 'aunt', 'Jordan Lee', 'example.org'):
            self.assertNotIn(value, sent)

    def test_api_failure_falls_back_and_is_marked_in_file_name(self):
        out = Path(tempfile.mkdtemp())
        report, _ = match(AMINA, 'raise', out_dir=out)
        self.assertEqual((report['mode'], report['fallback_reason']), ('rules_only', 'execution_error'))
        self.assertIn('-rules_only-', Path(report['path']).name)
        self.assertEqual(load_match_result(report['path']).mode, Mode.rules_only)

    def test_zero_candidates(self):
        case = self.variant(languages=['Tigrinya'], preferences={'provider_gender': 'woman', 'interpreter_ok': False})
        report, calls = match(case)
        self.assertEqual((report['picks'], calls, report['fallback_reason']), ([], [], 'no_candidates'))
        MatchResult.model_validate(report)

    def test_fewer_than_three_candidates(self):
        _, cands, _ = rules.candidates(AMINA, PROVIDERS, DATA_VERSION)
        two = [c['provider'] for c in cands[:2]]
        report = run_match(AMINA, scripted_model(), model='scripted-demo', providers=two,
                           data_version=DATA_VERSION, **QUIET)
        self.assertEqual((report['mode'], len(report['picks'])), ('scripted', 2))

    def test_more_than_five_tier_a(self):
        _, cands, _ = rules.candidates(AMINA, PROVIDERS, DATA_VERSION)
        gio = cands[0]['provider']
        clones = [dict(gio, id=f'{gio["id"]}-{i}', name=f'Gio clone {i}') for i in range(7)]
        report = run_match(AMINA, scripted_model(), model='scripted-demo', providers=clones,
                           data_version=DATA_VERSION, **QUIET)
        self.assertEqual(report['mode'], 'scripted')
        self.assertEqual({p['tier'] for p in report['picks']}, {'A'})


if __name__ == '__main__':
    unittest.main()
