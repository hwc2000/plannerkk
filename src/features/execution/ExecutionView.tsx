import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, Trash2, UserRound } from 'lucide-react'
import './execution.css'
import type { BlockedTime, CalendarEvent, ClosedProject, ExecutionPlan, ExecutionState, Milestone, Project, Memory, ProfileUpdateProposal } from '../../shared/types'
import { dateKey } from '../../shared/constants'
import { ExecutionLearning } from './ExecutionLearning'
import { ProfileForm } from './ProfileForm'
import { PlannerChat, type PlannerDraftCache } from './PlannerChat'
import { checkInCounts, checkInLabel } from './CheckIn'
import { AboutMe } from './AboutMe'
import { AvailabilityGrid, blockedLabel } from './AvailabilityGrid'
import { PlanReasons } from './PlanReasons'
import { ProjectSettings } from './ProjectSettings'
import { answerLabels, focusTimeText, formatAnswer, notAsked } from './profileLabels'
import { approveProposalAndReplan, executionApi, existingTasksFor, planIsStale, planProjectIds, projectContext, replansCurrentPlan, staleProjectIds } from './api'
import { projectColor } from '../../shared/projectColors'
import { useAiConsent } from '../../shared/aiConsent'
import { deadlineTone } from '../../shared/deadline'

/** What a screen shows: the home week, one project's conversation, or the user's profile. */
export type ExecutionSection = 'home' | 'schedule' | 'project' | 'profile'

/** Older mixed drafts sometimes identify owners only on tasks, not plan.projects. */
function draftProjectIds(plan: ExecutionPlan) {
  return [...new Set([...planProjectIds(plan), ...(plan.project ? [plan.project.id] : []),
    ...plan.entries.filter(e => e.kind === 'task').map(e => e.projectId ?? plan.projectId),
    ...plan.pendingTasks.map(e => e.projectId ?? plan.projectId)].filter((id): id is string => !!id))]
}

/** How far a deadline is, e.g. 마감 D-3. */
function deadlineLabel(due: string, now = new Date()) {
  const days = Math.round((new Date(`${due}T12:00:00`).getTime() - new Date(`${dateKey(now)}T12:00:00`).getTime()) / 86400000)
  return days > 0 ? `마감 D-${days}` : days === 0 ? '오늘 마감' : '마감 지남'
}

/** The week as the home screen shows it, e.g. 10/26~11/1. */
function thisWeekLabel(now = new Date()) {
  const monday = new Date(now)
  monday.setDate(now.getDate() - (now.getDay() + 6) % 7)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  const md = (d: Date) => `${d.getMonth() + 1}/${d.getDate()}`
  return `${md(monday)}~${md(sunday)}`
}

