import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from fastapi.testclient import TestClient
from server.app.main import create_app
from server.app.execution_store import ExecutionStore
from server.app.execution_api import SCHEDULE_STYLE_INSTRUCTIONS, Slot, BusyEvent
from server.app.execution_scheduler import availability_windows, schedule
from server.app.execution_profile import generate_profile

ANSWERS = {"roles": ["student", "employee"], "regularity": "irregular", "barriers": ["starting", "overplanning"], "focusMinutes": 30, "dailyMinutes": 60, "energy": "evening", "recovery": "reduce", "constraints": "", "context": ""}

class FakeLLM:
    async def generate(self, **kwargs):
        if kwargs['name']=='execution_profile':
            return generate_profile(ANSWERS)['insights']
        return {'tasks': [{'title': f'연습문제 {i} 풀기', 'minutes': 20, 'doneWhen': '풀이와 오답 이유 기록', 'dueDate': None} for i in range(4)]}

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.temp.name)/'execution.sqlite3')
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=FakeLLM()))
        self.state = self.client.get('/api/execution').json()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self, path, **body):
        response = self.client.post('/api/execution'+path, json={'revision': self.state['revision'], **body})
        self.assertEqual(response.status_code,200,response.text)
        self.state = response.json()
        return self.state

    def setup_profile(self):
        self.post('/profile', answers=ANSWERS)
        self.assertIsNone(self.state['profile'])
        self.post('/profile/confirm')
        self.assertEqual(self.state['profile']['facts'],ANSWERS)
        settings={'slots':[{'day':0,'hour':18},{'day':0,'hour':19}], 'view':'timeline'}
        response=self.client.put('/api/execution/settings',json={'revision':self.state['revision'],'settings':settings})
        self.assertEqual(response.status_code,200,response.text)
        self.state=response.json()

    def test_draft_confirmation_reload_completion_and_reset(self):
        self.setup_profile()
        self.post('/plan',goal='연습문제 공부',startDate='2030-01-07',consent=True)
        self.assertIsNone(self.state['plan'])
        draft=self.state['planDraft']
        self.assertTrue(draft['entries'])
        self.post('/plan/confirm',planId=draft['id'])
        first=next(e for e in self.state['plan']['entries'] if e['kind']=='task')
        self.post('/task',planId=draft['id'],taskId=first['id'],completed=True)
        reloaded=ExecutionStore(self.store.path).read()
        self.assertTrue(next(e for e in reloaded['plan']['entries'] if e['id']==first['id'])['completed'])
        response=self.client.put('/api/execution/settings',json={'revision':self.state['revision'],'settings':{**self.state['settings'],'view':'checklist'}})
        self.state=response.json()
        self.assertTrue(next(e for e in self.state['plan']['entries'] if e['id']==first['id'])['completed'])
        old_revision=self.state['revision']
        self.post('/reset')
        self.assertIsNone(self.state['profile'])
        self.assertIsNone(self.state['plan'])
        self.assertEqual(self.state['settings']['slots'],[])
        self.assertGreater(self.state['revision'],old_revision)

    def test_rejects_stale_requests_and_requires_consent(self):
        self.setup_profile()
        r=self.client.post('/api/execution/profile/confirm',json={'revision':0})
        self.assertEqual(r.status_code,409)
        r=self.client.post('/api/execution/plan',json={'revision':self.state['revision'],'goal':'test','startDate':'2030-01-07'})
        self.assertEqual(r.status_code,400)
        r=self.client.post('/api/execution/profile',json={'revision':self.state['revision'],'answers':ANSWERS,'mode':'llm'})
        self.assertEqual(r.status_code,400)

    def test_new_calendar_conflict_blocks_confirmation(self):
        self.setup_profile()
        self.post('/plan',goal='공부',startDate='2030-01-07',consent=True)
        draft=self.state['planDraft']
        r=self.client.post('/api/execution/plan/confirm',json={'revision':self.state['revision'],'planId':draft['id'],'events':[{'date':'2030-01-07','startTime':'18:00','endTime':'20:00'}]})
        self.assertEqual(r.status_code,400)
        self.assertIsNone(self.store.read()['plan'])

    def test_unknown_and_llm_profile_are_preserved(self):
        unknown={**ANSWERS,'focusMinutes':None,'dailyMinutes':None}
        self.post('/profile',answers=unknown,mode='llm',consent=True)
        self.assertIsNone(self.state['profileDraft']['facts']['focusMinutes'])
        self.assertEqual(self.state['profileDraft']['source'],'llm')

    def test_invalid_answers_do_not_replace_saved_profile(self):
        self.setup_profile()
        saved=self.state['profile']
        r=self.client.post('/api/execution/profile',json={'revision':self.state['revision'],'answers':{**ANSWERS,'focusMinutes':True}})
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.store.read()['profile'],saved)

    def test_plan_prompt_and_chunk_size_follow_schedule_style(self):
        class RecordingLLM(FakeLLM):
            def __init__(self):
                self.calls = []

            async def generate(self, **kwargs):
                self.calls.append(kwargs)
                return await super().generate(**kwargs)

        self.client.close()
        # 18~20시 window (120분), buffer 40% -> flexible chunk 72분; time_blocks keeps blockMinutes 30.
        # scheduleStyle currently follows regularity (regular -> time_blocks).
        for regularity, style, max_block in (('regular', 'time_blocks', 30), ('irregular', 'flexible_queue', 72)):
            with self.subTest(style=style):
                llm = RecordingLLM()
                store = ExecutionStore(Path(self.temp.name)/f'{style}.sqlite3')
                with TestClient(create_app(execution_store=store, execution_llm=llm)) as client:
                    self.client, self.state = client, client.get('/api/execution').json()
                    self.post('/profile', answers={**ANSWERS, 'regularity': regularity})
                    self.post('/profile/confirm')
                    self.assertEqual(self.state['profile']['planningPreferences']['scheduleStyle'], style)
                    r = client.put('/api/execution/settings', json={'revision': self.state['revision'], 'settings': {'slots': [{'day': 0, 'hour': 18}, {'day': 0, 'hour': 19}], 'view': 'timeline'}})
                    self.state = r.json()
                    self.post('/plan', goal='공부', startDate='2030-01-07', consent=True)
                call = llm.calls[-1]
                self.assertEqual(call['context']['scheduleStyle'], style)
                self.assertEqual(call['context']['maxBlockMinutes'], max_block)
                self.assertIn(SCHEDULE_STYLE_INSTRUCTIONS[style], call['instructions'])

class SchedulerTests(unittest.TestCase):
    def test_busy_events_past_time_and_deadlines(self):
        slots=[Slot(day=0,hour=18),Slot(day=0,hour=19)]
        events=[BusyEvent(date=date(2030,1,7),startTime='18:20',endTime='18:50')]
        windows=availability_windows(date(2030,1,7),slots,events,now=datetime(2030,1,7,18,4))
        self.assertEqual(windows,[(datetime(2030,1,7,18,5),datetime(2030,1,7,18,20)),(datetime(2030,1,7,18,50),datetime(2030,1,7,20))])
        task={'title':'공부','minutes':15,'doneWhen':'완료','dueDate':None}
        entries,pending=schedule([task,task,{**task,'dueDate':'2030-01-06'}],windows,40)
        self.assertEqual(len(pending),1)
        for e in entries:
            self.assertTrue(any(a.isoformat(timespec='minutes')<=e['start']<e['end']<=b.isoformat(timespec='minutes') for a,b in windows))
        self.assertLessEqual(sum(e['minutes'] for e in entries if e['kind']=='task'),51)
        self.assertTrue(all(a['end']<=b['start'] for a,b in zip(entries,entries[1:])))

if __name__=='__main__':unittest.main()
