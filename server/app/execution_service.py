from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .execution_learning import REASON_CODES, propose_update
from .execution_store import ConflictError


class ExecutionRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planId: str
    taskId: str
    actualMinutes: int | None = Field(default=None, ge=0, le=1440, strict=True)
    remainingMinutes: int | None = Field(default=None, ge=0, le=1440, strict=True)
    result: Literal["completed", "partial", "not_started", "incomplete"]
    reasonCode: str | None = None
    note: str = Field(default="", max_length=2000)
    difficulty: int | None = Field(default=None, ge=1, le=5, strict=True)
    recoveryAction: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def valid_result(self):
        if self.reasonCode is not None and self.reasonCode not in REASON_CODES:
            raise ValueError("올바른 이유 코드를 선택해 주세요.")
        if self.result in ("partial", "not_started") and self.reasonCode is None:
            raise ValueError("미완료 이유를 선택해 주세요.")
        if self.result == "not_started" and self.actualMinutes != 0:
            raise ValueError("미시작 작업의 실제 시간은 0분이어야 합니다.")
        if self.result == "completed" and self.remainingMinutes not in (None, 0):
            raise ValueError("완료 작업의 남은 시간은 0분이어야 합니다.")
        return self

class ProposalNotFoundError(ValueError):
    pass


def summarize_execution(state, *, days=14, plan_id=None, profile_id=None, now=None):
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError("조회 기간은 1~365일이어야 합니다.")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    records = sorted((r for r in state.get('executionRecords', [])
                      if cutoff <= datetime.fromisoformat(r['createdAt']) <= now
                      and (plan_id is None or r['planId'] == plan_id)
                      and (profile_id is None or r.get('profileId') == profile_id)),
                     key=lambda r: (datetime.fromisoformat(r['createdAt']), r['id']))
    counts = {result: sum(r['result'] == result for r in records)
              for result in ('completed', 'partial', 'not_started', 'incomplete')}
    reasons = {code: sum(r['result'] != 'completed' and r['reasonCode'] == code for r in records)
               for code in REASON_CODES}
    planned = sum(r['plannedMinutes'] for r in records)
    measured = [r for r in records if r.get('actualMinutes') is not None]
    actual = sum(r['actualMinutes'] for r in measured)
    return {
        'revision': state['revision'], 'days': days,
        'periodStart': cutoff.isoformat(), 'periodEnd': now.isoformat(),
        'planId': plan_id, 'profileId': profile_id,
        'recordCount': len(records), 'resultCounts': counts,
        'completionRate': round(counts['completed'] / len(records) * 100, 2) if records else None,
        'plannedMinutes': planned, 'actualMinutes': actual,
        'minutesDifference': actual - sum(r['plannedMinutes'] for r in measured),
        'actualMinutesRecordCount': len(measured),
        'incompleteReasonCounts': reasons,
        'evidenceRecordIds': [r['id'] for r in records],
    }


class ExecutionService:
    def __init__(self, store):
        self.store = store

    def record_execution(self, revision, payload):
        def update(state):
            save_execution_record(state, payload)
        return self.store.change(revision, update)

    def decide_proposal(self, revision, proposal_id, decision):
        if decision not in ('approve', 'reject'):
            raise ValueError('승인 또는 거절을 선택해 주세요.')

        def update(state):
            proposal = next((p for p in state['profileUpdateProposals'] if p['id'] == proposal_id), None)
            if proposal is None:
                raise ProposalNotFoundError('변경 후보를 찾을 수 없습니다.')
            if proposal['status'] != 'pending':
                raise ConflictError('이미 처리한 변경 후보입니다.')
            if decision == 'approve':
                profile = state['profile']
                if not profile or profile['id'] != proposal['profileId'] or state['profileDraft']:
                    raise ConflictError('프로필이 변경되었거나 수정 중입니다. 후보를 거절하고 새 기록을 모아 주세요.')
                prefs = profile['planningPreferences']
                for key, value in proposal['proposedChanges'].items():
                    if prefs[key] != value['from']:
                        raise ConflictError('제안 이후 프로필 값이 변경되었습니다.')
                for key, value in proposal['proposedChanges'].items():
                    prefs[key] = value['to']
                profile['id'] = str(uuid4())
                proposal['appliedProfileId'] = profile['id']
                state['planDraft'] = None
            proposal['status'] = 'approved' if decision == 'approve' else 'rejected'
            proposal['decidedAt'] = datetime.now(timezone.utc).isoformat()

        return self.store.change(revision, update)

    def get_execution_summary(self, *, days=14, plan_id=None, profile_id=None):
        return summarize_execution(self.store.read(), days=days, plan_id=plan_id, profile_id=profile_id)


def save_execution_record(state, payload, *, allow_follow_up=False):
    request = ExecutionRecordInput.model_validate(payload)
    plan = state['plan']
    if not plan or plan['id'] != request.planId:
        raise ValueError('현재 확정한 계획을 선택해 주세요.')
    task = next((e for e in plan['entries'] if e['id'] == request.taskId and e['kind'] == 'task'), None)
    if task is None:
        raise ValueError('작업을 찾을 수 없습니다.')
    matches = [r for r in state['executionRecords'] if r['planId'] == plan['id'] and r['taskId'] == task['id']]
    pending = next((r for r in reversed(matches) if r['result'] != 'completed' and not r.get('recoveryAction')), None)
    if matches and not allow_follow_up:
        raise ConflictError('이미 실행 결과를 기록한 작업입니다.')
    if pending and allow_follow_up:
        if any(pending['id'] in p['evidenceRecordIds'] for p in state['profileUpdateProposals']):
            raise ConflictError('변경 후보의 근거로 사용된 기록은 수정할 수 없습니다.')
        pending.update(request.model_dump(exclude={'recoveryAction'}))
        record = pending
    else:
        record = request.model_dump()
        record.update(id=str(uuid4()), profileId=plan['profileId'], taskTitle=task['title'],
                      plannedMinutes=task['minutes'], createdAt=datetime.now(timezone.utc).isoformat())
        state['executionRecords'].append(record)
    task['completed'] = request.result == 'completed'
    propose_update(state)
    return record['id']


def set_recovery_action(state, record_id, action):
    if action not in ('shrink', 'reschedule', 'keep_current_plan', 'plan_replaced'):
        raise ValueError('지원하지 않는 복구 결정입니다.')
    record = next((r for r in state['executionRecords'] if r['id'] == record_id), None)
    if record is None:
        raise ValueError('실행 기록을 찾을 수 없습니다.')
    if record.get('recoveryAction') and record['recoveryAction'] != action:
        raise ConflictError('이미 복구 결정이 반영된 기록입니다.')
    record['recoveryAction'] = action
    record['recoveryDecidedAt'] = datetime.now(timezone.utc).isoformat()
