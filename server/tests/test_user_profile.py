import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient

from server.app.execution_store import ExecutionStore, ConflictError
from server.app.execution_profile import UNKNOWN_FOCUS_START, generate_profile
from server.app.main import create_app
from server.app.planning_context import get_planning_context
from server.app.project_profile import effective_preferences
from server.app.user_profile import apply_profile_proposal, confirm_profile_draft, save_profile_draft
from server.tests.test_execution import ANSWERS, FakeLLM


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.temp.name) / 'db.sqlite3')
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=FakeLLM()))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self, path, **body):
        return self.client.post('/api/execution' + path, json={'revision': self.store.read()['revision'], **body})

    def profile(self, style='time_blocks'):
        r = self.post('/profile', answers={**ANSWERS, 'scheduleStyle': style})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.post('/profile/confirm')
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['profile']

    def test_explicit_style_overrides_regularity_and_is_confirmed(self):
        for style in ('time_blocks', 'flexible_queue'):
            p = self.profile(style)
            self.assertEqual(p['planningPreferences']['scheduleStyle'], style)
            self.assertEqual(p['planningPreferences']['scheduleStyleSource'], 'user')
            self.assertEqual(p['planningPreferences']['status'], 'confirmed')
            self.assertEqual(p['declaredFacts'], p['facts'])
        self.assertEqual(p['version'], 2)
        self.assertEqual(len(self.store.read()['profileRevisions']), 2)

    def test_survey_roundtrip_and_draft_does_not_change_context(self):
        old = self.profile()
        self.post('/profile', answers={**ANSWERS, 'scheduleStyle': 'flexible_queue'})
        context = get_planning_context('local', state=self.store.read())
        self.assertEqual(context['profileId'], old['id'])
        self.assertEqual(context['userProfile']['planningPreferences']['scheduleStyle'], 'time_blocks')
        r = self.client.get('/api/execution/survey-responses')
        self.assertEqual(r.json()['items'][-1]['answers']['scheduleStyle'], 'flexible_queue')
        self.assertEqual(len(ExecutionStore(self.store.path).read()['surveyResponses']), 2)

    def test_invalid_style_is_rejected_without_mutation(self):
        self.profile()
        before = self.store.read()
        r = self.post('/profile', answers={**ANSWERS, 'scheduleStyle': 'invented'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.store.read(), before)

    def test_users_are_isolated_in_same_database(self):
        self.profile()
        other = ExecutionStore(self.store.path, user_id='other')
        self.assertIsNone(other.read()['profile'])
        def seed(state):
            p = generate_profile({**ANSWERS, 'scheduleStyle': 'flexible_queue'})
            p['id'] = 'other-profile'
            save_profile_draft(state, p, ANSWERS, 'other')
            confirm_profile_draft(state)
        other.change(0, seed)
        a = get_planning_context('local', state=self.store.read())
        b = get_planning_context('other', state=other.read())
        self.assertNotEqual(a['userProfile']['planningPreferences']['scheduleStyle'], b['userProfile']['planningPreferences']['scheduleStyle'])
        with self.assertRaises(ValueError):
            get_planning_context('local', state=other.read())

    def test_legacy_migration_preserves_id_and_draft_status(self):
        p = generate_profile(ANSWERS)
        p.update(id='legacy', status='confirmed')
        old = {'revision': 4, 'profile': p, 'profileDraft': {**deepcopy(p), 'id': 'draft', 'status': 'draft'},
               'settings': {'slots': [], 'view': 'timeline'}, 'plan': None, 'planDraft': None}
        with self.store.connect() as db:
            db.execute('INSERT INTO execution_state VALUES (1, ?)', (json.dumps(old),))
        state = self.store.read()
        self.assertEqual(state['profile']['id'], 'legacy')
        self.assertEqual(state['profileDraft']['status'], 'draft')
        self.assertEqual(state['profile']['version'], 1)
        self.assertEqual(state['profile']['planningPreferences']['status'], 'confirmed')
        self.assertEqual(state['surveyResponses'], [])
        self.store.change(4, lambda s: None)
        self.assertEqual(len(self.store.read()['profileRevisions']), 1)

    def test_a_held_back_share_saved_by_older_versions_is_dropped(self):
        # Older profiles held back 25~40% of the chosen time; now all of it is planned.
        p = generate_profile(ANSWERS)
        p.update(id='old', status='confirmed')
        p['planningPreferences']['bufferPercent'] = 40
        project = {'id': 'v1', 'projectId': 'essay', 'userId': 'local', 'version': 1, 'learnedPatterns': [],
                   'createdAt': '2030-01-01T00:00:00+00:00', 'updatedAt': '2030-01-01T00:00:00+00:00',
                   'overrides': {'bufferPercent': {'value': 10, 'source': 'declared', 'proposalId': None},
                                 'blockMinutes': {'value': 20, 'source': 'declared', 'proposalId': None}}}
        old = {'revision': 4, 'profile': p, 'profileDraft': None, 'settings': {'slots': [], 'view': 'timeline'},
               'plan': None, 'planDraft': None, 'projectProfiles': {'essay': project}}
        with self.store.connect() as db:
            db.execute('INSERT INTO execution_state VALUES (1, ?)', (json.dumps(old),))
        state = self.store.read()
        self.assertNotIn('bufferPercent', state['profile']['planningPreferences'])
        self.assertEqual(list(state['projectProfiles']['essay']['overrides']), ['blockMinutes'])
        prefs, _ = effective_preferences(state['profile'], state['projectProfiles']['essay'])
        self.assertEqual(prefs['blockMinutes'], 20)

    def test_context_filters_memory_and_does_not_mutate_state(self):
        self.profile()
        state = self.store.read()
        now = datetime.now(timezone.utc)
        base = {'id': 'ok', 'content': '저녁 공부 선호', 'category': 'preference', 'source': 'user', 'createdAt': now.isoformat()}
        memories = [base, {**base, 'id': 'sensitive', 'sensitive': True}, {**base, 'id': 'old', 'createdAt': (now-timedelta(days=181)).isoformat()},
                    {**base, 'id': 'pending', 'source': 'ai_pending'}, {**base, 'id': 'other', 'userId': 'other'},
                    {**base, 'id': 'expired', 'expiresAt': (now-timedelta(seconds=1)).isoformat()}]
        before = deepcopy(state)
        context = get_planning_context('local', state=state, memories=memories, now=now)
        self.assertEqual([m['id'] for m in context['memories']], ['ok'])
        self.assertNotIn('constraints', context['userProfile']['declaredFacts'])
        context['userProfile']['planningPreferences']['blockMinutes'] = 99
        self.assertEqual(state, before)

    def proposal(self):
        p = self.profile()
        def seed(state):
            state['executionRecords'] = [{'id': f'r{i}', 'profileId': p['id']} for i in range(3)]
            state['profileUpdateProposals'] = [{'id': 'b-proposal', 'profileId': p['id'],
                'proposedChanges': {'blockMinutes': {'from': p['planningPreferences']['blockMinutes'], 'to': 20}},
                'reason': '긴 작업 반복 미완료', 'evidenceRecordIds': ['r0', 'r1', 'r2'], 'ruleVersion': 'long-task-v1',
                'status': 'pending', 'createdAt': datetime.now(timezone.utc).isoformat(), 'decidedAt': None}]
        self.store.change(self.store.read()['revision'], seed)
        return p

    def test_pr8_proposal_approval_advances_profile_version_and_evidence(self):
        old = self.proposal()
        state = self.store.read()
        self.assertEqual(get_planning_context('local', state=state)['userProfile']['learnedPatterns'], [])
        saved = self.store.change(state['revision'], lambda s: apply_profile_proposal(s, 'b-proposal', expected_version=old['version']))
        self.assertNotEqual(saved['profile']['id'], old['id'])
        self.assertEqual(saved['profile']['version'], 2)
        self.assertEqual(saved['profile']['planningPreferences']['blockMinutes'], 20)
        context = get_planning_context('local', state=saved)
        self.assertEqual(context['userProfile']['learnedPatterns'][0]['evidenceRecordIds'], ['r0', 'r1', 'r2'])
        with self.assertRaises(ConflictError):
            self.store.change(saved['revision'], lambda s: apply_profile_proposal(s, 'b-proposal', expected_version=2))
        self.assertEqual(self.store.read(), saved)

    def test_stale_approval_rolls_back(self):
        self.proposal()
        old = self.store.read()
        with self.assertRaises(ConflictError):
            self.store.change(old['revision'], lambda s: apply_profile_proposal(s, 'b-proposal', expected_version=99))
        self.assertEqual(self.store.read(), old)

    def test_profile_reset_preserves_schedule_plan_and_execution_history(self):
        self.profile()
        def seed(state):
            state['settings']['slots'] = [{'day':0, 'hour':18}]
            state['plan'] = {'id':'keep-plan'}
            state['executionRecords'] = [{'id':'keep-record'}]
            state['planDraft'] = {'id':'drop-draft'}
        self.store.change(self.store.read()['revision'], seed)
        old = self.store.read()
        r = self.post('/profile/reset')
        self.assertEqual(r.status_code,200,r.text)
        saved = r.json()
        for key in ('profile','profileDraft','planDraft'):
            self.assertIsNone(saved[key])
        for key in ('surveyResponses','profileRevisions','profileUpdateProposals'):
            self.assertEqual(saved[key], [])
        for key in ('settings','plan','executionRecords'):
            self.assertEqual(saved[key],old[key])
        self.assertEqual(self.client.post('/api/execution/profile/reset',json={'revision':old['revision']}).status_code,409)


class SurveyFocusTests(unittest.TestCase):
    """The onboarding answer becomes the user's focus block as given."""

    def prefs(self, **answers):
        return generate_profile({**ANSWERS, "barriers": ["none"], "dailyMinutes": None, **answers})["planningPreferences"]

    def test_the_answer_is_used_as_is_without_a_fixed_cap(self):
        for minutes in (15, 25, 45, 60, 90):
            self.assertEqual(self.prefs(focusMinutes=minutes)["blockMinutes"], minutes)

    def test_a_distraction_answer_does_not_override_the_stated_focus(self):
        self.assertEqual(self.prefs(focusMinutes=60, barriers=["distraction"])["blockMinutes"], 60)

    def test_only_an_unknown_answer_uses_the_start_value(self):
        self.assertEqual(self.prefs(focusMinutes=None)["blockMinutes"], UNKNOWN_FOCUS_START)

    def test_a_daily_amount_still_bounds_the_block(self):
        prefs = self.prefs(focusMinutes=90, dailyMinutes=60)
        self.assertEqual(prefs["blockMinutes"], prefs["dailyPlannedMinutes"])
