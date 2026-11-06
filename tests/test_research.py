"""Offline tests for the research workflow: scripted agents, real runtime,
real evidence store, fixture pages. No network, no paid calls."""
import json
import tempfile
import unittest
from pathlib import Path

from research import pipeline
from research.scripted import fixture_fetch, scripted_model

TOPIC = 'pro bono and low-cost mental health for immigrant women in DC'


class ResearchWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        cls.report = pipeline.run(TOPIC, scripted_model(), fixture_fetch, model='scripted-demo',
                                  out_dir=cls.out, log=lambda m: None)
        cls.by_field = {}
        for r in cls.report['resources']:
            for f, vals in r['fields'].items():
                cls.by_field[(r['organization'], f)] = vals
            for item in r['review']:
                cls.by_field[(r['organization'], 'review:' + item['field'])] = item

    def test_all_stages_complete_on_one_budget(self):
        self.assertEqual([s['status'] for s in self.report['stages']], ['complete'] * 4)
        self.assertEqual(self.report['budget_used']['requests'], sum(s['requests'] for s in self.report['stages']))

    def test_supported_quote_found_claims_are_accepted_with_source(self):
        # cost + languages; the asylum 'services' claim is supported but its page is injection-flagged.
        self.assertEqual(self.report['counts']['accepted'], 3)
        cost = self.by_field[('Example University', 'cost')][0]
        self.assertEqual(cost['source_url'], 'https://clinic.example.edu/community-clinic')
        self.assertIn('sliding fee scale', cost['excerpt'])
        self.assertEqual(cost['trust'], 'institutional')
        self.assertTrue(cost['acceptance_id'])

    def test_server_fetched_copy_used_when_host_fetch_blocked(self):
        item = self.by_field[('Example University', 'serves_immigrants')][0]
        self.assertEqual(item['fetched_via'], 'server_fetch')
        self.assertIn('Farsi and Dari', item['excerpt'])

    def test_fabricated_excerpt_is_rejected_by_host_quote_check(self):
        item = self.by_field[('Example University', 'review:women_focus')]
        self.assertEqual(item['reason'], 'quote_not_found')
        self.assertNotIn(('Example University', 'women_focus'), self.by_field)

    def test_verifier_rejects_value_the_page_contradicts(self):
        item = self.by_field[('Example Asylum Network', 'review:how_to_access')]
        self.assertEqual(item['reason'], 'verifier: unsupported')

    def test_unreachable_source_is_never_accepted(self):
        item = self.by_field[('Example Asylum Network', 'review:phone')]
        self.assertEqual(item['reason'], 'source_unreachable')
        self.assertNotIn(('Example Asylum Network', 'phone'), self.by_field)

    def test_injection_flagged_page_is_never_auto_accepted(self):
        item = self.by_field[('Example Asylum Network', 'review:services')]
        self.assertTrue(item['reason'].startswith('injection_suspected'))
        self.assertIn('override_instructions', item['reason'])
        self.assertIn('verdict_manipulation', item['reason'])
        self.assertEqual(self.report['counts']['injection_flagged'], 2)

    def test_link_policy_blocks_http_and_shorteners_before_fetch(self):
        self.assertEqual(self.by_field[('Example Asylum Network', 'review:website')]['reason'], 'link_not_https')
        self.assertEqual(self.by_field[('Example Asylum Network', 'review:cost')]['reason'], 'link_blocked_host')

    def test_url_the_specialist_never_saw_is_rejected(self):
        self.assertEqual(self.by_field[('Example Asylum Network', 'review:eligibility')]['reason'],
                         'url_not_seen_by_specialist')

    def test_audit_log_written_without_page_content(self):
        lines = (self.out / 'audit.jsonl').read_text().splitlines()
        self.assertTrue(lines)
        self.assertTrue(all(json.loads(l)['correlation_id'] == self.report['correlation_id'] for l in lines))
        self.assertNotIn('IGNORE ALL PREVIOUS', '\n'.join(lines))
        self.assertNotIn('sliding fee scale', '\n'.join(lines))

    def test_injected_page_text_does_not_enter_dataset(self):
        text = json.dumps(self.report['resources'])
        self.assertNotIn('555-0100', text)
        self.assertNotIn('IGNORE ALL PREVIOUS', json.dumps([r['fields'] for r in self.report['resources']]))

    def test_dataset_and_run_files_written(self):
        data = json.loads((self.out / 'supplemental_resources.json').read_text())
        self.assertEqual({r['resource_type'] for r in data}, {'training_clinic', 'pro_bono_network'})
        self.assertTrue(list((self.out / 'runs').glob('*.json')))

    def test_topic_with_client_data_is_refused_before_any_model_call(self):
        def never(**_):
            raise AssertionError('model must not be called')
        for topic in ['therapist for Amina, call 202-555-0123', 'clinic near 1660 L Street NW for client',
                      'help amina@example.com find care', 'case A123456789 needs Dari therapist']:
            with self.assertRaises(ValueError):
                pipeline.run(topic, never, fixture_fetch, model='x', out_dir=self.out, log=lambda m: None)


