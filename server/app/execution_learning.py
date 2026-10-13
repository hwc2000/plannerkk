from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .project_profile import effective_preferences

REASON_CODES = ('time_shortage', 'task_too_large', 'fatigue', 'interruption',
                'priority_changed', 'unclear_task', 'underestimated', 'other')

# long-task-v1 rule parameters (system rule, not user traits).
WINDOW_DAYS = 14
LONG_TASK_MINUTES = 50
EVIDENCE_COUNT = 3
SIZE_REASONS = ('time_shortage', 'task_too_large')
MIN_SIZE_REASONS = 2
TARGET_BLOCK_MINUTES = 20


def propose_update(state, project_id=None):
    """Run long-task-v1 on one scope: a project's records, or records without a project.

    A pattern seen in one project becomes a change for that project only, so a
    hard project never shrinks the plans of the others.  Only records made
    under the scope's current settings count; older ones were already answered
    by the change that replaced those settings.
    """
    profile = state['profile']
    if not profile:
        return
    project_profile = (state.get('projectProfiles') or {}).get(project_id) if project_id else None
    try:
        prefs, _ = effective_preferences(profile, project_profile)
    except ValueError:
        return  # unusable project settings are reported when planning
    if prefs['blockMinutes'] <= TARGET_BLOCK_MINUTES:
        return
    project_profile_id = (project_profile or {}).get('id')
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    records = [r for r in state['executionRecords']
               if r.get('profileId') == profile['id'] and r.get('projectId') == project_id
               and r.get('projectProfileId') == project_profile_id
               and r['plannedMinutes'] >= LONG_TASK_MINUTES
               and datetime.fromisoformat(r['createdAt']) >= cutoff][-EVIDENCE_COUNT:]
    if len(records) != EVIDENCE_COUNT or any(r['result'] == 'completed' for r in records):
        return
    if sum(r['reasonCode'] in SIZE_REASONS for r in records) < MIN_SIZE_REASONS:
        return
    ids = [r['id'] for r in records]
    if any(p['profileId'] == profile['id'] and
           ((p['status'] == 'pending' and p.get('projectId') == project_id) or set(p['evidenceRecordIds']) & set(ids))
           for p in state['profileUpdateProposals']):
        return
    scope = '이 프로젝트에서 ' if project_id else ''
    state['profileUpdateProposals'].append({
        'id': str(uuid4()), 'profileId': profile['id'],
        'projectId': project_id, 'projectProfileId': project_profile_id,
        'proposedChanges': {'blockMinutes': {'from': prefs['blockMinutes'], 'to': TARGET_BLOCK_MINUTES}},
        'reason': (f'{scope}최근 {WINDOW_DAYS}일의 {LONG_TASK_MINUTES}분 이상 작업 {EVIDENCE_COUNT}건이 모두 미완료이며, '
                   f'{MIN_SIZE_REASONS}건 이상에서 시간 부족 또는 작업 크기가 이유였습니다. '
                   f'{TARGET_BLOCK_MINUTES}분 단위를 제안합니다.'),
        'evidenceRecordIds': ids, 'ruleVersion': 'long-task-v1',
        'status': 'pending', 'createdAt': datetime.now(timezone.utc).isoformat(), 'decidedAt': None,
    })
