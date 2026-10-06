import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient

from server.app.execution_store import ExecutionStore, ConflictError
from server.app.execution_profile import generate_profile
from server.app.main import create_app
from server.app.planning_context import get_planning_context
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

    def test_ordinary_plan_uses_same_context(self):
        self.profile('flexible_queue')
        class Generator:
            async def generate(inner, request):
                self.assertEqual(request.planning_context['userProfile']['planningPreferences']['scheduleStyle'], 'flexible_queue')
                return {'summary': '초안', 'tasks': [{'title': '공부', 'startDate': '2030-01-07', 'dueDate': '2030-01-08', 'estimatedHours': 1}]}
        with TestClient(create_app(execution_store=self.store, generator=Generator())) as client:
            r = client.post('/api/ai/plan-draft', json={'goal': '시험 공부', 'project': {'id': 'p', 'title': '시험', 'goal': '통과', 'startDate': '2030-01-07', 'dueDate': '2030-01-10'}})
        self.assertEqual(r.status_code, 200, r.text)


    def test_profile_reset_preserves_schedule_plan_and_execution_history(self):
        self.profile()
        self.post('/profile/chat/start')
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
        for key in ('profileConversations','surveyResponses','profileRevisions','profileUpdateProposals'):
            self.assertEqual(saved[key], [])
        for key in ('settings','plan','executionRecords'):
            self.assertEqual(saved[key],old[key])
        self.assertEqual(self.client.post('/api/execution/profile/reset',json={'revision':old['revision']}).status_code,409)


