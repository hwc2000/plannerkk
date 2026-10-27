import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import type { BlockedTime, ClosedProject, ExecutionState, PlannerAction, Project } from '../../shared/types'
import { plannerActionValid } from '../../shared/types'
import { projectColor } from '../../shared/projectColors'
import { dateKey } from '../../shared/constants'
import { confirmCheckIn, executionApi, projectContext } from './api'
import { settingLabel, settingValue } from './ProjectSettings'
import { blockedLabel } from './AvailabilityGrid'
import { ClosedNotice, CloseProject } from './CloseProject'
import { CheckIn, checkInTasks, type CheckInDraft } from './CheckIn'

export type PlannerDraftCache = { messages: Record<string, string>; checkIns: Record<string, CheckInDraft> }

const days = '월화수목금토일'
// Which skill answered a message and what saved information it read, shown under the reply.
const SKILLS: Record<string, string> = { answer: '답하기', plan_create: '계획 만들기', plan_adjust: '계획 조정', availability: '가능한 시간', project_settings: '프로젝트 방식', small_talk: '대화', confirm: '카드 확인', check_in: '체크인' }
const LOOKUPS: Record<string, string> = { week: '이번 주 시간표', profile: '프로필', tasks: '이 프로젝트 작업', records: '실행 기록' }