export function ExecutionView({ state, onChange, projects, milestones, events, memories = [], section = 'profile', projectId, calendar,
  onProjectStatus, onProfileConfirmed, onGoHome, onOpenProfile, onOpenSchedule, onOpenProject, onCreateProject, onEditProject, startCheckIn, onCheckInStarted }: {
  state: ExecutionState; onChange: (state: ExecutionState) => void
  projects: Project[]; milestones: Milestone[]; events: CalendarEvent[]; memories?: Memory[]
  section?: ExecutionSection
  /** The project a 'project' screen talks about. */
  projectId?: string
  /** The calendar the home screen shows between this week's hours and the plan. */
  calendar?: ReactNode
  /** The project list lives in the browser: ending or reopening a project updates its status there too. */
  onProjectStatus?: (projectId: string, status: Project['status']) => void
  /** The first survey is done: the app moves on to the home week. */
  onProfileConfirmed?: () => void
  onGoHome?: () => void
  onOpenProfile?: () => void
  onOpenSchedule?: () => void
  /** Open a project; ``checkIn`` opens its check-in right away. */
  onOpenProject?: (projectId: string, checkIn?: boolean) => void
  onCreateProject?: () => void
  onEditProject?: (projectId: string) => void
  startCheckIn?: boolean
  onCheckInStarted?: () => void
}) {
  const plannerDrafts = useRef<PlannerDraftCache>({ messages: {}, checkIns: {} })
  const [aiConsent, setAiConsent] = useAiConsent()
  const [surveyKey, setSurveyKey] = useState(0)
  const [editing, setEditing] = useState(!state.profile && !state.profileDraft)
  const [slots, setSlots] = useState(state.settings.slots)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const shownProfile = state.profileDraft ?? state.profile
  const blocked = state.blockedTimes ?? []
  const busyEvents = events.map(({ date, startTime, endTime }) => ({ date, startTime, endTime }))
  const savedSlots = JSON.stringify(state.settings.slots)
  const slotsDirty = JSON.stringify(slots) !== savedSlots
  useEffect(() => { setSlots(JSON.parse(savedSlots)) }, [savedSlots])

  async function run(action: () => Promise<ExecutionState>, message: string | ((next: ExecutionState) => string)) {
    if (busy) return false
    setBusy(true); setError(''); setNotice('')
    try { const next = await action(); onChange(next); setNotice(typeof message === 'string' ? message : message(next)); return true }
    catch (caught) {
      setError(caught instanceof Error ? caught.message : '요청에 실패했습니다.')
      // A generation may finish server-side after a client disconnect. Recover the actual DB state.
      try { const fresh = await executionApi(); onChange(fresh); setSlots(fresh.settings.slots) } catch { /* retain visible input */ }
      return false
    } finally { setBusy(false) }
  }

  async function generatePlan(goal: string, startDate: string, project: Project | null, consent: boolean) {
    return run(async () => {
      let current = state
      if (slotsDirty) current = await executionApi('/settings', { revision: current.revision, settings: { slots, view: current.settings.view } }, 'PUT')
      return executionApi('/plan', {
        revision: current.revision, goal, startDate, consent, memories, project: projectContext(project ?? undefined), merge: true, events: busyEvents,
        existingTasks: existingTasksFor(milestones, project ? [project.id] : []),
      })
    }, '계획 초안을 만들었습니다. 검토 후 확정하면 캘린더에도 표시됩니다.')
  }

  /** Say which open tasks the server moved out of time that is no longer free. */
  function withRelocation(base: string) {
    return (next: ExecutionState) => {
      const moved = next.relocated?.moved.length ?? 0
      const unplaced = next.relocated?.unplaced.length ?? 0
      return [base, moved > 0 && `겹친 작업 ${moved}개를 빈 시간으로 옮겼어요.`,
        unplaced > 0 && `${unplaced}개는 이번 주 남은 시간에 들어가지 않아 ‘배치하지 못한 작업’에 두었어요.`].filter(Boolean).join(' ')
    }
  }

  // Hours taken out for every project, then (when asked) this project's open work planned again.
  async function adjustWeek(blocked: Array<Omit<BlockedTime, 'id'>>, goal: string | null, startDate: string, project: Project | null, consent: boolean) {
    return run(async () => {
      let current = state
      if (blocked.length) current = await executionApi('/blocked-times', { revision: current.revision, items: [...(current.blockedTimes ?? []), ...blocked], events: busyEvents }, 'PUT')
      if (!goal) return current
      const next = await executionApi('/plan', {
        revision: current.revision, goal, startDate, consent, memories, project: projectContext(project ?? undefined), merge: true, events: busyEvents,
        existingTasks: existingTasksFor(milestones, project ? [project.id] : []),
      })
      return { ...next, relocated: current.relocated }
    }, withRelocation(goal ? '계획 조정 초안을 만들었어요. 검토 후 확정해 주세요.' : '그 시간을 비웠어요.'))
  }

  async function closeProject(project: Project, outcome: ClosedProject['outcome']) {
    const ok = await run(() => executionApi(`/projects/${encodeURIComponent(project.id)}/close`, {
      revision: state.revision, project: projectContext(project), outcome,
    }), next => {
      const carried = next.closedProjects?.[project.id]?.carried ?? []
      return `‘${project.title}’ 프로젝트를 끝냈어요. ` + (carried.length
        ? `기본 프로필에 반영: ${carried.map(c => `${c.label} ${c.to}`).join(', ')}.`
        : '기본 프로필은 그대로예요.')
    })
    if (ok) onProjectStatus?.(project.id, outcome === 'completed' ? 'completed' : 'paused')
    return ok
  }

  async function reopenProject(project: Project) {
    const ok = await run(() => executionApi(`/projects/${encodeURIComponent(project.id)}/reopen`, { revision: state.revision }),
      `‘${project.title}’ 프로젝트를 다시 열었어요. 대화로 이어서 계획해 주세요.`)
    if (ok) onProjectStatus?.(project.id, 'active')
    return ok
  }

  async function approveProposal(proposalId: string, replanConsent: boolean) {
    const plan = state.plan
    return run(() => approveProposalAndReplan(state, proposalId, {
      goal: plan?.goal ?? '',
      startDate: plan?.startDate ?? dateKey(new Date()),
      consent: replanConsent,
      memories,
      project: plan?.project ?? null,
      events: busyEvents,
      existingTasks: existingTasksFor(milestones, planProjectIds(plan)),
    }), approvalMessage(state.profileUpdateProposals?.find(p => p.id === proposalId)))
  }

  function approvalMessage(proposal: ProfileUpdateProposal | undefined) {
    const title = proposal?.projectId ? projects.find(p => p.id === proposal.projectId)?.title ?? '해당 프로젝트' : null
    if (!replansCurrentPlan(state, proposal)) {
      return title ? `${title} 설정에 변경을 적용했습니다. 지금 계획은 그대로 두고 ${title}의 다음 계획부터 반영됩니다.` : '프로필 변경을 승인했습니다.'
    }
    return `${title ? `${title} 설정에` : '프로필에'} 변경을 적용하고 재계획 초안을 만들었습니다. 검토 후 확정해 주세요.`
  }

  /** Name what changed: the shared profile means the whole week, a project's settings only that project. */
  function staleNotice(plan: ExecutionPlan) {
    if (state.profile?.id !== plan.profileId) return '이 계획을 만든 뒤 기본 프로필이 바뀌었습니다. 새 프로필로 적용하려면 다시 계획해 주세요.'
    const names = staleProjectIds(state, plan).map(id => `‘${projects.find(p => p.id === id)?.title ?? (id ? '삭제된 프로젝트' : '자유 계획')}’`)
    return `${names.join(', ')} 설정이 바뀌었습니다. 그 프로젝트 대화에서 다시 계획하면 반영돼요. 다른 프로젝트 작업은 그대로예요.`
  }

  function removeTask(plan: ExecutionPlan, task: ExecutionPlan['entries'][number]) {
    if (!window.confirm(`‘${task.title}’ 일정을 이번 주 계획에서 삭제할까요?\n삭제하면 되돌릴 수 없어요. 이미 남긴 실행 기록은 그대로 둬요.`)) return
    void run(() => executionApi('/task/remove', { revision: state.revision, planId: plan.id, taskId: task.id }), `‘${task.title}’ 일정을 삭제했어요.`)
  }

  function planCard(plan: ExecutionPlan, draft: boolean) {
    const owners = draftProjectIds(plan)
    const ownerNames = owners.map(id => ({ id, title: projects.find(p => p.id === id)?.title ?? plan.projects?.find(p => p.id === id)?.title ?? (plan.project?.id === id ? plan.project.title : id) }))
    const projectTitle = (id?: string | null) => id ? (projects.find(p => p.id === id)?.title ?? plan.projects?.find(p => p.id === id)?.title ?? plan.project?.title) : undefined
    const timed = (plan.scheduleStyle ?? state.profile?.planningPreferences.scheduleStyle) !== 'flexible_queue' && state.settings.view === 'timeline'
    const tasks = plan.entries.filter(e => e.kind === 'task')
    const dates = [...new Set(tasks.map(e => e.start.slice(0, 10)))].sort()
    const completed = tasks.filter(e => e.completed).length
    const percent = tasks.length ? Math.round(completed / tasks.length * 100) : 0
    const today = dateKey(new Date())
    const due = plan.project?.dueDate ?? projects.find(p => p.id === plan.projectId)?.dueDate
    const until = due && due < plan.endDate ? `${due} (프로젝트 마감)` : plan.endDate
    const dayName = (day: string) => `${Number(day.slice(5, 7))}/${Number(day.slice(8, 10))} (${'일월화수목금토'[new Date(`${day}T12:00:00`).getDay()]})`
    return <section className="execution-card week-plan" key={plan.id} id={draft ? 'plan-draft' : 'my-week'} aria-label={draft ? '주간 계획 초안' : '확정한 주간 계획'}>
      <header className="week-plan-head">
        <div>
          <h2>{draft ? '주간 계획 초안' : '이번 주 계획'}</h2>
          <p className="week-plan-period">{plan.project && `${plan.project.title} · `}{plan.startDate} ~ {until}</p>
        </div>
        {!draft && tasks.length > 0 && <div className="week-progress" aria-label={`${tasks.length}개 중 ${completed}개 완료`}>
          <span><b>{completed}</b> / {tasks.length} 완료</span>
          <span className={`meter ${percent === 100 ? 'full' : ''}`}><b style={{ width: `${percent}%` }}/></span>
        </div>}
      </header>
      {ownerNames.length > 1 && <ul className="week-plan-projects" aria-label="이 계획의 프로젝트">{ownerNames.map(o => <li key={o.id}><i className="project-dot" style={{ background: projectColor(o.id) }}/>{o.title}</li>)}</ul>}
      {plan.goal && <p className="week-plan-goal">{plan.goal}</p>}
      {!draft && planIsStale(state, plan) && <p className="execution-notice warn">{staleNotice(plan)}</p>}
      {draft && <p className="week-plan-note">확인용 초안이에요. 확정하면 캘린더에 들어가고, 그때부터 끝낸 일을 체크할 수 있어요.</p>}
      <div className="week-days">
        {dates.map(day => {
          const dayTasks = tasks.filter(e => e.start.startsWith(day))
          const done = dayTasks.filter(e => e.completed).length
          return <div key={day} className={`week-day ${day === today ? 'today' : ''} ${day < today ? 'past' : ''}`}>
            <div className="week-day-head">
              <strong>{dayName(day)}</strong>{day === today && <span className="week-today">오늘</span>}
              <span className="week-day-count">{done === dayTasks.length ? <span className="badge ok">완료</span> : <span className="badge neutral">{done}/{dayTasks.length}</span>}</span>
            </div>
            <ul className="week-tasks">{dayTasks.map(e => {
              const owner = e.projectId ?? plan.projectId
              const info = <div className="week-task-main">
                <strong>{e.title}{!draft && !e.completed && day < today && <span className="badge warn missed">못 함</span>}</strong>
                <small>{timed && <span className="week-task-time">{e.start.slice(11)}~{e.end.slice(11)}</span>}{e.minutes}분{e.doneWhen && ` · ${e.doneWhen}`}</small>
                {projectTitle(owner) && <small className="execution-task-project"><i className="project-dot" style={{ background: projectColor(owner ?? undefined) }}/>{projectTitle(owner)}</small>}
                {e.environmentSuggestion && <small className="week-task-hint">장소 제안 (선택): {e.environmentSuggestion.place} · 집중 응답 {e.environmentSuggestion.knownFocusDays}일 중 {e.environmentSuggestion.goodFocusDays}일 좋았어요.</small>}
              </div>
              return <li key={e.id} className={`week-task ${e.completed ? 'done' : ''} ${e.starter ? 'starter' : ''}`}>
                {draft ? <><span className="week-check" aria-hidden="true"/>{info}</> : <label className="week-task-label">
                  <input type="checkbox" className="sr-only" aria-label={`${e.title} 완료`} checked={e.completed} disabled={busy} onChange={event => { void run(() => executionApi('/task', { revision: state.revision, planId: plan.id, taskId: e.id, completed: event.target.checked }), event.target.checked ? '완료를 실행 기록에 남겼습니다.' : '완료 기록을 취소했습니다.') }}/>
                  <span className="week-check" aria-hidden="true">{e.completed && <Check size={14} strokeWidth={3}/>}</span>
                  {info}
                </label>}
                {!draft && <button type="button" className="week-task-delete" aria-label={`${e.title} 삭제`} title="일정 삭제" disabled={busy} onClick={() => removeTask(plan, e)}><Trash2 size={15}/></button>}
              </li>
            })}</ul>
          </div>
        })}
      </div>
      {!dates.length && <p className="week-plan-note">선택한 시간에 배치된 작업이 없어요. 가용 시간이나 목표를 조정해 주세요.</p>}
      {plan.pendingTasks.length > 0 && <details className="week-pending" open><summary>배치하지 못한 작업 {plan.pendingTasks.length}개</summary>{plan.pendingTasks.map((t, i) => <p key={i}>{projectTitle(t.projectId ?? plan.projectId) && `[${projectTitle(t.projectId ?? plan.projectId)}] `}{t.title} · {t.minutes}분<br/><small>{t.reason}</small></p>)}</details>}
      <PlanReasons reasons={plan.personalization ?? []} open/>
      <p className="week-plan-note">작업 시간은 추정치예요. 끝낸 일은 체크하면 실행 기록에 남고, 기록이 쌓이면 나에게 맞게 바꿀 점을 제안해요.</p>
      {draft && <div className="execution-actions">
        <button className="secondary-button" disabled={busy} onClick={() => { void run(() => executionApi('/plan/discard', { revision: state.revision }), '초안을 버렸습니다.') }}>초안 버리기</button>
        <button className="primary-button" disabled={busy || !tasks.length} onClick={() => { void run(() => executionApi('/plan/confirm', { revision: state.revision, planId: plan.id, events: busyEvents, project: projectContext(projects.find(p => p.id === plan.projectId)) }), '계획을 확정했습니다. 캘린더와 체크리스트가 연결되었습니다.') }}>검토 후 확정·캘린더 반영</button>
      </div>}
    </section>
  }

  const status = <div className="execution-status">{error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="execution-notice" role="status">{notice}</p>}</div>
  const needsProfile = <section className="execution-card"><h2>먼저 나에 대해 알려 주세요</h2>
    <p>짧은 설문 하나면 돼요. 답에 맞춰 작업 길이와 계획 방식을 정합니다.</p>
    <div className="execution-actions"><button className="primary-button" onClick={onOpenProfile}>설문하러 가기</button></div></section>

  if (section === 'project') {
    const project = projects.find(p => p.id === projectId)
    return <section className="execution-workspace">
      {status}
      {!state.profile ? needsProfile : !project ? <section className="execution-card"><p>이 프로젝트를 찾을 수 없어요. 왼쪽 목록에서 다시 골라 주세요.</p></section> : <>
        {!state.settings.slots.length && <p className="execution-notice warn">이번 주 계획할 시간을 아직 안 골랐어요. <button type="button" className="secondary-button" onClick={onOpenSchedule ?? onGoHome}>시간 고르기</button></p>}
        <PlannerChat state={state} busy={busy} run={run} project={project} onApplyPlan={generatePlan} onAdjust={adjustWeek} events={busyEvents}
          draftCache={plannerDrafts.current}
          onCloseProject={closeProject} onReopenProject={reopenProject} onEditProject={onEditProject ? () => onEditProject(project.id) : undefined}
          startCheckIn={startCheckIn} onCheckInStarted={onCheckInStarted}
          projectInfo={item => <ProjectSettings key={item.id} state={state} project={item} busy={busy} run={run} editable={import.meta.env.DEV}/>}>
          {state.planDraft && draftProjectIds(state.planDraft).includes(project.id) && planCard(state.planDraft, true)}
        </PlannerChat>
      </>}
    </section>
  }

  if (section === 'schedule') {
    return <section className="execution-workspace schedule-page">
      {status}
      <header className="page-head">
        <h1>이번 주 시간</h1>
        <p>AI가 이번 주 계획을 넣어도 되는 시간이에요. 매주 새로 고르고, 다음 주가 되면 비워져요.</p>
        <p className="schedule-summary">이번 주 계획할 시간 · {thisWeekLabel()} · {state.settings.slots.length ? `주 ${state.settings.slots.length}시간` : '아직 안 고름'}</p>
      </header>
      {!state.profile ? needsProfile : <section id="weekly-setup" className="execution-card">
        {blocked.length > 0 && <div className="execution-fieldset"><strong>이번 주에 비워 둔 시간</strong><ul className="fixed-list">{blocked.map(b => <li key={b.id}>{blockedLabel(b)}
          <button type="button" className="secondary-button" disabled={busy} onClick={() => { void run(() => executionApi('/blocked-times', { revision: state.revision, items: blocked.filter(x => x.id !== b.id), events: busyEvents }, 'PUT'), '그 시간을 다시 계획에 쓸 수 있습니다. 비어 있던 작업은 다음에 계획할 때 들어갑니다.') }}>되돌리기</button></li>)}</ul></div>}
        <AvailabilityGrid slots={slots} onChange={setSlots} disabled={busy}/>
        <div className="schedule-actions">
          {slotsDirty && <span>저장하지 않은 변경이 있어요</span>}
          <button className="primary-button" disabled={busy||!slotsDirty} onClick={()=>{void run(()=>executionApi('/settings',{revision:state.revision,settings:{...state.settings,slots}},'PUT'),'이번 주 계획할 시간을 저장했습니다. 프로젝트 대화에서 계획을 요청해 보세요.') }}>이번 주 시간 저장</button>
        </div>
      </section>}
    </section>
  }

  if (section === 'home') {
    const ongoing = projects.filter(p => !state.closedProjects?.[p.id])
    const week = state.plan && state.plan.endDate >= dateKey(new Date()) ? state.plan : null
    return <section className="execution-workspace">
      {status}
      {state.profile && <section className="execution-card home-projects" aria-label="진행 중인 프로젝트"><h2>진행 중인 프로젝트</h2>
        {ongoing.length ? <div className="home-project-list">{ongoing.map(p => {
          const tasks = week?.entries.filter(e => e.kind === 'task' && !e.starter && (e.projectId ?? week.projectId) === p.id) ?? []
          const checkIn = checkInLabel(checkInCounts(state, p.id))
          return <div key={p.id} className="home-project">
            <button type="button" className="home-project-open" onClick={() => onOpenProject?.(p.id)}>
              <i className="project-dot" style={{ background: projectColor(p.id) }}/>
              <span><b>{p.title}</b><small>{p.startDate} ~ {p.dueDate} · <span className={`badge ${deadlineTone(p.dueDate)}`}>{deadlineLabel(p.dueDate)}</span></small>
                {tasks.length ? <>
                  <span className={`meter ${tasks.every(t => t.completed) ? 'full' : ''}`}><b style={{ width: `${Math.round(tasks.filter(t => t.completed).length / tasks.length * 100)}%` }}/></span>
                  <small>이번 주 작업 <strong>{tasks.filter(t => t.completed).length}/{tasks.length}개</strong> 완료</small>
                </> : <small>아직 계획 없음 · 눌러서 대화로 계획하기</small>}</span>
            </button>
            {checkIn && <button type="button" className="primary-button checkin-start" onClick={() => onOpenProject?.(p.id, true)}>{checkIn}</button>}
          </div>
        })}</div> : <p>아직 프로젝트가 없어요. <button type="button" className="secondary-button" onClick={onCreateProject}>+ 새 프로젝트</button></p>}
      </section>}
      {!state.profile ? needsProfile : !state.settings.slots.length && <p className="execution-notice warn">이번 주 계획할 시간을 아직 안 골랐어요. <button type="button" className="secondary-button" onClick={onOpenSchedule}>시간 고르기</button></p>}
      {calendar}
      {state.planDraft && planCard(state.planDraft, true)}
      {state.plan && planCard(state.plan, false)}
      {state.profile && (() => {
        // Check-ins happen in each project's conversation; this is the form for typing a record by hand.
        const waiting = (state.profileUpdateProposals ?? []).filter(p => p.status === 'pending').length + Object.keys(state.recoveryDrafts ?? {}).length
        return <details className="execution-card record-card" open={waiting > 0 || undefined}>
          <summary><span>직접 기록하기</span><small>실행 결과 남기기 · 개선 제안{waiting > 0 && <b> · 확인할 것 {waiting}개</b>}</small></summary>
          <ExecutionLearning state={state} busy={busy} run={run} approveProposal={approveProposal} events={busyEvents} memories={memories} projects={projects}/>
        </details>
      })()}
    </section>
  }

  const resetProfile = () => {
    if (!window.confirm('프로필과 작성 중인 초안, 프로젝트별 설정을 초기화할까요? 가용 시간, 확정 계획, 프로젝트 대화는 유지됩니다.')) return
    void run(() => executionApi('/profile/reset', { revision: state.revision }), '프로필을 초기화했습니다. 설문을 다시 작성해 주세요.').then(ok => {
      if (ok) { setEditing(true); setSurveyKey(key => key + 1) }
    })
  }
  const resetEverything = () => {
    if (!window.confirm('실행 프로필·가용 시간·주간 계획·실행 기록·변경 후보를 모두 초기화할까요? 프로젝트·일정·기억은 유지됩니다.')) return
    void run(() => executionApi('/reset', { revision: state.revision }), '실행 프로필과 계획을 초기화했습니다.').then(ok => { if (ok) { setSlots([]); setEditing(true) } })
  }
  const prefs = shownProfile?.planningPreferences
  const answers = shownProfile ? Object.entries(shownProfile.declaredFacts ?? shownProfile.facts).filter(([key]) => !notAsked.includes(key)) : []

  return <section className="execution-workspace profile-page">
    {status}
    <header className="page-head">
      <h1>내 프로필</h1>
      <p>설문 답변과 실행 기록으로 정한, 나에게 맞는 계획 방식이에요. 모든 프로젝트의 기본값으로 쓰여요.</p>
    </header>
    {editing ? <ProfileForm key={surveyKey} initial={shownProfile?.declaredFacts ?? shownProfile?.facts} busy={busy} requestError={error} onCancel={shownProfile ? () => setEditing(false) : undefined} onGenerate={async answers => {
      const ok = await run(() => executionApi('/profile', { revision: state.revision, answers, mode: 'demo', consent: false }), '설문을 반영한 프로필 초안을 만들었습니다. 검토 후 확정해 주세요.')
      if (ok) setEditing(false)
    }}/> : shownProfile && prefs && <>
      <section className="profile-hero" aria-label="나의 실행 프로필">
        <span className="profile-hero-mark" aria-hidden="true"><UserRound size={22}/></span>
        <div className="profile-hero-main">
          <div className="profile-hero-title">
            <h2>나의 실행 프로필</h2>
            <span className={`status-badge ${shownProfile.status === 'draft' ? 'draft' : 'confirmed'}`}>{shownProfile.status === 'draft' ? '확정 전 초안' : '확정됨'}</span>
          </div>
          <p>{shownProfile.insights.summary}</p>
          <small>{shownProfile.source === 'llm' ? 'AI가 답변을 분석해 만들었어요' : '설문 답변으로 계산했어요'}</small>
        </div>
        <div className="profile-hero-actions">
          <button className="secondary-button" disabled={busy} onClick={() => setEditing(true)}>설문 수정</button>
          {state.profileDraft && <button type="button" className="primary-button" disabled={busy} onClick={() => { void run(() => executionApi('/profile/confirm', { revision: state.revision }), '프로필을 저장했습니다. 이제 이번 주 계획할 시간을 고르고 프로젝트를 만들어 보세요.').then(ok => { if (ok) onProfileConfirmed?.() }) }}>{busy ? '프로필 저장 중…' : '프로필 확정'}</button>}
        </div>
      </section>

      <div className="profile-stats">
        <div><span>첫 집중 구간</span><strong>{prefs.blockMinutes}분</strong><small>한 번에 이어서 하는 시간</small></div>
        <div><span>하루 계획량</span><strong>{prefs.dailyPlannedMinutes ? `${prefs.dailyPlannedMinutes}분` : '고른 시간 전부'}</strong><small>하루에 넣는 작업 합계</small></div>
        <div><span>집중이 잘 되는 시간대</span><strong>{focusTimeText(shownProfile).value}</strong><small>{focusTimeText(shownProfile).source}</small></div>
        <div><span>계획 방식</span><strong>{prefs.scheduleStyle === 'time_blocks' ? '시간 지정형' : '작업량 지정형'}</strong><small>{prefs.scheduleStyle === 'time_blocks' ? '예: 18:30~19:00 공부' : '예: A 1시간, B 2시간'}</small></div>
      </div>
      {Object.keys(state.projectProfiles ?? {}).length > 0 && <p className="profile-note">프로젝트마다 다르게 정했거나 기록으로 배운 값은 그 프로젝트 대화의 설정에서 보여요.</p>}

      {shownProfile.status === 'confirmed' && onGoHome && <section className="profile-next">
        <div><strong>프로필이 준비됐어요</strong><p>이번 주 계획할 시간을 고르고, 새 프로젝트를 만들어 대화로 계획을 요청해 보세요.</p></div>
        <div className="profile-next-actions">
          {onOpenSchedule && <button className="secondary-button" onClick={onOpenSchedule}>이번 주 시간 고르기</button>}
          <button className="primary-button" onClick={onGoHome}>홈으로 →</button>
        </div>
      </section>}

      <section className="execution-card profile-section" aria-label="설문 답변">
        <header className="profile-section-head"><h3>설문 답변</h3><span>{answers.length}개 항목</span></header>
        <dl className="answer-grid">{answers.map(([key, value]) => <div key={key} className="answer-item">
          <dt>{answerLabels[key] ?? key}</dt><dd>{formatAnswer(key, value) || '답하지 않음'}</dd>
        </div>)}</dl>
        <p className="profile-section-note">다르게 정리된 내용은 ‘설문 수정’에서 고친 뒤 확정해 주세요.</p>
      </section>

      {shownProfile.insights.strategies.length > 0 && <section className="execution-card profile-section" aria-label="추천 근거">
        <header className="profile-section-head"><h3>이렇게 계획하라고 추천했어요</h3><span>답변에서 나온 초기 가설</span></header>
        <ol className="strategy-list">{shownProfile.insights.strategies.map((item, i) => <li key={i}>
          <span className="strategy-num">{i + 1}</span>
          <div>
            <strong>{item.action}</strong>
            <p>{item.reason}</p>
            {item.evidence.length > 0 && <div className="evidence-chips">{item.evidence.map(k => <span key={k}>{answerLabels[k] ?? k}</span>)}</div>}
          </div>
        </li>)}</ol>
        <p className="profile-section-note">추천값은 실행해 보며 조정할 출발점이에요. 기록이 쌓이면 바꿀 점을 제안해요.</p>
      </section>}

      {shownProfile.insights.followUpQuestions.length > 0 && <section className="execution-card profile-section" aria-label="추가 질문">
        <header className="profile-section-head"><h3>더 알려 주면 좋은 것</h3><span>선택 · 건너뛰어도 괜찮아요</span></header>
        <ul className="question-list">{shownProfile.insights.followUpQuestions.map(q => <li key={q}><span aria-hidden="true">?</span>{q}</li>)}</ul>
        <p className="profile-section-note">체크인이나 프로젝트 대화에서 편하게 이야기해 주세요.</p>
      </section>}
    </>}
    {state.profile && !editing && <AboutMe revision={state.revision}/>}

    <section className="execution-card profile-section danger-zone" aria-label="데이터와 초기화">
      <header className="profile-section-head"><h3>데이터와 초기화</h3><span>계정별로 서버에 저장돼요</span></header>
      <div className="setting-row">
        <div><strong>플래너 대화의 AI 전송 동의</strong><p>{aiConsent ? '동의함 · 대화 내용이 OpenAI로 전송돼요.' : '아직 동의 안 함 · 대화를 처음 보낼 때 물어봐요.'}</p></div>
        {aiConsent && <button type="button" className="secondary-button compact" onClick={() => { setAiConsent(false); setNotice('AI 전송 동의를 철회했어요. 다음에 대화할 때 다시 물어볼게요.') }}>동의 철회</button>}
      </div>
      <div className="setting-row">
        <div><strong>프로필 초기화</strong><p>프로필과 프로젝트별 설정만 지우고 설문을 다시 해요. 계획과 대화는 남아요.</p></div>
        <button type="button" className="secondary-button compact" disabled={busy} onClick={resetProfile}>프로필 초기화하기</button>
      </div>
      <div className="setting-row">
        <div><strong>처음부터 다시 시작</strong><p>프로필·가용 시간·주간 계획·실행 기록을 모두 지워요. 프로젝트·일정·기억은 남아요.</p></div>
        <button type="button" className="secondary-button compact danger" disabled={busy} onClick={resetEverything}>프로필부터 다시 시작</button>
      </div>
    </section>
  </section>
}
