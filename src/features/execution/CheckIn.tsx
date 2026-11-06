import { useRef, useState } from 'react'
import type { Atmosphere, CheckInRecord, CheckInSession, ExecutionPlan, ExecutionState, InsightQuestion, Level, Project, ProjectFeedback } from '../../shared/types'
import { plannerActionValid } from '../../shared/types'
import { confirmCheckIn, executionApi, fetchInsights, projectContext } from './api'
import { reasons } from './ExecutionLearning'

type Run = (action: () => Promise<ExecutionState>, message: string) => Promise<boolean>
type Result = CheckInRecord['result']
type Task = ExecutionPlan['entries'][number]
const RESULTS: Array<[Result, string]> = [['completed', '다 했어요'], ['partial', '조금 했어요'], ['not_started', '못 했어요']]
const RESULT_TEXT: Record<Result, string> = { completed: '다 함', partial: '조금 함', not_started: '못 함' }
const FOCUS_TEXT: Record<Level, string> = { good: '잘 됨', ok: '보통', poor: '안 됨' }
const CONDITION_TEXT: Record<Level, string> = { good: '좋음', ok: '보통', poor: '나쁨' }
const ATMOSPHERE_TEXT: Record<Atmosphere, string> = { quiet: '조용한 곳', lively: '소리 있는 열린 곳' }
const SESSION = ['place', 'atmosphere', 'focus', 'condition'] as const
const LOADS: Array<[NonNullable<ProjectFeedback['load']>, string]> = [['too_much', '많았어요'], ['right', '적당했어요'], ['too_little', '적었어요']]
const TIMES: Array<[NonNullable<ProjectFeedback['timeFit']>, string]> = [['too_short', '짧았어요'], ['right', '알맞았어요'], ['too_long', '길었어요'], ['unknown', '모르겠어요']]

/** Session dates are server-owned Korean calendar days, independent of browser timezone. */
export function checkInDate(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date)
  const part = (name: string) => parts.find(p => p.type === name)!.value
  return `${part('year')}-${part('month')}-${part('day')}`
}

/** Keep checkbox-only completions eligible, but not an already confirmed check-in. */
export function checkInTasks(state: ExecutionState, projectId: string, today = checkInDate()) {
  const plan = state.plan
  if (!plan) return { due: [] as Task[], early: [] as Task[], ticked: new Set<string>(), recorded: [] as Task[] }
  // Shared-week merges retain task IDs while replacing the plan ID.
  const latest = new Map((state.executionRecords ?? []).map(r => [r.taskId, r]))
  const ticked = new Set<string>()
  const open = plan.entries.filter(e => {
    if (e.kind !== 'task' || e.starter || (e.projectId ?? plan.projectId ?? null) !== projectId) return false
    const record = latest.get(e.id)
    if (!record) return !e.completed
    const bare = record.result === 'completed' && !record.checkInId && !record.checkInDate && !SESSION.some(f => record[f])
    if (bare) ticked.add(e.id)
    return bare
  })
  const due = open.filter(e => e.start.slice(0, 10) <= today)
  const evidence = new Set((state.profileUpdateProposals ?? []).flatMap(p => p.evidenceRecordIds))
  const recorded = plan.entries.filter(e => e.kind === 'task' && !e.starter && (e.projectId ?? plan.projectId ?? null) === projectId
    && e.start.slice(0, 10) <= today && !open.includes(e) && latest.has(e.id) && !evidence.has(latest.get(e.id)!.id))
  return { due, early: due.length ? [] : open.filter(e => !ticked.has(e.id)).slice(0, 5), ticked, recorded }
}

export function checkInCounts(state: ExecutionState, projectId: string, today = checkInDate()) {
  const { due } = checkInTasks(state, projectId, today)
  const weekIsOpen = !!state.plan && state.plan.endDate >= today
  return {
    today: due.filter(e => e.start.slice(0, 10) === today).length,
    late: weekIsOpen ? due.filter(e => e.start.slice(0, 10) < today).length : 0,
  }
}

export function checkInLabel({ today, late }: { today: number; late: number }) {
  if (today) return `오늘 체크인 · ${today}개${late ? ` · 밀린 ${late}개` : ''}`
  return late ? `밀린 체크인 · ${late}개` : ''
}