/** One project's conversation: it goes on in a single session, and plans only this project's work. */
export function PlannerChat({ state, busy, run, project, onApplyPlan, onAdjust, onCloseProject, onReopenProject, events = [], projectInfo,
  startCheckIn = false, onCheckInStarted, draftCache }: {
  state: ExecutionState; busy: boolean
  run: (action: () => Promise<ExecutionState>, message: string) => Promise<boolean>
  project: Project
  onApplyPlan: (goal: string, startDate: string, project: Project | null, consent: boolean) => Promise<boolean>
  /** Take hours out of this week and/or plan this project's open work again. */
  onAdjust?: (blocked: Array<Omit<BlockedTime, 'id'>>, goal: string | null, startDate: string, project: Project | null, consent: boolean) => Promise<boolean>
  /** End a project (its habits go to the user profile), or plan it again. */
  onCloseProject?: (project: Project, outcome: ClosedProject['outcome']) => Promise<boolean>
  onReopenProject?: (project: Project) => Promise<boolean>
  /** Calendar events, so the planner's week lookup leaves them out. */
  events?: Array<{ date: string; startTime: string; endTime: string }>
  projectInfo?: (project: Project) => ReactNode
  /** Open the check-in right away (from the home screen's prompt). */
  startCheckIn?: boolean
  onCheckInStarted?: () => void
  draftCache?: PlannerDraftCache
}) {
  const [closing, setClosing] = useState(false)
  const [checkingIn, setCheckingIn] = useState(false)
  const localDrafts = useRef<PlannerDraftCache>({ messages: {}, checkIns: {} })
  const cache = draftCache ?? localDrafts.current
  const [, refreshDraft] = useState(0)
  const [consent, setConsent] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  // The reply that agreed to the waiting card in words; its card is applied once the new state arrives.
  const confirming = useRef<{ projectId: string; messageId: string } | null>(null)
  const key = project.id
  const thread = state.plannerThreads?.[key]
  const messages = thread?.messages ?? []
  const ended = state.closedProjects?.[key]
  const action = !ended && plannerActionValid(thread?.action, state.revision, key) ? thread.action : null
  const text = cache.messages[key] ?? ''
  function setText(value: string) { cache.messages[key] = value; refreshDraft(n => n + 1) }
  const color = projectColor(key)
  const week = state.plan && state.plan.endDate >= dateKey(new Date()) ? state.plan : null
  const weekTasks = week?.entries.filter(e => e.kind === 'task' && (e.projectId ?? week.projectId ?? null) === key) ?? []

  useEffect(() => { setClosing(false); setCheckingIn(false) }, [key])
  useEffect(() => {
    if (!startCheckIn) return
    setCheckingIn(true)
    onCheckInStarted?.()
  }, [startCheckIn, onCheckInStarted])
  const toCheckIn = checkInTasks(state, key).due.length
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }) }, [messages.length, key])
  useEffect(() => {
    if (!confirming.current || confirming.current.projectId !== key || messages.at(-1)?.id !== confirming.current.messageId) return
    confirming.current = null
    if (action && !cardBlocked(action)) void applyCard(action)
  })

  /** A card can be applied only with what its button needs. */
  function cardBlocked(card: PlannerAction) {
    if (card.kind === 'plan') return !consent || !state.settings.slots.length
    if (card.kind === 'adjust') return !onAdjust || (!!card.payload.goal && !consent)
    return false
  }

  /** What the card's button does; saying "좋아요" in the chat does the same. */
  function applyCard(card: PlannerAction) {
    if (card.kind === 'plan') return onApplyPlan(card.payload.goal, card.payload.startDate, project, consent)
    if (card.kind === 'adjust') return onAdjust?.(card.payload.blockedTimes, card.payload.goal, card.payload.startDate, project, consent)
    if (card.kind === 'check_in') return run(() => confirmCheckIn(state, project, card.id), `‘${project.title}’ 체크인을 기록했어요.`)
    if (card.kind === 'project_settings') return run(() => executionApi(`/projects/${encodeURIComponent(card.payload.projectId)}/profile`,
      { revision: state.revision, overrides: card.payload.overrides }, 'PUT'), `‘${project.title}’ 프로젝트에 맞췄어요.`)
    return run(() => executionApi('/settings', { revision: state.revision, settings: card.payload }, 'PUT'), '계획할 시간을 저장했어요.')
  }

  async function send() {
    if (!text.trim() || !consent || busy) return
    const ok = await run(async () => {
      const next = await executionApi('/chat/message', {
        revision: state.revision, text, consent, project: projectContext(project), events,
      })
      const thread = next.plannerThreads?.[key]
      const last = thread?.messages.at(-1)
      if (last?.skill === 'confirm' && thread?.action) confirming.current = { projectId: key, messageId: last.id }
      return next
    }, '플래너가 답했어요.')
    if (ok) { cache.messages[key] = ''; refreshDraft(n => n + 1) }
  }

  const overdue = !ended && project.dueDate < dateKey(new Date())

  return <section className="planner-workspace" id="weekly-goal" aria-label="대화형 플래너" style={{ '--thread-color': color } as CSSProperties}>
    <div className="planner-chat execution-card" aria-label={`${project.title} 대화`}>
      <header className="planner-chat-head">
        <i className="project-dot" style={{ background: color }}/>
        <div><h2>{project.title}</h2>
          <p className="execution-help">{project.startDate} ~ {project.dueDate}{project.goal ? ` · ${project.goal}` : ''}</p></div>
        {!ended && state.plan && <button type="button" className="secondary-button" disabled={busy || checkingIn} onClick={() => setCheckingIn(true)}>
          체크인{toCheckIn > 0 && ` · ${toCheckIn}개`}</button>}
        {!ended && onCloseProject && <button type="button" className="secondary-button" disabled={busy || closing}
          onClick={() => setClosing(true)}>{overdue ? '마감 지남 · 끝내기' : '프로젝트 끝내기'}</button>}
      </header>
      {projectInfo?.(project)}
      {week && <p className="planner-week">이번 주 계획 {week.startDate} ~ {week.endDate} · 이 프로젝트 작업 {weekTasks.length}개 ({weekTasks.filter(t => t.completed).length}개 완료)</p>}

      <div className="profile-chat-log" role="log" aria-live="polite" aria-label="플래너 대화 기록">
        {!messages.length && <div className="profile-chat-message assistant"><small>플래너</small><p>{!state.settings.slots.length
          ? '이번 주에 계획을 넣을 시간이 아직 없어요. 홈에서 이번 주 시간을 고르거나, 여기서 ‘평일 저녁 7시부터 9시까지 돼요’처럼 말해 주세요.'
          : opening(state, project)}</p></div>}
        {messages.map(m => <div key={m.id} className={`profile-chat-message ${m.role}`}><small>{m.role === 'user' ? '나' : '플래너'}</small><p>{m.content}</p>
          {m.skill && <small className="planner-skill">{SKILLS[m.skill] ?? m.skill}{m.lookups?.length ? ` · ${m.lookups.map(l => LOOKUPS[l] ?? l).join('·')} 확인` : ''}</small>}</div>)}
        {checkingIn && !ended && <CheckIn key={`${key}-${state.plan?.id}`} state={state} project={project} busy={busy} run={run}
          draft={cache.checkIns[key]} onDraftChange={draft => { cache.checkIns[key] = draft }}
          consent={consent} onConsent={setConsent} onClose={() => setCheckingIn(false)}/>}
        {busy && <p role="status">플래너가 생각하고 있어요…</p>}
        <div ref={end}/>
      </div>

      {closing && !ended && <CloseProject project={project} busy={busy} onCancel={() => setClosing(false)}
        onClose={async outcome => { const ok = await onCloseProject!(project, outcome); if (ok) setClosing(false); return ok }}/>}
      {ended && <ClosedNotice info={ended} busy={busy} onReopen={onReopenProject ? () => { void onReopenProject(project) } : undefined}/>}
      {action?.kind === 'check_in' && !checkingIn && <div className="planner-action" aria-label="확인 카드">
        <h3>{project.title} · 확인하지 않은 체크인이 있어요</h3>
        <p>{action.payload.records.map(r => `‘${r.taskTitle}’`).join(', ')}</p>
        <button className="primary-button" disabled={busy} onClick={() => { void applyCard(action) }}>확인하고 기록</button>
        <button className="secondary-button" disabled={busy} onClick={() => setCheckingIn(true)}>체크인 이어하기·수정</button>
      </div>}
      {action && action.kind !== 'check_in' && <div className="planner-action" aria-label="확인 카드">
        <p className="section-kicker">{project.title} · {action.kind === 'plan' || action.kind === 'adjust' ? '계획 카드' : '설정 카드'}</p>
        {action.kind === 'plan' ? <>
          <h3>이 내용으로 계획 초안을 만들까요?</h3>
          <p><strong>목표: </strong>{action.payload.goal}</p>
          <p><strong>기간: </strong>{planPeriod(action.payload.startDate, project)}</p>
          {action.freeMinutes != null && <p><strong>이번 주 남은 빈 시간: </strong>{Math.floor(action.freeMinutes / 60)}시간{action.freeMinutes % 60 ? ` ${action.freeMinutes % 60}분` : ''}</p>}
          {week && <p className="execution-help">이번 주 계획에서 이 프로젝트의 남은 작업만 바꿔요. 다른 프로젝트 작업과 완료한 작업은 그대로 둬요.</p>}
          {!state.settings.slots.length && <p className="form-error">이번 주 계획할 시간이 아직 없어요. 홈에서 고르거나 대화로 알려 주세요.</p>}
          <button className="primary-button" disabled={busy || cardBlocked(action)} onClick={() => { void applyCard(action) }}>확인하고 계획 초안 만들기</button>
        </> : action.kind === 'project_settings' ? <>
          <h3>‘{project.title}’ 프로젝트를 이렇게 맞출까요?</h3>
          <ul>{Object.entries(action.payload.changes).map(([key, change]) =>
            <li key={key}>{settingLabel(key)}: {settingValue(key, change.from)} → {settingValue(key, change.to)}</li>)}</ul>
          <p className="execution-help">이 프로젝트에만 적용돼요. 기본 프로필과 다른 프로젝트는 그대로예요.{weekTasks.some(t => !t.completed) ? ' 이번 주 이 프로젝트의 남은 작업은 다시 계획하면 반영돼요.' : ''}</p>
          <button className="primary-button" disabled={busy} onClick={() => { void applyCard(action) }}>확인하고 이 프로젝트에 적용</button>
        </> : action.kind === 'adjust' ? <>
          <h3>이번 주 계획을 이렇게 바꿀까요?</h3>
          {action.payload.blockedTimes.length > 0 && <>
            <p><strong>비워 둘 시간: </strong>{action.payload.blockedTimes.map(blockedLabel).join(', ')}</p>
            <p className="execution-help">모든 프로젝트에 적용돼요. 이 시간과 겹치는 작업은 빈 시간으로 옮겨요.</p>
          </>}
          {action.payload.goal && <>
            <p><strong>다시 계획: </strong>{action.payload.goal}</p>
            <p className="execution-help">이 프로젝트의 남은 작업만 새로 짜서 초안으로 보여 드려요. 다른 프로젝트 작업과 완료한 작업은 그대로예요.</p>
          </>}
          <button className="primary-button" disabled={busy || cardBlocked(action)} onClick={() => { void applyCard(action) }}>{action.payload.goal ? '확인하고 계획 다시 짜기' : '확인하고 시간 비우기'}</button>
        </> : <>
          <h3>계획할 시간을 이렇게 바꿀까요?</h3>
          {action.change ? <>
            {action.change.added.length > 0 && <p><strong>더할 시간: </strong>{slotRanges(action.change.added)}</p>}
            {action.change.removed.length > 0 && <p><strong>뺄 시간: </strong>{slotRanges(action.change.removed)}</p>}
            <p className="execution-help">이번 주에 모든 프로젝트가 함께 쓰는 시간이에요. 바꾼 뒤에는 주 {action.payload.slots.length}시간이에요.</p>
          </> : <>
            <p>{action.payload.slots.length ? slotRanges(action.payload.slots) : '선택한 시간 없음'}</p>
            <p className="execution-help">이번 주에 모든 프로젝트가 함께 쓰는 시간이에요. 기존에 저장한 시간을 모두 이 내용으로 바꿔요.</p>
          </>}
          <button className="primary-button" disabled={busy} onClick={() => { void applyCard(action) }}>확인하고 시간 저장</button>
        </>}
        <p className="execution-help">대화로 ‘좋아요’라고 답해도 적용돼요. 고칠 내용이 있으면 아래 대화로 알려 주세요.</p>
      </div>}

      {!ended && <form onSubmit={e => { e.preventDefault(); void send() }}>
        <label className="execution-label">메시지<textarea maxLength={2000} value={text} disabled={busy} onChange={e => setText(e.target.value)}
          placeholder={`예: ${project.title} 이번 주에는 발표 자료 초안까지 끝내고 싶어요. 금요일이 마감이에요.`}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }}/></label>
        <label className="execution-inline"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>대화·프로필·기억·가용 시간·프로젝트와 기존 할 일을 OpenAI에 전송하는 데 동의합니다.</label>
        <button className="primary-button" disabled={busy || !consent || !text.trim() || !state.llmAvailable}>{busy ? '보내는 중…' : '보내기'}</button>
        {!state.llmAvailable && <p className="execution-help">서버 API 키를 설정하면 플래너와 대화할 수 있습니다.</p>}
      </form>}
    </div>
  </section>
}