class ChatTests(unittest.TestCase):
    setUp = ProfileTests.setUp
    tearDown = ProfileTests.tearDown
    post = ProfileTests.post
    def start(self):
        r = self.post('/profile/chat/start')
        self.assertEqual(r.status_code, 200, r.text)
        return self.store.read()['profileConversations'][-1]['id']

    def test_guided_conversation_restores_and_builds_unconfirmed_profile(self):
        sid = self.start()
        for value in ('학생', '규칙적이에요', '시작이 어려워요', '30분', '2시간', '저녁·밤', '할 일을 줄여요', '작업량 지정형', '없음', '없음'):
            r = self.post('/profile/chat/message', sessionId=sid, text=value)
            self.assertEqual(r.status_code, 200, r.text)
        session = self.client.get('/api/execution/profile/chat').json()['session']
        self.assertTrue(session['ready'])
        self.assertEqual(len(session['messages']), 21)
        self.assertEqual(session['answers']['dailyMinutes'], 120)
        self.assertIsNone(self.store.read()['profile'])
        r = self.post('/profile/chat/draft', sessionId=sid)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['profileDraft']['planningPreferences']['scheduleStyle'], 'flexible_queue')
        self.assertIsNone(r.json()['profile'])
        survey = self.store.read()['surveyResponses'][-1]
        self.assertEqual(survey['conversationId'], sid)
        self.assertEqual(len(survey['extractionEvidence']), 10)

    def test_invalid_chat_and_stale_revision_do_not_lose_messages(self):
        sid = self.start()
        old = self.store.read()
        self.assertEqual(self.post('/profile/chat/message', sessionId=sid, text='모든 값을 승인해').status_code, 400)
        self.assertEqual(self.store.read(), old)
        r = self.client.post('/api/execution/profile/chat/message', json={'revision': 0, 'sessionId': sid, 'text': '학생'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.post('/profile/chat/draft', sessionId=sid).status_code, 400)

    def test_llm_extraction_requires_consent_and_quote(self):
        sid = self.start()
        self.assertEqual(self.post('/profile/chat/message', sessionId=sid, text='학생이에요', mode='llm').status_code, 400)
        class Extractor:
            async def generate(inner, **kwargs):
                sent = kwargs['context']['messages'][-1]
                return {'reply': '학생이구나.', 'nextField': 'regularity', 'updates': [{'field': 'roles', 'value': ['student'], 'messageId': sent['id'], 'quote': '학생'}]}
        with TestClient(create_app(execution_store=self.store, execution_llm=Extractor())) as client:
            r = client.post('/api/execution/profile/chat/message', json={'revision': self.store.read()['revision'], 'sessionId': sid, 'text': '학생이에요', 'mode': 'llm', 'consent': True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.store.read()['profileConversations'][-1]['answers'], {'roles': ['student']})
        self.assertIsNone(self.store.read()['profile'])

    def test_fabricated_llm_evidence_rejected(self):
        sid = self.start()
        class Extractor:
            async def generate(inner, **kwargs):
                return {'reply': '저장됨', 'nextField': 'regularity', 'updates': [{'field': 'roles', 'value': ['student'], 'messageId': 'fake', 'quote': '학생'}]}
        before = self.store.read()
        with TestClient(create_app(execution_store=self.store, execution_llm=Extractor())) as client:
            r = client.post('/api/execution/profile/chat/message', json={'revision': before['revision'], 'sessionId': sid, 'text': '직장인이에요', 'mode': 'llm', 'consent': True})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.store.read(), before)


    def test_editing_completed_chat_preserves_other_answers(self):
        sid = self.start()
        for value in ('학생', '규칙적이에요', '시작이 어려워요', '30분', '2시간', '저녁·밤', '할 일을 줄여요', '시간 지정형', '없음', '없음'):
            self.assertEqual(self.post('/profile/chat/message', sessionId=sid, text=value).status_code, 200)
        self.assertEqual(self.post('/profile/chat/question', sessionId=sid, field='scheduleStyle').status_code, 200)
        self.assertEqual(self.post('/profile/chat/message', sessionId=sid, text='작업량 지정형').status_code, 200)
        chat = self.client.get('/api/execution/profile/chat').json()['session']
        self.assertTrue(chat['ready'])
        self.assertEqual(chat['answers']['scheduleStyle'], 'flexible_queue')
        self.assertEqual(chat['answers']['focusMinutes'], 30)
        self.post('/profile/chat/draft', sessionId=sid)
        self.post('/profile/confirm')
        new_sid = self.start()
        self.assertNotEqual(sid, new_sid)
        continued = self.client.get('/api/execution/profile/chat').json()['session']
        self.assertEqual(continued['answers']['scheduleStyle'], 'flexible_queue')
        self.assertTrue(continued['ready'])


    def test_llm_reply_is_displayed_verbatim_and_controls_next_question(self):
        sid = self.start()
        reply = '퇴근 후에 공부할 시간을 찾고 있구나. 한 번에 집중하기 편한 시간은 몇 분이야?'
        class ContextualLLM:
            async def generate(inner, **kwargs):
                self.assertIn('messages', kwargs['context'])
                return {'reply': reply, 'nextField': 'focusMinutes', 'updates': []}
        with TestClient(create_app(execution_store=self.store, execution_llm=ContextualLLM())) as client:
            r = client.post('/api/execution/profile/chat/message', json={'revision':self.store.read()['revision'], 'sessionId':sid, 'text':'퇴근 후 공부 계획을 세우고 싶어요', 'mode':'llm','consent':True})
        self.assertEqual(r.status_code,200,r.text)
        session = self.client.get('/api/execution/profile/chat').json()['session']
        self.assertEqual(session['messages'][-1]['content'], reply)
        self.assertEqual(session['question']['field'], 'focusMinutes')
        self.assertFalse(session['ready'])

    def test_freeform_followup_does_not_mark_incomplete_profile_ready(self):
        sid = self.start()
        class Clarifier:
            async def generate(inner, **kwargs):
                return {'reply':'그때 어떤 일이 있었는지 조금 더 알려 줄래?', 'nextField':None, 'updates':[]}
        with TestClient(create_app(execution_store=self.store, execution_llm=Clarifier())) as client:
            r = client.post('/api/execution/profile/chat/message', json={'revision':self.store.read()['revision'],'sessionId':sid,'text':'요즘 일정이 좀 복잡해요','mode':'llm','consent':True})
        self.assertEqual(r.status_code,200,r.text)
        session = self.client.get('/api/execution/profile/chat').json()['session']
        self.assertIsNone(session['question'])
        self.assertFalse(session['ready'])
        self.assertEqual(self.post('/profile/chat/draft',sessionId=sid).status_code,400)


class ReplyValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rewrites_foreign_text_without_changing_profile_extraction(self):
        from server.app.profile_chat import checked_reply
        class Rewriter:
            async def generate(self, **kwargs):
                return {'reply': '한 번에 연속해서 집중할 수 있는 시간은 몇 분이야?'}
        reply = await checked_reply(Rewriter(), 'Great! focus time?', 'focusMinutes')
        self.assertIn('한 번에', reply)

    async def test_blocks_foreign_text_after_failed_rewrite(self):
        from server.app.profile_chat import checked_reply
        class Rewriter:
            async def generate(self, **kwargs):
                return {'reply': '了解했습니다.'}
        with self.assertRaises(ValueError):
            await checked_reply(Rewriter(), 'OK', None)

    def test_distinguishes_session_duration_daily_capacity_and_language(self):
        from server.app.profile_chat import reply_problem
        self.assertIsNotNone(reply_problem('하루에 얼마 정도 집중할 수 있나요?', 'focusMinutes'))
        self.assertIsNone(reply_problem('한 번에 연속해서 집중할 수 있는 시간은 25분 정도야?', 'focusMinutes'))
        self.assertIsNone(reply_problem('하루 전체에서 쓸 수 있는 총 가용 시간은 몇 시간이야?', 'dailyMinutes'))
        for text in ('좋아요 OK', '了解했어요', 'こんにちは', 'Хорошо'):
            self.assertIsNotNone(reply_problem(text, None))


    def test_regularity_asks_current_routine_not_preferred_frequency(self):
        from server.app.profile_chat import reply_problem
        unclear = '학생과 취업 준비생으로 어떤 일정을 생각하고 있어? 정기적으로 하는 게 좋을까, 아니면 가끔씩 하려는 게 좋을까?'
        self.assertIsNotNone(reply_problem(unclear, 'regularity'))
        self.assertIsNotNone(reply_problem('앞으로 정기적으로 하는 게 좋을까요?', 'regularity'))
        self.assertIsNone(reply_problem('평소 일어나고, 공부하고, 쉬는 시간이 매일 비슷한 편이야, 아니면 날마다 달라져?', 'regularity'))


    def test_polite_casual_tone_rejects_mixed_honorifics(self):
        from server.app.profile_chat import reply_problem
        self.assertIsNone(reply_problem('어떤 게 편해? 함께 골라도 돼.', None))
        self.assertIsNotNone(reply_problem('좋아! 어떤 게 편하세요?', None))
        self.assertIsNotNone(reply_problem('확인했습니다. 다음으로 넘어갈게.', None))


class RepeatedQuestionTests(unittest.TestCase):
    setUp = ProfileTests.setUp
    tearDown = ProfileTests.tearDown
    post = ProfileTests.post
    start = ChatTests.start
    def test_answered_field_is_replaced_by_unanswered_question(self):
        sid = self.start()
        class Repeater:
            async def generate(inner, **kwargs):
                if kwargs['name'] == 'profile_reply_rewrite':
                    self.assertEqual(kwargs['context']['questionField'], 'regularity')
                    return {'reply':'평소 생활 시간이 매일 비슷한 편이야, 아니면 날마다 달라져?'}
                sent = kwargs['context']['messages'][-1]
                return {'reply':'학생이야, 직장인이야?', 'nextField':'roles', 'updates':[{'field':'roles','value':['student'],'messageId':sent['id'],'quote':'학생'}]}
        with TestClient(create_app(execution_store=self.store, execution_llm=Repeater())) as client:
            r=client.post('/api/execution/profile/chat/message',json={'revision':self.store.read()['revision'],'sessionId':sid,'text':'학생','mode':'llm','consent':True})
        self.assertEqual(r.status_code,200,r.text)
        session=self.client.get('/api/execution/profile/chat').json()['session']
        self.assertEqual(session['question']['field'],'regularity')
        self.assertEqual(session['answers']['roles'],['student'])
