import { useState } from 'react'
import type { CheckIn, ExecutionRecord, ExecutionState, Memory, ProfileUpdateProposal, Project, RecoveryStrategy } from '../../shared/types'
import { dateKey } from '../../shared/constants'
import { adaptiveApi, executionApi, replansCurrentPlan } from './api'
import { focusTimeLabels, options } from './profileLabels'
import { RecoveryReview } from './RecoveryReview'

export const reasons: Record<string, string> = {
  time_shortage: '시간 부족', task_too_large: '작업이 너무 큼', fatigue: '피로',
  interruption: '외부 방해', priority_changed: '우선순위 변경', unclear_task: '불명확한 작업',
  underestimated: '시간 과소 추정', other: '기타',
}
const periodLabel = (value: string) => focusTimeLabels[value] ?? '모름'
const STRATEGIES: Record<RecoveryStrategy, string> = {
  reschedule: '다른 빈 시간으로 옮기기', shrink: '이 작업만 줄이기', replan: '이 프로젝트 다시 계획하기',
}
type Run = (action: () => Promise<ExecutionState>, message: string | ((next: ExecutionState) => string)) => Promise<boolean>

/** Local time as plan entries write it, e.g. 2030-01-07T19:30. */
function nowKey(now = new Date()) {
  return `${dateKey(now)}T${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

/** What a proposal changes, in the user's words. */
function proposalTitle(p: ProfileUpdateProposal) {
  const { blockMinutes, focusTime, recoveryPreference } = p.proposedChanges
  const recovery = (value: string) => options.recovery.find(([code]) => code === value)?.[1] ?? value
  return [
    blockMinutes && `집중 구간 ${blockMinutes.from}분 → ${blockMinutes.to}분`,
    focusTime && `집중이 잘 되는 시간대 ${periodLabel(focusTime.from)} → ${periodLabel(focusTime.to)}`,
    recoveryPreference && `계획이 틀어졌을 때 ${recovery(recoveryPreference.from)} → ${recovery(recoveryPreference.to)}`,
  ].filter(Boolean).join(' · ')
}

export function ExecutionLearning({ state, busy, run, approveProposal, events = [], memories = [], projects = [] }: {
  state: ExecutionState; busy: boolean
  run: Run
  approveProposal?: (proposalId: string, consent: boolean) => Promise<boolean>
  events?: Array<{ date: string; startTime: string; endTime: string }>
  memories?: Memory[]
  projects?: Project[]
}) {
  const projectTitle = (projectId: string) =>
    projects.find(p => p.id === projectId)?.title ?? (state.plan?.project?.id === projectId ? state.plan.project.title : '다른 프로젝트')
  // An approved change can be replanned again only while the settings it produced are still current.
  const stillCurrent = (p: ProfileUpdateProposal) => p.appliedProfileId === state.profile?.id
    && (!p.projectId || p.appliedProjectProfileId === state.projectProfiles?.[p.projectId]?.id)
  const [taskId, setTaskId] = useState('')
  const [result, setResult] = useState<ExecutionRecord['result']>('completed')
  const [reasonCode, setReasonCode] = useState('')
  const [adaptiveConsent, setAdaptiveConsent] = useState(false)
  const [replanConsent, setReplanConsent] = useState(false)
  const [sizingConsent, setSizingConsent] = useState(false)
  const [recoveryConsent, setRecoveryConsent] = useState(false)
  // The planner could not pick a way back on its own: the user picks, with the same check-in.
  const [choice, setChoice] = useState<{ taskId: string; checkIn: CheckIn; options: RecoveryStrategy[]; reason?: string } | null>(null)
  const records = state.executionRecords ?? []
  const tasks = state.plan?.entries.filter(e => e.kind === 'task' && !e.completed && !records.some(r => r.planId === state.plan?.id && r.taskId === e.id)) ?? []
  // Their time has passed and nothing says how they went: the loop learns only from what is recorded.
  const missed = tasks.filter(e => !e.starter && e.end <= nowKey())
  const priorityChanged = result !== 'completed' && reasonCode === 'priority_changed'
  const recover = result !== 'completed' && !priorityChanged && recoveryConsent

  function checkInAgain(taskId: string, checkIn: CheckIn, strategy: RecoveryStrategy | null) {
    return () => adaptiveApi('/check-in', { revision: state.revision, taskId, checkIn, strategy, consent: true, memories, events })
  }

  /** What the planner did with a failed task; when it needs the user to pick a way, offer the choices. */
  function recoveryMessage(taskId: string, checkIn: CheckIn) {
    return (next: ExecutionState) => {
      const outcome = next.result
      setChoice(null)
      if (next.planDraft && outcome?.approvalStatus === 'waiting' && outcome.strategy === 'replan') return '실행 결과를 남기고 이 프로젝트의 재계획 초안을 만들었어요. 검토 후 확정해 주세요.'
      if (next.recoveryDrafts?.[taskId]) return '실행 결과를 남기고 복구안을 만들었어요. 아래에서 확인해 주세요.'
      if (outcome?.approvalStatus === 'needs_input') {
        const options = outcome.fallback?.options?.length ? outcome.fallback.options : (['reschedule', 'shrink', 'replan'] as RecoveryStrategy[])
        setChoice({ taskId, checkIn, options, reason: outcome.fallback?.reason })
        return ['실행 결과를 남겼어요.', outcome.fallback?.reason, '어떻게 다시 넣을지 골라 주세요.'].filter(Boolean).join(' ')
      }
      return `실행 결과를 남겼어요. ${outcome?.fallback?.reason ? `${outcome.fallback.reason} ` : ''}계획은 그대로예요.`
    }
  }

  return <section className="record-panel" id="check-in">
    <p className="record-intro">체크인 대화 없이 실행 결과를 바로 남겨요. 기록이 쌓이면 반복되는 어려움을 보고 바꿀 점을 제안하고, 승인하기 전에는 프로필이 바뀌지 않아요.</p>
    {missed.length > 0 && <div className="record-block" aria-label="지난 작업 확인">
      <h3>시간이 지난 작업 {missed.length}개, 어떻게 됐나요?</h3>
      <ul className="record-missed">{missed.map(e => <li key={e.id}>
        <span className="record-missed-title"><small>{e.start.slice(5, 10).replace('-', '/')} {e.start.slice(11)} · {e.minutes}분</small>{e.title}</span>
        <span className="record-missed-actions">
          <button type="button" className="secondary-button compact" disabled={busy} onClick={() => { void run(() => executionApi('/task', { revision: state.revision, planId: state.plan!.id, taskId: e.id, completed: true }), '완료를 실행 기록에 남겼습니다.') }}>했어요</button>
          <button type="button" className="secondary-button compact" disabled={busy} onClick={() => { setTaskId(e.id); setResult('not_started') }}>못 했어요</button>
        </span></li>)}</ul>
    </div>}
    {choice && <div className="record-block" aria-label="복구 방법 고르기">
      <strong>어떻게 다시 넣을까요?</strong>{choice.reason && <p className="execution-help">{choice.reason}</p>}
      <div className="execution-actions">{choice.options.map(option => <button key={option} type="button" className="secondary-button" disabled={busy}
        onClick={() => { void run(checkInAgain(choice.taskId, choice.checkIn, option), recoveryMessage(choice.taskId, choice.checkIn)) }}>{STRATEGIES[option]}</button>)}
        <button type="button" className="secondary-button" disabled={busy} onClick={() => setChoice(null)}>그대로 두기</button></div>
    </div>}
    <RecoveryReview state={state} busy={busy} run={run} events={events} memories={memories}/>
    {tasks.length > 0 && <form onSubmit={event => {
      event.preventDefault()
      const form = event.currentTarget
      const values = new FormData(form)
      const actualMinutes = Number(values.get('actualMinutes'))
      const remainingMinutes = result === 'completed' ? 0 : values.get('remainingMinutes') ? Number(values.get('remainingMinutes')) : null
      const checkIn: CheckIn = {
        completed: false, actualMinutes, remainingMinutes: remainingMinutes || null, reasonCode: reasonCode || null,
        note: String(values.get('note') ?? ''), difficulty: values.get('difficulty') ? Number(values.get('difficulty')) : null,
      }
      const chosen = taskId
      const action = recover
        ? checkInAgain(chosen, checkIn, null)
        : priorityChanged
        ? () => adaptiveApi('/check-in', {
          revision: state.revision,
          taskId,
          checkIn: {
            completed: false,
            actualMinutes,
            remainingMinutes,
            reasonCode,
            note: values.get('note'),
            difficulty: values.get('difficulty') ? Number(values.get('difficulty')) : null,
          },
          strategy: 'replan',
          consent: adaptiveConsent,
          memories,
          events,
        })
        : () => executionApi('/records', {
          revision: state.revision, planId: state.plan!.id, taskId,
          result, actualMinutes, remainingMinutes,
          reasonCode: reasonCode || null, note: values.get('note'),
          difficulty: values.get('difficulty') ? Number(values.get('difficulty')) : null,
          recoveryAction: values.get('recoveryAction'),
          consent: sizingConsent,
        })
      void run(
        action,
        recover ? recoveryMessage(chosen, checkIn)
          : priorityChanged ? '실행 결과와 재계획 초안을 저장했습니다. 검토 후 확정해 주세요.' : '실행 결과를 저장했습니다.',
      ).then(ok => {
        if (ok) {
          form.reset(); setTaskId(''); setResult('completed'); setReasonCode(''); setAdaptiveConsent(false)
        }
      })
    }} className="record-block"><h3>실행 결과 기록</h3><fieldset className="record-form" disabled={busy}>
      <div className="record-grid">
      <label className="execution-label record-wide">작업<select required value={taskId} onChange={e => setTaskId(e.target.value)}><option value="">작업 선택</option>{tasks.map(t => <option key={t.id} value={t.id}>{t.title} · 예정 {t.minutes}분</option>)}</select></label>
      <label className="execution-label">실행 결과<select value={result} onChange={e => { const next = e.target.value as ExecutionRecord['result']; setResult(next); if (next === 'completed') { setReasonCode(''); setAdaptiveConsent(false) } }}><option value="completed">완료</option><option value="partial">부분 완료</option><option value="not_started">미시작</option></select></label>
      <label className="execution-label">실제 시간(분)<input name="actualMinutes" type="number" min="0" max={result === 'not_started' ? 0 : 1440} required /></label>
      {result !== 'completed' && <label className="execution-label">미완료·지연 이유<select name="reasonCode" value={reasonCode} onChange={e => { setReasonCode(e.target.value); if (e.target.value !== 'priority_changed') setAdaptiveConsent(false) }} required><option value="">이유 선택</option>{Object.entries(reasons).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>}
      {result !== 'completed' && <label className="execution-label">남은 작업 예상 시간(분)<input name="remainingMinutes" type="number" min={priorityChanged ? 1 : 0} max="1440" /></label>}
      </div>
      <details className="record-more"><summary>더 적기 (선택) · 난이도·메모{!priorityChanged && !recover ? '·다시 시도할 방법' : ''}</summary>
      <div className="record-grid">
      <label className="execution-label">난이도<select name="difficulty"><option value="">미입력</option>{[1,2,3,4,5].map(n => <option key={n} value={n}>{n}{n === 1 ? ' · 쉬움' : n === 5 ? ' · 어려움' : ''}</option>)}</select></label>
      {!priorityChanged && !recover && <label className="execution-label">다시 시도할 방법<input name="recoveryAction" maxLength={1000}/></label>}
      <label className="execution-label record-wide">메모<textarea name="note" maxLength={priorityChanged ? 1500 : 2000}/></label>
      </div>
      </details>
      {result !== 'completed' && !priorityChanged && <label className="execution-inline"><input type="checkbox" checked={recoveryConsent} onChange={e => setRecoveryConsent(e.target.checked)}/>못 한 작업을 다시 넣을 방법(다른 빈 시간으로 옮기기·줄이기)을 제안받기 위해 작업·체크인 정보와 반복 패턴 판단에 필요한 기록을 AI에 전송하는 데 동의합니다. 제안은 승인해야 반영돼요.</label>}
      {!priorityChanged && !recover && <label className="execution-inline"><input type="checkbox" checked={sizingConsent} onChange={e => setSizingConsent(e.target.checked)}/>(선택) 작업 이름·시간·메모를 AI에 보내, 기록에서 반복되는 패턴(한 번에 할 길이, 집중이 잘 되는 시간대)을 작업 내용까지 보고 판단받는 데 동의합니다.</label>}
      {priorityChanged && <>
        <p className="execution-help">우선순위 변경은 현재 계획을 바로 바꾸지 않고 새 주간 계획 초안을 만듭니다.</p>
        <label className="execution-inline"><input type="checkbox" checked={adaptiveConsent} onChange={e => setAdaptiveConsent(e.target.checked)}/>목표·프로필·기억·가용 시간·프로젝트·현재 계획·작업·체크인 정보를 LLM에 전송해 재계획 초안을 만드는 데 동의합니다.</label>
      </>}
      <div className="record-submit"><button className="primary-button" disabled={priorityChanged && !adaptiveConsent}>{priorityChanged ? '재계획 초안 만들기' : recover ? '결과 저장하고 다시 넣을 방법 받기' : '실행 결과 저장'}</button></div>
    </fieldset></form>}
    {(state.profileUpdateProposals ?? []).map(p => { const replan = replansCurrentPlan(state, p); return <article key={p.id} className="record-block record-proposal">
      <h3>{proposalTitle(p)}</h3>
      {p.projectId && <p className="execution-help">이 프로젝트에만 적용: {projectTitle(p.projectId)} · 다른 프로젝트와 기본 프로필은 그대로입니다.{!replan && p.status === 'pending' && ' 지금 계획은 그대로 두고 이 프로젝트의 다음 계획부터 반영합니다.'}</p>}
      <p>{p.reason}</p>
      {p.sizing && <p className="execution-help">{p.sizedBy === 'ai' ? '실제 기록과 작업 내용을 AI가 함께 보고 정했어요.' : p.sizing}</p>}
      {p.focusStats && <p className="execution-help">{Object.entries(p.focusStats).map(([period, s]) => `${periodLabel(period)} ${s.planned}건 중 ${s.finished}건 완료`).join(' · ')}</p>}
      {p.aiReason && <p className="execution-help">AI 판단: {p.aiReason}</p>}
      <p>상태: {p.sourceProjectId ? '프로젝트를 끝내며 반영함' : { pending: '사용자 승인 대기', approved: '승인됨', rejected: '거절됨' }[p.status]}</p>
      <details><summary>근거 기록 {p.evidenceRecordIds.length}건</summary><ul>{p.evidenceRecordIds.map(id => { const r = records.find(r => r.id === id); return <li key={id}>{r ? `${r.taskTitle}: ${r.result === 'completed' ? '완료' : `예정 ${r.plannedMinutes}분 / 실제 ${r.actualMinutes ?? '미입력'}분`}${r.reasonCode ? ` · ${reasons[r.reasonCode]}` : ''}` : '실행 기록'}<small> · 근거 ID: {id}</small></li> })}</ul></details>
      {!p.sourceProjectId && (p.status === 'pending' || (p.status === 'approved' && replan && stillCurrent(p))) && <>
        {replan && <label className="execution-inline"><input type="checkbox" checked={replanConsent} onChange={e => setReplanConsent(e.target.checked)}/>목표·프로필·기억·가용 시간·프로젝트·기존 할 일·현재 계획·변경 근거를 LLM에 전송해 재계획 초안을 만드는 데 동의합니다.</label>}
        <div className="execution-actions">
          <button disabled={busy || (replan && !replanConsent)} className="secondary-button" onClick={() => {
            if (approveProposal) void approveProposal(p.id, replanConsent)
            else if (p.status === 'pending') void run(() => executionApi(`/proposals/${p.id}/approve`, { revision: state.revision }), '승인했습니다.')
          }}>{p.status === 'approved' ? '재계획 초안 다시 만들기' : replan ? '승인하고 재계획 초안 만들기' : '승인'}</button>
          {p.status === 'pending' && <button disabled={busy} className="secondary-button" onClick={() => { void run(() => executionApi(`/proposals/${p.id}/reject`, { revision: state.revision }), '제안을 거절했습니다.') }}>거절</button>}
        </div>
      </>}
    </article> })}
    <details className="record-history"><summary>실행 기록 {records.length}건</summary>{[...records].reverse().map(r => <p key={r.id}>{r.projectId && `[${projectTitle(r.projectId)}] `}{r.taskTitle} · {{ completed: '완료', partial: '부분 완료', not_started: '미시작', incomplete: '미완료' }[r.result]}<br/>예정 {r.plannedMinutes}분 / 실제 {r.actualMinutes ?? '미입력'}분 · 차이 {r.actualMinutes === null ? '미정' : r.actualMinutes - r.plannedMinutes}분{r.reasonCode && ` · ${reasons[r.reasonCode]}`}<br/>{r.note}{r.recoveryAction && ` · 다음 시도: ${r.recoveryAction}`}</p>)}</details>
  </section>
}