/** A new project's first words: what it plans with now, and an invitation to make it its own. */
function opening(state: ExecutionState, project: Project) {
  const overrides = state.projectProfiles?.[project.id]?.overrides ?? {}
  const block = overrides.blockMinutes?.value ?? state.profile?.planningPreferences.blockMinutes
  const now = Object.keys(overrides).length
    ? `이 프로젝트만의 값으로 계획해요: ${Object.entries(overrides).map(([key, item]) => `${settingLabel(key)} ${settingValue(key, item.value)}`).join(', ')}. `
    : block ? `지금은 기본 프로필대로 한 번에 ${block}분씩 계획해요. ` : ''
  return `‘${project.title}’ 대화를 시작해요. ${now}이 프로젝트만 다르게 하고 싶은 점(예: 한 번에 25분씩, 하루 1시간만)이 있으면 먼저 알려 주세요. 없으면 이번 주에 하고 싶은 일과 마감을 말해 주세요.`
}

/** What the plan covers: a week from the start, cut at the project's own dates. */
function planPeriod(startDate: string, project: Project) {
  const weekEnd = new Date(`${startDate}T12:00:00`)
  weekEnd.setDate(weekEnd.getDate() + 6)
  const start = project.startDate > startDate ? project.startDate : startDate
  const end = dateKey(weekEnd)
  return project.dueDate < end ? `${start} ~ ${project.dueDate} (프로젝트 마감까지)` : `${start} ~ ${end} (7일)`
}

/** Weekly hours as ranges per day, e.g. 월 9~11시, 화 19~22시. */
function slotRanges(slots: Array<{ day: number; hour: number }>) {
  const ranges: Array<[number, number, number]> = []
  for (const s of [...slots].sort((a, b) => a.day - b.day || a.hour - b.hour)) {
    const last = ranges.at(-1)
    if (last && last[0] === s.day && last[2] === s.hour) last[2] = s.hour + 1
    else ranges.push([s.day, s.hour, s.hour + 1])
  }
  return ranges.map(([day, start, end]) => `${days[day]} ${start}~${end}시`).join(', ')
}