class Guardrails(unittest.TestCase):
    def test_raw_ip_hosts_blocked_including_ipv6_and_hex(self):
        from research.sources import link_policy
        for url in ['https://[::1]/x', 'https://[2001:db8::1]/p', 'https://0x7f000001/', 'https://127.0.0.1/', 'https://2130706433/']:
            self.assertEqual(link_policy(url), 'link_raw_ip', url)
        self.assertIsNone(link_policy('https://dhcf.dc.gov/service/medicaid'))

    def test_org_domains_are_not_institutional(self):
        from research.sources import trust_tier
        self.assertEqual(trust_tier('https://scam-clinic.org/a'), 'needs_review')
        self.assertEqual(trust_tier('https://dbh.dc.gov/a'), 'institutional')

    def test_excerpt_span_correct_after_case_changing_characters(self):
        from research.sources import find_excerpt
        text = 'Straße Klinik. Sessions are available in English and Spanish.'
        self.assertEqual(find_excerpt(text, 'sessions are available in english'), 'Sessions are available in English')

    def test_generic_street_names_allowed_but_addresses_refused(self):
        pipeline.check_topic('top 5 clinics near Georgia Avenue for Dari speakers')
        pipeline.check_topic('mental health programs at St Elizabeths campus')
        for t in ['client lives at 1660 L Street, needs therapist', 'near 12 Main St NW for a client']:
            with self.assertRaises(ValueError):
                pipeline.check_topic(t)

    def test_later_run_does_not_erase_verified_facts(self):
        out = Path(tempfile.mkdtemp())
        pipeline.run(TOPIC, scripted_model(), fixture_fetch, model='scripted-demo', out_dir=out, log=lambda m: None)
        def down(url):
            raise ValueError('source unavailable')
        pipeline.run(TOPIC, scripted_model(), down, model='scripted-demo', out_dir=out, log=lambda m: None)
        data = {r['organization']: r for r in json.loads((out / 'supplemental_resources.json').read_text())}
        self.assertIn('cost', data['Example University']['fields'])

    def test_resource_with_contradicted_claim_is_not_verified(self):
        out = Path(tempfile.mkdtemp())
        report = pipeline.run(TOPIC, scripted_model(), fixture_fetch, model='scripted-demo', out_dir=out, log=lambda m: None)
        asylum = next(r for r in report['resources'] if r['organization'] == 'Example Asylum Network')
        self.assertEqual(asylum['status'], 'needs_review')

    def test_search_only_fallback_when_fetch_tool_fails(self):
        inner = scripted_model()
        def create(**kw):
            if kw['system'].startswith('You are a CareBridge research specialist') and any(
                    t.get('name') == 'web_fetch' for t in kw.get('tools', [])):
                return {'id': 'x', 'stop_reason': 'end_turn', 'usage': {'input_tokens': 0, 'output_tokens': 0},
                        'content': [{'type': 'mystery_block'}]}
            return inner(**kw)
        report = pipeline.run(TOPIC, create, fixture_fetch, model='scripted-demo', out_dir=Path(tempfile.mkdtemp()),
                              log=lambda m: None)
        stages = [s['stage'] for s in report['stages'] if s['status'] == 'complete']
        self.assertIn('specialist:training_clinic:search-only', stages)
        self.assertGreater(report['counts']['accepted'], 0)


if __name__ == '__main__':
    unittest.main()
