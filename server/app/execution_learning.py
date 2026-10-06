from datetime import datetime, timedelta, timezone
from uuid import uuid4

REASON_CODES = ('time_shortage', 'task_too_large', 'fatigue', 'interruption',
                'priority_changed', 'unclear_task', 'underestimated', 'other')


def propose_update(state):
    profile = state['profile']
    if not profile or profile['planningPreferences']['blockMinutes'] <= 20:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    records = [r for r in state['executionRecords']
               if r.get('profileId') == profile['id'] and r['plannedMinutes'] >= 50
               and datetime.fromisoformat(r['createdAt']) >= cutoff][-3:]
    if len(records) != 3 or any(r['result'] == 'completed' for r in records):
        return
    if sum(r['reasonCode'] in ('time_shortage', 'task_too_large') for r in records) < 2:
        return
    ids = [r['id'] for r in records]
    if any(p['profileId'] == profile['id'] and
           (p['status'] == 'pending' or set(p['evidenceRecordIds']) & set(ids))
           for p in state['profileUpdateProposals']):
        return
    state['profileUpdateProposals'].append({
        'id': str(uuid4()), 'profileId': profile['id'],
        'proposedChanges': {'blockMinutes': {'from': profile['planningPreferences']['blockMinutes'], 'to': 20}},
        'reason': '최근 14일의 50분 이상 작업 3건이 모두 미완료이며, 2건 이상에서 시간 부족 또는 작업 크기가 이유였습니다. 20분 단위를 제안합니다.',
        'evidenceRecordIds': ids, 'ruleVersion': 'long-task-v1',
        'status': 'pending', 'createdAt': datetime.now(timezone.utc).isoformat(), 'decidedAt': None,
    })
