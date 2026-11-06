import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { ArrowUp, Pencil, Sparkles } from 'lucide-react'
import type { BlockedTime, ClosedProject, ExecutionState, PlannerAction, Project } from '../../shared/types'
import { plannerActionValid } from '../../shared/types'
import { projectColor } from '../../shared/projectColors'
import { useAiConsent } from '../../shared/aiConsent'
import { daysUntil, deadlineTone } from '../../shared/deadline'
import { dateKey } from '../../shared/constants'
import { confirmCheckIn, executionApi, projectContext } from './api'
import { settingLabel, settingValue } from './ProjectSettings'
import { blockedLabel } from './AvailabilityGrid'
import { ClosedNotice, CloseProject } from './CloseProject'
import { CheckIn, checkInCounts, checkInLabel, type CheckInDraft } from './CheckIn'

export type PlannerDraftCache = { messages: Record<string, string>; checkIns: Record<string, CheckInDraft> }

const days = '월화수목금토일'
// Which skill answered a message and what saved information it read, shown under the reply.
const SKILLS: Record<string, string> = { answer: '답하기', plan_create: '계획 만들기', plan_adjust: '계획 조정', availability: '가능한 시간', project_settings: '프로젝트 방식', small_talk: '대화', confirm: '카드 확인', check_in: '체크인' }
const LOOKUPS: Record<string, string> = { week: '이번 주 시간표', profile: '프로필', tasks: '이 프로젝트 작업', records: '실행 기록' }

