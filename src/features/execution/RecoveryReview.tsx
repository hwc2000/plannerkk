import { useState } from 'react'
import type { ExecutionState, Memory, RecoveryDraft } from '../../shared/types'
import { adaptiveApi } from './api'

const KIND: Record<RecoveryDraft['draft']['kind'], string> = {
  shrink: '이 작업 줄이기', reschedule: '다른 시간으로 옮기기', fit_deadline: '마감 전에 맞춰 줄이기',
}
type Run = (action: () => Promise<ExecutionState>, message: string | ((next: ExecutionState) => string)) => Promise<boolean>

const WEEKDAYS = '월화수목금토일'

/** 1/8(화) 18:00~18:30, like the other time labels on this screen. */
function when(start: string, end: string | null) {
  const day = new Date(`${start.slice(0, 10)}T12:00:00`)
  return `${day.getMonth() + 1}/${day.getDate()}(${WEEKDAYS[(day.getDay() + 6) % 7]}) ${start.slice(11)}${end ? `~${end.slice(11)}` : ''}`
}

/** A failed task's recovery drafts, waiting for the user: nothing changes in the plan until one is approved. */
export function RecoveryReview({ state, busy, run, events = [], memories = [] }: {
  state: ExecutionState; busy: boolean; run: Run
  events?: Array<{ date: string; startTime: string; endTime: string }>
  memories?: Memory[]
}) {
  const [feedback, setFeedback] = useState<Record<string, string>>({})
  const [consent, setConsent] = useState(false)
  const plan = state.plan
  const drafts = Object.values(state.recoveryDrafts ?? {}).filter(d => d.planId === plan?.id)
  if (!plan || !drafts.length) return null

  function review(draft: RecoveryDraft, decision: 'approve' | 'reject' | 'revise') {
    return run(() => adaptiveApi('/review', {
      revision: state.revision, draftId: draft.id, decision, events, memories,
      ...(decision === 'revise' ? { feedback: feedback[draft.id], consent } : {}),
    }), next => {
      const reason = next.result?.fallback?.reason
      if (decision === 'reject') return '복구안을 거절했어요. 계획은 그대로예요.'
      if (decision === 'approve') return next.result?.approvalStatus === 'approved' ? '복구안을 계획에 반영했어요.' : `반영하지 못했어요. ${reason ?? '다시 시도해 주세요.'}`
      return reason ? `고치지 못했어요. ${reason}` : '말씀하신 대로 고친 복구안을 만들었어요.'
    })
  }

  return <div className="recovery-drafts">
    <h3>못 한 작업의 복구안</h3>
    <p className="execution-help">승인하기 전에는 계획이 바뀌지 않아요.</p>
    {drafts.map(d => {
      const task = plan.entries.find(e => e.id === d.taskId)
      return <article key={d.id} className="execution-fieldset" aria-label={`${task?.title ?? '작업'} 복구안`}>
        <strong>{KIND[d.draft.kind]} · {task?.title ?? '작업'}</strong>
        <ul>{d.draft.tasks.map((t, i) => <li key={i}>{t.start && `${when(t.start, t.end)} · `}{t.title} · {t.minutes}분<br/><small>{t.doneWhen}</small></li>)}</ul>
        {d.draft.carryOverMinutes > 0 && <p className="execution-help">이번 주에 들어가지 않는 {d.draft.carryOverMinutes}분은 ‘배치하지 못한 작업’으로 넘겨요.</p>}
        {d.draft.droppedScope.length > 0 && <p className="execution-help">이번에는 뺀 것: {d.draft.droppedScope.join(', ')}</p>}
        {d.draft.appliedReasons.length > 0 && <p className="execution-help">{d.draft.appliedReasons.join(' ')}</p>}
        <div className="execution-actions">
          <button className="primary-button" disabled={busy} onClick={() => { void review(d, 'approve') }}>승인하고 계획에 반영</button>
          <button className="secondary-button" disabled={busy} onClick={() => { void review(d, 'reject') }}>거절하고 그대로 두기</button>
        </div>
        <details><summary>고쳐서 다시 받기</summary>
          <label className="execution-label">어떻게 고칠까요?<textarea maxLength={1000} value={feedback[d.id] ?? ''} onChange={e => setFeedback(f => ({ ...f, [d.id]: e.target.value }))}/></label>
          <label className="execution-inline"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>고칠 내용과 작업·체크인 정보를 AI에 전송하는 데 동의합니다.</label>
          <button className="secondary-button" disabled={busy || !consent || !(feedback[d.id] ?? '').trim()} onClick={() => { void review(d, 'revise') }}>고친 복구안 받기</button>
        </details>
      </article>
    })}
  </div>
}