/** Memory-only draft owned by the signed-in workspace, never browser storage. */
export type CheckInDraft = {
  planId?: string; tasks: Task[]; results: Record<string, Result>; questions: InsightQuestion[]
  step: 'results' | 'details' | 'load' | 'done'; said: string; text: string; note: string
  load?: ProjectFeedback['load']; timeFit?: ProjectFeedback['timeFit']
}
export function CheckIn({ state, project, busy, run, consent, onConsent, onClose, draft, onDraftChange }: {
  state: ExecutionState; project: Project; busy: boolean; run: Run
  consent: boolean; onConsent: (value: boolean) => void; onClose: () => void
  draft?: CheckInDraft; onDraftChange?: (draft: CheckInDraft) => void
}) {
  const { due, early, ticked, recorded } = checkInTasks(state, project.id)
  const lastResult = new Map((state.executionRecords ?? []).map(r => [r.taskId, r.result]))
  const action = state.plannerThreads?.[project.id]?.action
  const card = plannerActionValid(action, state.revision, project.id) && action.kind === 'check_in' ? action : null
  const [data, setData] = useState<CheckInDraft>(() => {
    if (draft && draft.planId === state.plan?.id && draft.step !== 'done') return draft
    // After a workspace restart the server card, not today's due queue, owns
    // the selection. Look up its tasks in the whole plan (including early work).
    const tasks = card ? card.payload.records.flatMap(record => {
      const task = state.plan?.entries.find(t => t.id === record.taskId && t.kind === 'task' && (t.projectId ?? state.plan?.projectId) === project.id)
      return task ? [task] : []
    }) : (due.length ? due : early).slice(0, 20)
    const results = card ? Object.fromEntries(card.payload.records.map(r => [r.taskId, r.result]))
      : Object.fromEntries(tasks.filter(t => ticked.has(t.id)).map(t => [t.id, 'completed' as const]))
    const said = card ? (card.payload.session?.note ?? card.payload.records[0]?.note ?? '') : ''
    return { planId: state.plan?.id, tasks, results, questions: [], step: card ? 'details' : 'results', said, text: '', note: '' }
  })
  const latest = useRef(data)
  function update(patch: Partial<CheckInDraft>) {
    const next = { ...latest.current, ...patch }
    latest.current = next
    onDraftChange?.(next)
    setData(next)
  }
  const { tasks, results, questions, step, said, text, note, load, timeFit } = data
  const again = recorded.filter(t => !tasks.some(x => x.id === t.id))
  function toggleAgain(taskId: string, value: Result) {
    const next = { ...results }
    if (next[taskId] === value) delete next[taskId]
    else next[taskId] = value
    update({ results: next })
  }
  const chosen = [...tasks, ...again].filter(t => results[t.id])
  const today = checkInDate()
  const known: Partial<CheckInSession> = (card?.payload.date ?? card?.payload.session?.date) === today ? { ...card?.payload.knownDaily } : {}
  for (const session of state.checkInSessions ?? []) {
    if (session.date === today) for (const field of SESSION) if (session[field]) Object.assign(known, { [field]: session[field] })
  }
  const unknownLabels = SESSION.filter(field => !known[field]).map(field => ({ place: '장소', atmosphere: '분위기', focus: '집중', condition: '컨디션' })[field])
  async function next() {
    // Load once per draft; these invitations are never prerequisites for recording.
    let followups = questions
    if (!followups.length) try { followups = (await fetchInsights()).next.filter(q => !SESSION.some(field => field === q.key && known[field])).slice(0, 3) } catch { followups = [] }
    update({ questions: followups, step: 'details' })
  }
  async function send(extra: string) {
    const all = [said, extra].filter(Boolean).join('\n')
    const ok = await run(() => executionApi('/chat/check-in', {
      revision: state.revision, consent, project: projectContext(project), text: all, asked: questions.map(q => q.key),
      results: chosen.map(t => ({ taskId: t.id, result: results[t.id] })),
    }), `‘${project.title}’ 체크인 내용을 정리했어요. 맞는지 확인해 주세요.`)
    if (ok) update({ said: all, text: '' })
  }
  async function confirm() {
    if (!card) return
    const ok = await run(() => confirmCheckIn(state, project, card.id), `‘${project.title}’ 체크인을 기록했어요.`)
    if (ok) update({ step: 'load' })
  }
  async function feedback() {
    const ok = await run(() => executionApi(`/projects/${encodeURIComponent(project.id)}/feedback`, { revision: state.revision, ...(load ? { load } : {}), ...(timeFit ? { timeFit } : {}), note }), `‘${project.title}’ 계획에 대한 의견을 저장했어요.`)
    if (ok) update({ step: 'done' })
  }
  if (!tasks.length && !again.length && !card && step !== 'load' && step !== 'done') return <div className="profile-chat-message assistant checkin" aria-label="체크인"><small>{project.title} · 체크인</small>
    <p>지금은 기록할 작업이 없어요. 확정한 계획의 작업이 생기면 여기서 알려 주세요.</p><div className="checkin-footer"><button type="button" className="secondary-button" onClick={onClose}>닫기</button></div></div>
  return <div className="checkin" aria-label="체크인">
    <h3>{project.title} · 체크인</h3>
    {step !== 'done' && <button type="button" className="secondary-button" onClick={onClose}>취소·나중에 이어하기</button>}
    {step === 'results' && <div className="profile-chat-message assistant"><small>플래너</small>
      <p>{due.length ? '오늘까지 계획한 작업이에요. 알려 주고 싶은 작업만 골라 주세요. 이미 완료 체크한 작업도 상태를 덧붙일 수 있어요.' : tasks.length ? '먼저 한 작업이 있으면 알려 주세요.' : '이번에 새로 기록할 작업은 없어요. 이미 기록한 작업을 다시 남길 수 있어요.'} 한 번에 최대 20개씩 기록해요.</p>
      <ul className="checkin-tasks">{tasks.map(t => <li key={t.id}>
        <span><b>{t.title}</b><small>{t.start.slice(5, 10).replace('-', '/')} {t.start.slice(11)} · {t.minutes}분</small></span>
        <span className="checkin-choices">{RESULTS.map(([value, label]) => <button type="button" key={value} aria-pressed={results[t.id] === value} disabled={busy || ticked.has(t.id)} onClick={() => update({ results: { ...results, [t.id]: value } })}>{label}</button>)}</span>
      </li>)}</ul>
      {again.length > 0 && <>
        <p className="checkin-again-title">이미 기록한 작업 · 다시 남기면 지난 기록을 고쳐요</p>
        <ul className="checkin-tasks">{again.map(t => <li key={t.id}>
          <span><b>{t.title}</b><small>{t.start.slice(5, 10).replace('-', '/')} {t.start.slice(11)} · 지난 기록: {RESULT_TEXT[lastResult.get(t.id) as Result] ?? '기록함'}</small></span>
          <span className="checkin-choices">{RESULTS.map(([value, label]) => <button type="button" key={value} aria-pressed={results[t.id] === value} disabled={busy} onClick={() => toggleAgain(t.id, value)}>{label}</button>)}</span>
        </li>)}</ul>
      </>}
      <button type="button" className="primary-button" disabled={busy || !chosen.length} onClick={() => { void next() }}>다음</button>
    </div>}
    {step === 'details' && <div className="profile-chat-message assistant"><small>플래너</small>
      <p>이번 작업은 전반적으로 어땠나요? 분량이나 배정 시간이 알맞았는지, 하고 싶은 말만 남겨 주세요.</p>
      {sessionLine(known) && <p>오늘 이미 알려 준 상태: {sessionLine(known)}. 다시 답하지 않아도 돼요. 달라졌다면 알려 주세요.</p>}
      {unknownLabels.length > 0 && <p>오늘의 {unknownLabels.join('·')}도 원하면 한마디로 알려 주세요. 여러 작업에 공통으로 한 번만 남겨요.</p>}
      <div className="checkin-optional"><strong>답해주시면 다음 계획에 도움이 돼요, 건너뛰어도 괜찮아요</strong>
        {questions.length > 0 && <ul>{questions.slice(0, 3).map(q => <li key={q.key}>{q.question}</li>)}</ul>}</div>
      <label className="execution-label">답하기 (선택)<textarea maxLength={1000} value={text} disabled={busy} onChange={e => update({ text: e.target.value })} placeholder="예: 분량은 적당했어요. 도서관에서 집중이 잘 됐어요."/></label>
      <label className="execution-inline"><input type="checkbox" checked={consent} onChange={e => onConsent(e.target.checked)}/>답한 내용과 이 작업들을 OpenAI에 보내 정리하는 데 동의합니다.</label>
      <div className="execution-actions">
        <button type="button" className="secondary-button" disabled={busy} onClick={() => update({ step: 'results' })}>이전</button>
        <button type="button" className="primary-button" disabled={busy || !text.trim() || !consent} onClick={() => { void send(text.trim()) }}>{card ? '고쳐서 다시 정리' : '보내기'}</button>
        {!card && <button type="button" className="secondary-button" disabled={busy || !chosen.length} onClick={() => { void send('') }}>덧붙일 말 없이 기록</button>}
      </div>
    </div>}
    {step === 'details' && card && <div className="planner-action" aria-label="체크인 확인 카드">
      <h3>{project.title} · 체크인 확인</h3>
      <ul>{card.payload.records.map(r => <li key={r.taskId}>‘{r.taskTitle}’ {RESULT_TEXT[r.result]}{r.actualMinutes ? ` · 실제 ${r.actualMinutes}분` : ''}{r.reasonCode ? ` · 이유: ${reasons[r.reasonCode] ?? r.reasonCode}` : ''}</li>)}</ul>
      {sessionLine(card.payload.session ?? card.payload.records[0]) && <p><strong>오늘 상태: </strong>{sessionLine(card.payload.session ?? card.payload.records[0])}</p>}
      {!!card.payload.learned?.length && <p><strong>대화에서 정리한 내용 (관찰·선호 후보): </strong>{card.payload.learned.join(' · ')}</p>}
      {(card.payload.session?.note ?? card.payload.records[0]?.note) && <p className="execution-help">메모: {card.payload.session?.note ?? card.payload.records[0]?.note}</p>}
      <button type="button" className="primary-button" disabled={busy} onClick={() => { void confirm() }}>확인하고 기록</button>
      <p className="execution-help">틀린 곳은 위에서 고쳐 주세요. 확인 전에는 실행 기록에 저장되지 않아요.</p>
    </div>}
    {step === 'load' && <div className="profile-chat-message assistant"><small>{project.title} · 계획 피드백 (선택)</small>
      <p>체크인은 기록했어요. 완료 여부와 별개로, 이번 계획 분량은 어땠어요?</p>
      <div className="execution-actions">{LOADS.map(([value, label]) => <button type="button" key={value} disabled={busy} aria-pressed={load === value} onClick={() => update({ load: value })}>{label}</button>)}</div>
      <p>작업에 배정한 시간은 알맞았나요? (선택)</p>
      <div className="execution-actions">{TIMES.map(([value, label]) => <button type="button" key={value} disabled={busy} aria-pressed={timeFit === value} onClick={() => update({ timeFit: value })}>{label}</button>)}</div>
      <label className="execution-label">더 하고 싶은 말 (선택)<textarea maxLength={500} value={note} disabled={busy} placeholder="예: 분량은 괜찮았는데 첫 작업이 조금 길었어요." onChange={e => update({ note: e.target.value })}/></label>
      <p className="execution-help">이 프로젝트의 다음 계획에만 참고해요. 기본 프로필을 바꾸지 않아요.</p>
      <div className="checkin-footer">
        <button type="button" className="secondary-button" disabled={busy} onClick={() => update({ step: 'done' })}>건너뛰기</button>
        <button type="button" className="primary-button" disabled={busy || (!load && !timeFit && !note.trim())} onClick={() => { void feedback() }}>의견 저장</button>
      </div>
    </div>}
    {step === 'done' && <div className="profile-chat-message assistant"><p>알려 줘서 고마워요. 다음에 이 프로젝트를 계획할 때 참고해요.</p><div className="checkin-footer"><button type="button" className="secondary-button" onClick={onClose}>닫기</button></div></div>}
  </div>
}
function sessionLine(record: Partial<CheckInSession> | undefined) {
  if (!record) return ''
  return [record.place && `장소 ${record.place}`, record.atmosphere && `분위기 ${ATMOSPHERE_TEXT[record.atmosphere]}`, record.focus && `집중 ${FOCUS_TEXT[record.focus]}`, record.condition && `컨디션 ${CONDITION_TEXT[record.condition]}`].filter(Boolean).join(' · ')
}
