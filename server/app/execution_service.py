from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .execution_learning import REASON_CODES, propose_focus_time, propose_growth, propose_update
from .execution_store import ConflictError
from .plan_merge import entry_owner
from .project_profile import apply_project_proposal, entry_settings_version
from .user_profile import apply_profile_proposal


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
    # How the session went, from the check-in: signals about the user, so they stay with the
    # user's records after the project ends (planner_checkin.py).
    place: str | None = Field(default=None, max_length=40)
    atmosphere: Literal["quiet", "lively"] | None = None
    focus: Literal["good", "ok", "poor"] | None = None
    condition: Literal["good", "ok", "poor"] | None = None

    @model_validator(mode="after")
    def valid_result(self):
        if self.reasonCode is not None and self.reasonCode not in REASON_CODES:
            raise ValueError("올바른 이유 코드를 선택해 주세요.")
        if self.result == "not_started" and self.actualMinutes != 0:
            raise ValueError("미시작 작업의 실제 시간은 0분이어야 합니다.")
        if self.result == "completed" and self.remainingMinutes not in (None, 0):
            raise ValueError("완료 작업의 남은 시간은 0분이어야 합니다.")
        return self

class ProposalNotFoundError(ValueError):
    pass


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
                # A project change only touches that project: other projects' drafts stay valid.
                project_id = proposal.get('projectId')
                draft = state.get('planDraft')
                if project_id is None or (draft and draft.get('projectId') == project_id):
                    resolve_plan_draft(state, 'keep_current_plan')
                if project_id is None:
                    apply_profile_proposal(state, proposal_id, expected_version=profile['version'])
                else:
                    apply_project_proposal(state, proposal_id, user_id=self.store.user_id)
                return
            proposal['status'] = 'approved' if decision == 'approve' else 'rejected'
            proposal['decidedAt'] = datetime.now(timezone.utc).isoformat()

        return self.store.change(revision, update)


def save_execution_record(state, payload, *, allow_follow_up=False):
    request = ExecutionRecordInput.model_validate(payload)
    # Only the server's recovery-review path can record an approval.
    if request.recoveryAction is not None:
        raise ValueError('복구 결정은 복구안을 확인한 뒤 반영해 주세요.')
    plan = state['plan']
    if not plan or plan['id'] != request.planId:
        raise ValueError('현재 확정한 계획을 선택해 주세요.')
    task = next((e for e in plan['entries'] if e['id'] == request.taskId and e['kind'] == 'task'), None)
    if task is None:
        raise ValueError('작업을 찾을 수 없습니다.')
    if task.get('completed'):
        raise ConflictError('이미 완료한 작업입니다.')
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
        record = _new_record(plan, task, request)
        state['executionRecords'].append(record)
    task['completed'] = request.result == 'completed'
    propose_update(state, record.get('projectId'))
    propose_growth(state, record.get('projectId'))
    propose_focus_time(state)
    return record['id']


def _new_record(plan, task, request):
    # The task's project and the settings version it was planned with travel with
    # the record, so learning counts it for that project only, even in a shared week.
    record = request.model_dump()
    record.update(id=str(uuid4()), profileId=plan['profileId'], profileVersion=plan.get('profileVersion'),
                  projectId=entry_owner(plan, task), projectProfileId=entry_settings_version(plan, task),
                  taskTitle=task['title'], plannedMinutes=task['minutes'], plannedStart=task['start'],
                  createdAt=datetime.now(timezone.utc).isoformat())
    return record


def set_task_completion(state, plan_id, task_id, completed):
    """Checking a task off stores a completion record, so completions count in learning.

    Unchecking undoes it: the task's latest record, when it is a completion, is
    removed. Older failure records of the task are kept.
    """
    plan = state['plan']
    if not plan or plan['id'] != plan_id:
        raise ValueError('계획이 변경되었습니다. 다시 불러와 주세요.')
    task = next((e for e in plan['entries'] if e['id'] == task_id and e['kind'] == 'task'), None)
    if task is None:
        raise ValueError('작업을 찾을 수 없습니다.')
    if bool(task.get('completed')) == completed:
        return
    if completed:
        request = ExecutionRecordInput(planId=plan_id, taskId=task_id, result='completed')
        state['executionRecords'].append(_new_record(plan, task, request))
        task['completed'] = True
        propose_update(state, entry_owner(plan, task))
        propose_growth(state, entry_owner(plan, task))
        propose_focus_time(state)
        return
    matches = [r for r in state['executionRecords'] if r['planId'] == plan_id and r['taskId'] == task_id]
    if matches and matches[-1]['result'] == 'completed':
        last = matches[-1]
        using = [p for p in state['profileUpdateProposals'] if last['id'] in p['evidenceRecordIds']]
        if any(p['status'] == 'approved' for p in using):
            raise ConflictError('이 완료 기록으로 이미 프로필을 바꿨어요. 완료 표시는 되돌릴 수 없어요.')
        # A suggestion still waiting stood on this completion; without it the suggestion goes too.
        for proposal in using:
            if proposal['status'] == 'pending':
                proposal.update(status='rejected', decidedAt=datetime.now(timezone.utc).isoformat(), closedBy='evidence_withdrawn')
        state['executionRecords'].remove(last)
    task['completed'] = False


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


_PLAN_DRAFT_RECORD_KEY = '_planDraftRecordId'


def replace_plan_draft(state, draft, *, source_record_id=None):
    """Replace a reviewable full-plan draft while resolving its previous source record."""
    previous = state.get(_PLAN_DRAFT_RECORD_KEY)
    if previous and previous != source_record_id:
        set_recovery_action(state, previous, 'keep_current_plan')
    state['planDraft'] = draft
    state[_PLAN_DRAFT_RECORD_KEY] = source_record_id


def resolve_plan_draft(state, action):
    """Resolve the B record that triggered the current full-plan draft, then clear it."""
    record_id = state.get(_PLAN_DRAFT_RECORD_KEY)
    if record_id:
        set_recovery_action(state, record_id, action)
    state['planDraft'] = None
    state[_PLAN_DRAFT_RECORD_KEY] = None
