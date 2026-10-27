import { useEffect, useRef, useState, type ReactNode } from 'react'
import './execution.css'
import type { BlockedTime, CalendarEvent, ClosedProject, ExecutionPlan, ExecutionState, Milestone, Project, Memory, ProfileUpdateProposal } from '../../shared/types'
import { dateKey } from '../../shared/constants'
import { ExecutionLearning } from './ExecutionLearning'
import { ProfileForm } from './ProfileForm'
import { PlannerChat, type PlannerDraftCache } from './PlannerChat'
import { checkInTasks } from './CheckIn'
import { AboutMe } from './AboutMe'
import { AvailabilityGrid, blockedLabel } from './AvailabilityGrid'
import { PlanReasons } from './PlanReasons'
import { ProjectSettings } from './ProjectSettings'
import { answerLabels, focusTimeText, formatAnswer, notAsked } from './profileLabels'
import { approveProposalAndReplan, downloadJson, executionApi, existingTasksFor, planIsStale, planProjectIds, projectContext, replansCurrentPlan, staleProjectIds } from './api'
import { projectColor } from '../../shared/projectColors'

/** What a screen shows: the home week, one project's conversation, or the user's profile. */
export type ExecutionSection = 'home' | 'project' | 'profile'

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
  onProjectStatus, onProfileConfirmed, onGoHome, onOpenProfile, onOpenProject, onCreateProject, startCheckIn, onCheckInStarted }: {
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
  /** Open a project; ``checkIn`` opens its check-in right away. */
  onOpenProject?: (projectId: string, checkIn?: boolean) => void
  onCreateProject?: () => void
  startCheckIn?: boolean
  onCheckInStarted?: () => void
}) {
  const plannerDrafts = useRef<PlannerDraftCache>({ messages: {}, checkIns: {} })
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

  function planCard(plan: ExecutionPlan, draft: boolean) {
    const owners = draftProjectIds(plan)
    const ownerNames = owners.map(id => projects.find(p => p.id === id)?.title ?? plan.projects?.find(p => p.id === id)?.title ?? (plan.project?.id === id ? plan.project.title : id)).filter(Boolean)
    const projectTitle = (id?: string | null) => id ? (projects.find(p => p.id === id)?.title ?? plan.projects?.find(p => p.id === id)?.title ?? plan.project?.title) : undefined
    const timed = (plan.scheduleStyle ?? state.profile?.planningPreferences.scheduleStyle) !== 'flexible_queue' && state.settings.view === 'timeline'
    const entries = plan.entries.filter(e => timed || e.kind==='task')
    const dates = [...new Set(entries.map(e => e.start.slice(0,10)))]
    const completed = plan.entries.filter(e => e.kind==='task' && e.completed).length
    // A one-project plan ends at that project's deadline even though the planning week runs on.
    const due = plan.project?.dueDate ?? projects.find(p => p.id === plan.projectId)?.dueDate
    const until = due && due < plan.endDate ? `${due} (프로젝트 마감)` : plan.endDate
    return <section className="execution-card" key={plan.id} id={draft ? 'plan-draft' : 'my-week'} aria-label={draft?'주간 계획 초안':'확정한 주간 계획'}>
      <p className="section-kicker">{draft?'REVIEW DRAFT':'MY WEEK'}</p><h2>{draft?'주간 계획 초안':'확정한 주간 계획'}</h2>
      {ownerNames.length > 0 && <p><strong>{ownerNames.length > 1 ? '여러 프로젝트 공동 계획: ' : '프로젝트: '}</strong>{ownerNames.join(' · ')}</p>}
      <p>{plan.goal}</p><p className="execution-help">{plan.project && `${plan.project.title} · `}{plan.startDate} ~ {until} · 한국 시간{!draft && ` · ${completed}개 완료`}</p>
      {!draft && planIsStale(state, plan) && <p className="execution-help">{staleNotice(plan)}</p>}
      <PlanReasons reasons={plan.personalization ?? []} open={draft}/>
      <p className="execution-help">{draft ? '확인용 초안이에요. 확정하면 캘린더에 들어가고, 그때부터 끝낸 작업을 체크해 완료로 기록할 수 있어요.' : '끝낸 작업은 체크하면 실행 기록에 남아요. 기록이 쌓이면 나에게 맞게 바꿀 점을 제안해요.'}</p>
      {dates.map(day => <div key={day}><h3>{day} · {new Intl.DateTimeFormat('ko-KR',{ weekday:'long' }).format(new Date(`${day}T12:00:00`))}</h3>
        {entries.filter(e => e.start.startsWith(day)).map(e => {
          if (e.kind === 'break') return <div className="execution-break" key={e.id}>{e.start.slice(11)} ~ {e.end.slice(11)} · 휴식</div>
          const body = <span>{timed && <b className="execution-task-time">{e.start.slice(11)} ~ {e.end.slice(11)}</b>}{projectTitle(e.projectId ?? plan.projectId) && <small className="execution-task-project"><i className="project-dot" style={{ background: projectColor(e.projectId ?? plan.projectId ?? undefined) }}/>{projectTitle(e.projectId ?? plan.projectId)}</small>}<strong>{e.title}</strong><small>{e.doneWhen} · {e.minutes}분</small>{e.environmentSuggestion && <small className="execution-help">장소 제안 (선택): {e.environmentSuggestion.place} · 집중 응답 {e.environmentSuggestion.knownFocusDays}일 중 {e.environmentSuggestion.goodFocusDays}일 좋았어요. 다른 장소를 골라도 괜찮아요.</small>}</span>
          // Before confirmation there is nothing to tick off yet: the draft is only reviewed.
          if (draft) return <div className={`execution-task ${e.starter?'starter':''}`} key={e.id}>{body}</div>
          return <label className={`execution-task ${e.completed?'done':''} ${e.starter?'starter':''}`} key={e.id}>
            <input aria-label={`${e.title} 완료`} type="checkbox" checked={e.completed} disabled={busy} onChange={event => { void run(() => executionApi('/task',{ revision:state.revision,planId:plan.id,taskId:e.id,completed:event.target.checked }),event.target.checked?'완료를 실행 기록에 남겼습니다.':'완료 기록을 취소했습니다.') }} />
            {body}
          </label>
        })}
      </div>)}
      {!dates.length && <p>선택한 시간에 배치된 작업이 없습니다. 가용 시간이나 목표를 조정해 주세요.</p>}
      {plan.pendingTasks.length>0 && <details open><summary>배치하지 못한 작업 {plan.pendingTasks.length}개</summary>{plan.pendingTasks.map((t,i) => <p className="execution-help" key={i}>{projectTitle(t.projectId ?? plan.projectId) && `[${projectTitle(t.projectId ?? plan.projectId)}] `}{t.title} · {t.minutes}분<br/>{t.reason}</p>)}</details>}
      <p className="execution-help">작업 시간은 추정치입니다. 고른 시간을 그날 안에서 앞에서부터 채우고, 목표에 필요한 일이 다 들어가면 남은 시간은 비워 둡니다. 전체 목표의 완료를 보장하지 않습니다.</p>
      <div className="execution-actions">
        <button className="secondary-button" onClick={() => downloadJson(plan,'replan-week.json')}>계획 JSON 다운로드</button>
        {draft && <><button className="secondary-button" disabled={busy} onClick={() => { void run(() => executionApi('/plan/discard',{revision:state.revision}),'초안을 버렸습니다.') }}>초안 버리기</button>
          <button className="primary-button" disabled={busy || !plan.entries.some(e=>e.kind==='task')} onClick={() => { void run(() => executionApi('/plan/confirm',{revision:state.revision,planId:plan.id,events:busyEvents,project:projectContext(projects.find(p=>p.id===plan.projectId))}),'계획을 확정했습니다. 캘린더와 체크리스트가 연결되었습니다.') }}>검토 후 확정·캘린더 반영</button></>}
      </div>
    </section>
  }

  const status = <div className="execution-status">{error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="execution-notice" role="status">{notice}</p>}
    {busy && <p role="status">요청을 처리하고 있습니다. 잠시 기다려 주세요.</p>}</div>
  const needsProfile = <section className="execution-card"><h2>먼저 나에 대해 알려 주세요</h2>
    <p>짧은 설문 하나면 돼요. 답에 맞춰 작업 길이와 계획 방식을 정합니다.</p>
    <div className="execution-actions"><button className="primary-button" onClick={onOpenProfile}>설문하러 가기</button></div></section>

  if (section === 'project') {
    const project = projects.find(p => p.id === projectId)
    return <section className="execution-workspace">
      {status}
      {!state.profile ? needsProfile : !project ? <section className="execution-card"><p>이 프로젝트를 찾을 수 없어요. 왼쪽 목록에서 다시 골라 주세요.</p></section> : <>
        {!state.settings.slots.length && <p className="execution-notice">이번 주 계획할 시간을 아직 안 골랐어요. <button type="button" className="secondary-button" onClick={onGoHome}>홈에서 고르기</button></p>}
        <PlannerChat state={state} busy={busy} run={run} project={project} onApplyPlan={generatePlan} onAdjust={adjustWeek} events={busyEvents}
          draftCache={plannerDrafts.current}
          onCloseProject={closeProject} onReopenProject={reopenProject} startCheckIn={startCheckIn} onCheckInStarted={onCheckInStarted}
          projectInfo={item => <ProjectSettings key={item.id} state={state} project={item} busy={busy} run={run} editable={import.meta.env.DEV}/>}/>
        {state.planDraft && draftProjectIds(state.planDraft).includes(project.id) && planCard(state.planDraft, true)}
      </>}
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
          const due = checkInTasks(state, p.id).due.length
          return <div key={p.id} className="home-project">
            <button type="button" className="home-project-open" onClick={() => onOpenProject?.(p.id)}>
              <i className="project-dot" style={{ background: projectColor(p.id) }}/>
              <span><b>{p.title}</b><small>{p.startDate} ~ {p.dueDate} · {deadlineLabel(p.dueDate)}</small>
                <small>{tasks.length ? `이번 주 작업 ${tasks.filter(t => t.completed).length}/${tasks.length}개 완료` : '아직 계획 없음 · 눌러서 대화로 계획하기'}</small></span>
            </button>
            {due > 0 && <button type="button" className="primary-button checkin-start" onClick={() => onOpenProject?.(p.id, true)}>오늘 체크인 · {due}개</button>}
          </div>
        })}</div> : <p>아직 프로젝트가 없어요. <button type="button" className="secondary-button" onClick={onCreateProject}>+ 새 프로젝트</button></p>}
      </section>}
      {!state.profile ? needsProfile : <details id="weekly-setup" className="execution-card" open={slots.length === 0 || slotsDirty ? true : undefined}>
        <summary>이번 주 계획할 시간 · {thisWeekLabel()} · {state.settings.slots.length ? `주 ${state.settings.slots.length}시간` : '아직 안 고름'}</summary>
        <p className="execution-help">AI가 이번 주 계획을 넣어도 되는 시간이에요. 매주 새로 고르고, 다음 주가 되면 비워져요.</p>
        {blocked.length > 0 && <div className="execution-fieldset"><strong>이번 주에 비워 둔 시간</strong><ul className="fixed-list">{blocked.map(b => <li key={b.id}>{blockedLabel(b)}
          <button type="button" className="secondary-button" disabled={busy} onClick={() => { void run(() => executionApi('/blocked-times', { revision: state.revision, items: blocked.filter(x => x.id !== b.id), events: busyEvents }, 'PUT'), '그 시간을 다시 계획에 쓸 수 있습니다. 비어 있던 작업은 다음에 계획할 때 들어갑니다.') }}>되돌리기</button></li>)}</ul></div>}
        <AvailabilityGrid slots={slots} onChange={setSlots} disabled={busy}/>
        <button className="secondary-button" disabled={busy||!slotsDirty} onClick={()=>{void run(()=>executionApi('/settings',{revision:state.revision,settings:{...state.settings,slots}},'PUT'),'이번 주 계획할 시간을 저장했습니다. 프로젝트 대화에서 계획을 요청해 보세요.') }}>이번 주 시간 저장</button>
      </details>}
      {calendar}
      {state.planDraft && planCard(state.planDraft, true)}
      {state.plan && planCard(state.plan, false)}
      {state.profile && (() => {
        // Check-ins happen in each project's conversation; this is the form for typing a record by hand.
        const waiting = (state.profileUpdateProposals ?? []).filter(p => p.status === 'pending').length + Object.keys(state.recoveryDrafts ?? {}).length
        return <details className="execution-card" open={waiting > 0 || undefined}>
          <summary>직접 기록하기 · 개선 제안{waiting > 0 && ` · 확인할 것 ${waiting}개`}</summary>
          <ExecutionLearning state={state} busy={busy} run={run} approveProposal={approveProposal} events={busyEvents} memories={memories} projects={projects}/>
        </details>
      })()}
    </section>
  }

  return <section className="execution-workspace">
    <header className="ai-planning-intro"><div><p className="eyebrow">PERSONAL EXECUTION PLAN</p><h1>나에게 맞는 <em>실행 계획</em>.</h1><p>나의 리듬을 파악하고, 가능한 시간 안에 무엇을 할지 구체적으로 정해요.</p></div><span className="ai-draft-badge">{state.model}</span></header>
    <div className="execution-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => {
      if (!window.confirm('프로필과 작성 중인 초안, 프로젝트별 설정을 초기화할까요? 가용 시간, 확정 계획, 프로젝트 대화는 유지됩니다.')) return
      void run(() => executionApi('/profile/reset', { revision: state.revision }), '프로필을 초기화했습니다. 설문을 다시 작성해 주세요.').then(ok => {
        if (ok) { setEditing(true); setSurveyKey(key => key + 1) }
      })
    }}>프로필 초기화하기</button></div>
    {status}
    {editing ? <ProfileForm key={surveyKey} initial={shownProfile?.declaredFacts ?? shownProfile?.facts} busy={busy} requestError={error} onCancel={shownProfile ? () => setEditing(false) : undefined} onGenerate={async answers => {
      const ok = await run(() => executionApi('/profile', { revision: state.revision, answers, mode: 'demo', consent: false }), '설문을 반영한 프로필 초안을 만들었습니다. 검토 후 확정해 주세요.')
      if (ok) setEditing(false)
    }}/> : shownProfile &&
      <section className="execution-card"><p className="section-kicker">MY PROFILE · {shownProfile.status==='draft'?'확정 전 초안':'확정됨'}</p><h2>나의 실행 프로필</h2><p className="execution-help">{shownProfile.source==='llm'?'LLM 분석':'답변에서 계산한 계획 선호'}</p><p>{shownProfile.insights.summary}</p>
        <div className="execution-metrics"><div><strong>{shownProfile.planningPreferences.blockMinutes}분</strong><span>첫 집중 구간</span></div><div><strong>{shownProfile.planningPreferences.dailyPlannedMinutes ? `${shownProfile.planningPreferences.dailyPlannedMinutes}분` : '고른 시간 전부'}</strong><span>하루 계획량</span></div><div><strong>{focusTimeText(shownProfile).value}</strong><span>집중이 잘 되는 시간대 · {focusTimeText(shownProfile).source}</span></div></div>
        {Object.keys(state.projectProfiles ?? {}).length > 0 && <p className="execution-help">모든 프로젝트의 기본값입니다. 프로젝트마다 다르게 정했거나 기록으로 배운 값은 그 프로젝트 화면에서 보여요.</p>}
        <p><strong>계획 방식: </strong>{shownProfile.planningPreferences.scheduleStyle === 'time_blocks' ? '시간 지정형 · 18:30~19:00' : '작업량 지정형 · A 1시간, B 2시간'}</p>
        <details open={shownProfile.status === 'draft'}><summary>설문 답변 확인</summary>{Object.entries(shownProfile.declaredFacts ?? shownProfile.facts).filter(([key]) => !notAsked.includes(key)).map(([key,value]) => <p key={key}><strong>{answerLabels[key] ?? key}: </strong>{formatAnswer(key, value)}</p>)}<p className="execution-help">다르게 정리된 내용은 ‘설문 수정’에서 고친 뒤 확정해 주세요.</p></details>
        <details><summary>추천 근거와 추가 질문</summary>{shownProfile.insights.strategies.map((s,i)=><div key={i}><h3>{s.action}</h3><p>{s.reason}</p><small>답변 근거: {s.evidence.map(k=>answerLabels[k]??k).join(', ')}</small></div>)}{shownProfile.insights.followUpQuestions.map(q=><p key={q}>{q}</p>)}<p className="execution-help">선택한 답변은 ‘설문 수정’에서 바꿀 수 있어요. 추천값은 실행 후 조정할 초기 가설입니다.</p></details>
        <div className="execution-actions"><button className="secondary-button" disabled={busy} onClick={()=>{setEditing(true)}}>설문 수정</button><button className="secondary-button" onClick={()=>downloadJson(shownProfile,'replan-profile.json')}>프로필 JSON 다운로드</button>{state.profileDraft && <button type="button" className="primary-button" disabled={busy} onClick={()=>{void run(()=>executionApi('/profile/confirm',{revision:state.revision}),'프로필을 저장했습니다. 이제 이번 주 계획할 시간을 고르고 프로젝트를 만들어 보세요.').then(ok => { if (ok) onProfileConfirmed?.() }) }}>{busy?'프로필 저장 중…':'프로필 확정'}</button>}</div>
        {shownProfile.status==='confirmed' && onGoHome && <div className="execution-next"><strong>프로필이 저장되었습니다.</strong><p>홈에서 이번 주 계획할 시간을 고르고, 새 프로젝트를 만들어 대화로 계획을 요청해 보세요.</p><button className="primary-button" onClick={onGoHome}>홈으로 →</button></div>}
      </section>}
    {state.profile && !editing && <AboutMe revision={state.revision}/>}
    <details className="execution-card"><summary>저장 및 초기화</summary><p className="execution-help">프로필·가용 시간·주간 계획·완료 상태는 서버 DB에 계정별로 저장됩니다.</p><button className="secondary-button" disabled={busy} onClick={()=>{
      if(!window.confirm('실행 프로필·가용 시간·주간 계획·실행 기록·변경 후보를 모두 초기화할까요? 프로젝트·일정·기억은 유지됩니다.'))return
      void run(()=>executionApi('/reset',{revision:state.revision}),'실행 프로필과 계획을 초기화했습니다.').then(ok=>{if(ok){setSlots([]);setEditing(true)}})
    }}>프로필부터 다시 시작</button></details>
  </section>
}