/** One project's conversation: it goes on in a single session, and plans only this project's work. */
export function PlannerChat({ state, busy, run, project, onApplyPlan, onAdjust, onCloseProject, onReopenProject, events = [], projectInfo,
  startCheckIn = false, onCheckInStarted, draftCache, onEditProject, children }: {
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
  onEditProject?: () => void
  children?: ReactNode
}) {
  const [closing, setClosing] = useState(false)
  const [checkingIn, setCheckingIn] = useState(false)
  const localDrafts = useRef<PlannerDraftCache>({ messages: {}, checkIns: {} })
  const cache = draftCache ?? localDrafts.current
  const [, refreshDraft] = useState(0)
  const [consent, setConsent] = useAiConsent()
  const end = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const checkInBox = useRef<HTMLDivElement>(null)
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
  const checkInText = checkInLabel(checkInCounts(state, key))
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }) }, [messages.length, key, busy])
  useEffect(() => {
    if (checkingIn) checkInBox.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [checkingIn])
  useEffect(() => {
    const box = input.current
    if (!box) return
    if (!text) { box.style.height = ''; return }
    box.style.height = 'auto'
    box.style.height = `${Math.min(box.scrollHeight, 220)}px`
  }, [text, key])
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

  const cards = <>
    {closing && !ended && <CloseProject project={project} busy={busy} onCancel={() => setClosing(false)}
      onClose={async outcome => { const ok = await onCloseProject!(project, outcome); if (ok) setClosing(false); return ok }}/>}
    {ended && <ClosedNotice info={ended} busy={busy} onReopen={onReopenProject ? () => { void onReopenProject(project) } : undefined}/>}
    {action?.kind === 'check_in' && !checkingIn && <div className="planner-action" aria-label="확인 카드">
      <h3>{project.title} · 확인하지 않은 체크인이 있어요</h3>
      <p>{action.payload.records.map(r => `‘${r.taskTitle}’`).join(', ')}</p>
      <div className="planner-action-buttons">
        <button className="primary-button" disabled={busy} onClick={() => { void applyCard(action) }}>확인하고 기록</button>
        <button className="secondary-button" disabled={busy} onClick={() => setCheckingIn(true)}>체크인 이어하기·수정</button>
      </div>
    </div>}
    {action && action.kind !== 'check_in' && <div className="planner-action" aria-label="확인 카드">
      <p className="planner-action-kind">{action.kind === 'plan' || action.kind === 'adjust' ? '계획 카드' : '설정 카드'}</p>
      {action.kind === 'plan' ? <>
        <h3>이 내용으로 계획 초안을 만들까요?</h3>
        <dl className="planner-action-facts">
          <dt>목표</dt><dd>{action.payload.goal}</dd>
          <dt>기간</dt><dd>{planPeriod(action.payload.startDate, project)}</dd>
          {action.freeMinutes != null && <><dt>남은 빈 시간</dt><dd>{Math.floor(action.freeMinutes / 60)}시간{action.freeMinutes % 60 ? ` ${action.freeMinutes % 60}분` : ''}</dd></>}
        </dl>
        {week && <p className="execution-help">이번 주 계획에서 이 프로젝트의 남은 작업만 바꿔요. 다른 프로젝트 작업과 완료한 작업은 그대로 둬요.</p>}
        {!state.settings.slots.length && <p className="form-error">이번 주 계획할 시간이 아직 없어요. ‘이번 주 시간’ 메뉴에서 고르거나 대화로 알려 주세요.</p>}
        <div className="planner-action-buttons"><button className="primary-button" disabled={busy || cardBlocked(action)} onClick={() => { void applyCard(action) }}>확인하고 계획 초안 만들기</button></div>
      </> : action.kind === 'project_settings' ? <>
        <h3>‘{project.title}’ 프로젝트를 이렇게 맞출까요?</h3>
        <ul>{Object.entries(action.payload.changes).map(([key, change]) =>
          <li key={key}>{settingLabel(key)}: {settingValue(key, change.from)} → {settingValue(key, change.to)}</li>)}</ul>
        <p className="execution-help">이 프로젝트에만 적용돼요. 기본 프로필과 다른 프로젝트는 그대로예요.{weekTasks.some(t => !t.completed) ? ' 이번 주 이 프로젝트의 남은 작업은 다시 계획하면 반영돼요.' : ''}</p>
        <div className="planner-action-buttons"><button className="primary-button" disabled={busy} onClick={() => { void applyCard(action) }}>확인하고 이 프로젝트에 적용</button></div>
      </> : action.kind === 'adjust' ? <>
        <h3>이번 주 계획을 이렇게 바꿀까요?</h3>
        <dl className="planner-action-facts">
          {action.payload.blockedTimes.length > 0 && <><dt>비워 둘 시간</dt><dd>{action.payload.blockedTimes.map(blockedLabel).join(', ')}</dd></>}
          {action.payload.goal && <><dt>다시 계획</dt><dd>{action.payload.goal}</dd></>}
        </dl>
        {action.payload.blockedTimes.length > 0 && <p className="execution-help">모든 프로젝트에 적용돼요. 이 시간과 겹치는 작업은 빈 시간으로 옮겨요.</p>}
        {action.payload.goal && <p className="execution-help">이 프로젝트의 남은 작업만 새로 짜서 초안으로 보여 드려요. 다른 프로젝트 작업과 완료한 작업은 그대로예요.</p>}
        <div className="planner-action-buttons"><button className="primary-button" disabled={busy || cardBlocked(action)} onClick={() => { void applyCard(action) }}>{action.payload.goal ? '확인하고 계획 다시 짜기' : '확인하고 시간 비우기'}</button></div>
      </> : <>
        <h3>계획할 시간을 이렇게 바꿀까요?</h3>
        {action.change ? <>
          <dl className="planner-action-facts">
            {action.change.added.length > 0 && <><dt>더할 시간</dt><dd>{slotRanges(action.change.added)}</dd></>}
            {action.change.removed.length > 0 && <><dt>뺄 시간</dt><dd>{slotRanges(action.change.removed)}</dd></>}
          </dl>
          <p className="execution-help">이번 주에 모든 프로젝트가 함께 쓰는 시간이에요. 바꾼 뒤에는 주 {action.payload.slots.length}시간이에요.</p>
        </> : <>
          <p>{action.payload.slots.length ? slotRanges(action.payload.slots) : '선택한 시간 없음'}</p>
          <p className="execution-help">이번 주에 모든 프로젝트가 함께 쓰는 시간이에요. 기존에 저장한 시간을 모두 이 내용으로 바꿔요.</p>
        </>}
        <div className="planner-action-buttons"><button className="primary-button" disabled={busy} onClick={() => { void applyCard(action) }}>확인하고 시간 저장</button></div>
      </>}
      <p className="planner-action-hint">대화로 ‘좋아요’라고 답해도 적용돼요. 고칠 내용이 있으면 아래에 알려 주세요.</p>
    </div>}
    {children}
  </>

  return <section className="chat-page" id="weekly-goal" aria-label="대화형 플래너" style={{ '--thread-color': color } as CSSProperties}>
    <header className="chat-header" aria-label={`${project.title} 대화`}>
      <i className="project-dot" style={{ background: color }}/>
      <div className="chat-header-title">
        <div className="chat-header-name"><h2>{project.title}</h2>{!ended && <span className={`badge ${deadlineTone(project.dueDate)}`}>{deadlineBadge(project.dueDate)}</span>}</div>
        <p>{project.startDate} ~ {project.dueDate}{project.goal ? ` · ${project.goal}` : ''}</p>
      </div>
      <div className="chat-header-actions">
        {!ended && state.plan && <button type="button" className="secondary-button compact" disabled={busy || checkingIn} onClick={() => setCheckingIn(true)}>
          {checkInText || '체크인'}</button>}
        {onEditProject && <button type="button" className="secondary-button compact" onClick={onEditProject}><Pencil size={14}/>수정</button>}
        {!ended && onCloseProject && <button type="button" className="chat-end-button" disabled={busy || closing}
          onClick={() => setClosing(true)}>{overdue ? '마감 지남 · 끝내기' : '프로젝트 끝내기'}</button>}
      </div>
    </header>
    {(projectInfo || week) && <details className="chat-context">
      <summary>{week ? `이번 주 이 프로젝트 작업 ${weekTasks.filter(t => t.completed).length}/${weekTasks.length}개 완료 · ${week.startDate} ~ ${week.endDate}` : '프로젝트 설정 보기'}</summary>
      {projectInfo?.(project)}
    </details>}

    {checkingIn && !ended && <div ref={checkInBox} className="chat-checkin"><CheckIn key={`${key}-${state.plan?.id}`} state={state} project={project} busy={busy} run={run}
      draft={cache.checkIns[key]} onDraftChange={draft => { cache.checkIns[key] = draft }}
      consent={consent} onConsent={setConsent} onClose={() => setCheckingIn(false)}/></div>}

    <div className="chat-thread" role="log" aria-live="polite" aria-label="플래너 대화 기록">
      {!messages.length && <AssistantMessage>{!state.settings.slots.length
        ? '이번 주에 계획을 넣을 시간이 아직 없어요. ‘이번 주 시간’ 메뉴에서 고르거나, 여기서 ‘평일 저녁 7시부터 9시까지 돼요’처럼 말해 주세요.'
        : opening(state, project)}</AssistantMessage>}
      {messages.map(m => m.role === 'user'
        ? <div key={m.id} className="chat-message user"><span className="sr-only">나</span><p>{m.content}</p></div>
        : <AssistantMessage key={m.id} meta={m.skill ? `${SKILLS[m.skill] ?? m.skill}${m.lookups?.length ? ` · ${m.lookups.map(l => LOOKUPS[l] ?? l).join('·')} 확인` : ''}` : undefined}>{m.content}</AssistantMessage>)}
      {cards}
      {busy && <div className="chat-message assistant" role="status"><span className="chat-avatar"><Sparkles size={14}/></span><span className="chat-typing" aria-label="플래너가 생각하고 있어요"><i/><i/><i/></span></div>}
      <div ref={end}/>
    </div>

    {!ended && <form className="chat-composer" onSubmit={e => { e.preventDefault(); void send() }}>
      <div className="composer-box">
        <textarea ref={input} rows={1} aria-label="메시지" maxLength={2000} value={text} disabled={busy} onChange={e => setText(e.target.value)}
          placeholder={`${project.title}에 대해 무엇이든 말해 보세요`}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }}/>
        <button className="composer-send" disabled={busy || !consent || !text.trim() || !state.llmAvailable}><ArrowUp size={18}/>{busy ? '보내는 중…' : '보내기'}</button>
      </div>
      {!consent && <label className="composer-consent"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>대화·프로필·기억·가용 시간·프로젝트와 기존 할 일을 OpenAI에 전송하는 데 동의합니다.</label>}
      {!state.llmAvailable && <p className="composer-note">서버 API 키를 설정하면 플래너와 대화할 수 있습니다.</p>}
    </form>}
  </section>
}

function deadlineBadge(due: string) {
  const days = daysUntil(due)
  return days > 0 ? `D-${days}` : days === 0 ? '오늘 마감' : '마감 지남'
}

function AssistantMessage({ children, meta }: { children: ReactNode; meta?: string }) {
  return <div className="chat-message assistant">
    <span className="chat-avatar" aria-hidden="true"><Sparkles size={14}/></span>
    <div className="chat-message-body"><span className="sr-only">플래너</span><p>{children}</p>{meta && <small className="planner-skill">{meta}</small>}</div>
  </div>
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
