import { useState } from 'react'
import type { ExecutionRecord, ExecutionState } from '../../shared/types'
import { executionApi } from './api'

const reasons: Record<string, string> = {
  time_shortage: '시간 부족', task_too_large: '작업이 너무 큼', fatigue: '피로',
  interruption: '외부 방해', priority_changed: '우선순위 변경', unclear_task: '불명확한 작업',
  underestimated: '시간 과소 추정', other: '기타',
}
export function ExecutionLearning({ state, busy, run }: {
  state: ExecutionState; busy: boolean
  run: (action: () => Promise<ExecutionState>, message: string) => Promise<boolean>
}) {
  const [taskId, setTaskId] = useState('')
  const [result, setResult] = useState<ExecutionRecord['result']>('completed')
  const records = state.executionRecords ?? []
  const tasks = state.plan?.entries.filter(e => e.kind === 'task' && !records.some(r => r.planId === state.plan?.id && r.taskId === e.id)) ?? []
  return <section className="execution-card"><h2>실행 결과와 개선 제안</h2>
    <p className="execution-help">실제 실행을 기록하면 반복되는 어려움을 바탕으로 변경을 제안합니다. 승인 전에는 프로필이 바뀌지 않습니다. 작업당 한 번 기록할 수 있습니다.</p>
    {tasks.length > 0 && <form onSubmit={event => {
      event.preventDefault()
      const form = event.currentTarget
      const values = new FormData(form)
      void run(() => executionApi('/records', {
        revision: state.revision, planId: state.plan!.id, taskId,
        result, actualMinutes: Number(values.get('actualMinutes')),
        remainingMinutes: result === 'completed' ? 0 : values.get('remainingMinutes') ? Number(values.get('remainingMinutes')) : null,
        reasonCode: values.get('reasonCode') || null, note: values.get('note'),
        difficulty: values.get('difficulty') ? Number(values.get('difficulty')) : null,
        recoveryAction: values.get('recoveryAction'),
      }), '실행 결과를 저장했습니다.').then(ok => { if (ok) { form.reset(); setTaskId(''); setResult('completed') } })
    }}><fieldset className="execution-fieldset" disabled={busy}>
      <label className="execution-label">작업<select required value={taskId} onChange={e => setTaskId(e.target.value)}><option value="">작업 선택</option>{tasks.map(t => <option key={t.id} value={t.id}>{t.title} · 예정 {t.minutes}분</option>)}</select></label>
      <label className="execution-label">실행 결과<select value={result} onChange={e => setResult(e.target.value as ExecutionRecord['result'])}><option value="completed">완료</option><option value="partial">부분 완료</option><option value="not_started">미시작</option></select></label>
      <label className="execution-label">실제 시간(분)<input name="actualMinutes" type="number" min="0" max={result === 'not_started' ? 0 : 1440} required /></label>
      <label className="execution-label">남은 작업 예상 시간(분)<input name="remainingMinutes" type="number" min="0" max="1440" disabled={result === 'completed'} /></label>
      <label className="execution-label">미완료·지연 이유<select name="reasonCode" required={result !== 'completed'}><option value="">해당 없음</option>{Object.entries(reasons).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="execution-label">난이도<select name="difficulty"><option value="">미입력</option>{[1,2,3,4,5].map(n => <option key={n} value={n}>{n}{n === 1 ? ' · 쉬움' : n === 5 ? ' · 어려움' : ''}</option>)}</select></label>
      <label className="execution-label">메모<textarea name="note" maxLength={2000}/></label>
      <label className="execution-label">다시 시도할 방법<input name="recoveryAction" maxLength={1000}/></label>
      <button className="primary-button">실행 결과 저장</button>
    </fieldset></form>}
    {(state.profileUpdateProposals ?? []).map(p => <article key={p.id}>
      <h3>집중 구간 {p.proposedChanges.blockMinutes.from}분 → {p.proposedChanges.blockMinutes.to}분</h3>
      <p>{p.reason}</p><p>상태: {{ pending: '사용자 승인 대기', approved: '승인됨', rejected: '거절됨' }[p.status]}</p>
      <ul>{p.evidenceRecordIds.map(id => { const r = records.find(r => r.id === id); return <li key={id}>{r ? `${r.taskTitle}: 예정 ${r.plannedMinutes}분 / 실제 ${r.actualMinutes ?? '미입력'}분 · ${r.reasonCode ? reasons[r.reasonCode] : ''}` : '실행 기록'}<small> · 근거 ID: {id}</small></li> })}</ul>
      {p.status === 'pending' && <div className="execution-actions">{(['approve', 'reject'] as const).map(action => <button key={action} disabled={busy} className="secondary-button" onClick={() => { void run(() => executionApi(`/proposals/${p.id}/${action}`, { revision: state.revision }), action === 'approve' ? '승인했습니다. 다음 계획부터 적용됩니다.' : '제안을 거절했습니다.') }}>{action === 'approve' ? '승인' : '거절'}</button>)}</div>}
    </article>)}
    <details><summary>실행 기록 {records.length}건</summary>{[...records].reverse().map(r => <p key={r.id}>{r.taskTitle} · {{ completed: '완료', partial: '부분 완료', not_started: '미시작', incomplete: '미완료' }[r.result]}<br/>예정 {r.plannedMinutes}분 / 실제 {r.actualMinutes ?? '미입력'}분 · 차이 {r.actualMinutes === null ? '미정' : r.actualMinutes - r.plannedMinutes}분{r.reasonCode && ` · ${reasons[r.reasonCode]}`}<br/>{r.note}{r.recoveryAction && ` · 다음 시도: ${r.recoveryAction}`}</p>)}</details>
  </section>
}
