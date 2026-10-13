import { useState } from 'react'
import './execution.css'
import type { CalendarEvent, ExecutionPlan, ExecutionState, Milestone, Project, Memory } from '../../shared/types'
import { dateKey } from '../../shared/constants'
import { ExecutionLearning } from './ExecutionLearning'
import { ProfileForm } from './ProfileForm'
import { AvailabilityGrid } from './AvailabilityGrid'
import { PlanReasons } from './PlanReasons'
import { answerLabels, formatAnswer } from './profileLabels'
import { approveProposalAndReplan, downloadJson, executionApi, projectContext } from './api'

export function ExecutionView({ state, onChange, projects, milestones, events, memories = [] }: {
  state: ExecutionState; onChange: (state: ExecutionState) => void
  projects: Project[]; milestones: Milestone[]; events: CalendarEvent[]; memories?: Memory[]
}) {
  const [chatKey, setChatKey] = useState(0)
  const [editing, setEditing] = useState(!state.profile && !state.profileDraft)
  const [slots, setSlots] = useState(state.settings.slots)
  const [goal, setGoal] = useState(state.planDraft?.goal ?? state.plan?.goal ?? '')
  const [startDate, setStartDate] = useState(state.planDraft?.startDate ?? state.plan?.startDate ?? dateKey(new Date()))
  const [projectId, setProjectId] = useState(state.planDraft?.projectId ?? state.plan?.projectId ?? '')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const shownProfile = state.profileDraft ?? state.profile
  const selectedProject = projects.find(p => p.id === projectId)
  const busyEvents = events.map(({ date, startTime, endTime }) => ({ date, startTime, endTime }))
  const slotsDirty = JSON.stringify(slots) !== JSON.stringify(state.settings.slots)

  async function run(action: () => Promise<ExecutionState>, message: string) {
    if (busy) return false
    setBusy(true); setError(''); setNotice('')
    try { const next = await action(); onChange(next); setNotice(message); return true }
    catch (caught) {
      setError(caught instanceof Error ? caught.message : '요청에 실패했습니다.')
      // A generation may finish server-side after a client disconnect. Recover the actual DB state.
      try { const fresh = await executionApi(); onChange(fresh); setSlots(fresh.settings.slots) } catch { /* retain visible input */ }
      return false
    } finally { setBusy(false) }
  }

  async function generatePlan() {
    await run(async () => {
      let current = state
      if (slotsDirty) current = await executionApi('/settings', { revision: current.revision, settings: { slots, view: current.settings.view } }, 'PUT')
      return executionApi('/plan', {
        revision: current.revision, goal, startDate, consent, memories, project: projectContext(selectedProject), events: busyEvents,
        existingTasks: milestones.filter(m => m.projectId === projectId).map(({ title, startDate, dueDate, estimatedHours, status }) => ({ title, startDate, dueDate, estimatedHours, status })),
      })
    }, '주간 계획 초안을 만들었습니다. 검토 후 확정하면 캘린더에도 표시됩니다.')
  }

  async function approveProposal(proposalId: string, replanConsent: boolean) {
    const plan = state.plan
    return run(() => approveProposalAndReplan(state, proposalId, {
      goal: plan?.goal ?? goal,
      startDate: plan?.startDate ?? startDate,
      consent: replanConsent,
      memories,
      project: plan?.project ?? null,
      events: busyEvents,
      existingTasks: milestones.filter(m => m.projectId === plan?.projectId).map(
        ({ title, startDate, dueDate, estimatedHours, status }) => ({ title, startDate, dueDate, estimatedHours, status }),
      ),
    }), plan ? '프로필 변경을 적용하고 재계획 초안을 만들었습니다. 검토 후 확정해 주세요.' : '프로필 변경을 승인했습니다.')
  }

  function planCard(plan: ExecutionPlan, draft: boolean) {
    const timed = (plan.scheduleStyle ?? state.profile?.planningPreferences.scheduleStyle) !== 'flexible_queue' && state.settings.view === 'timeline'
    const entries = plan.entries.filter(e => timed || e.kind==='task')
    const dates = [...new Set(entries.map(e => e.start.slice(0,10)))]
    const completed = plan.entries.filter(e => e.kind==='task' && e.completed).length
    return <section className="execution-card" key={plan.id} aria-label={draft?'주간 계획 초안':'확정한 주간 계획'}>
      <p className="section-kicker">{draft?'REVIEW DRAFT':'MY WEEK'}</p><h2>{draft?'주간 계획 초안':'확정한 주간 계획'}</h2>
      <p>{plan.goal}</p><p className="execution-help">{plan.startDate} ~ {plan.endDate} · 한국 시간{!draft && ` · ${completed}개 완료`}</p>
      {!draft && state.profile?.id!==plan.profileId && <p className="execution-help">이 계획은 이전 프로필로 만들었습니다. 새 프로필로 적용하려면 다시 생성해 주세요.</p>}
      <PlanReasons reasons={plan.personalization ?? []} open={draft}/>
      {dates.map(day => <div key={day}><h3>{day} · {new Intl.DateTimeFormat('ko-KR',{ weekday:'long' }).format(new Date(`${day}T12:00:00`))}</h3>
        {entries.filter(e => e.start.startsWith(day)).map(e => e.kind==='break'?<div className="execution-break" key={e.id}>{e.start.slice(11)} ~ {e.end.slice(11)} · 휴식</div>:
          <label className={`execution-task ${e.completed?'done':''} ${e.starter?'starter':''}`} key={e.id}>
            <input aria-label={`${e.title} 완료`} type="checkbox" checked={e.completed} disabled={draft||busy} onChange={event => { void run(() => executionApi('/task',{ revision:state.revision,planId:plan.id,taskId:e.id,completed:event.target.checked }),'완료 상태를 저장했습니다.') }} />
            <span>{timed && <b className="execution-task-time">{e.start.slice(11)} ~ {e.end.slice(11)}</b>}<strong>{e.title}</strong><small>{e.doneWhen} · {e.minutes}분</small></span>
          </label>)}
      </div>)}
      {!dates.length && <p>선택한 시간에 배치된 작업이 없습니다. 가용 시간이나 목표를 조정해 주세요.</p>}
      {plan.pendingTasks.length>0 && <details open><summary>배치하지 못한 작업 {plan.pendingTasks.length}개</summary>{plan.pendingTasks.map((t,i) => <p className="execution-help" key={i}>{t.title} · {t.minutes}분<br/>{t.reason}</p>)}</details>}
      <p className="execution-help">작업 시간은 추정치입니다. 선택한 시간과 기존 일정을 기준으로 배치하며 남는 시간은 여유분입니다. 전체 목표의 완료를 보장하지 않습니다.</p>
      <div className="execution-actions">
        <button className="secondary-button" onClick={() => downloadJson(plan,'replan-week.json')}>계획 JSON 다운로드</button>
        {draft && <><button className="secondary-button" disabled={busy} onClick={() => { void run(() => executionApi('/plan/discard',{revision:state.revision}),'초안을 버렸습니다.') }}>초안 버리기</button>
          <button className="primary-button" disabled={busy || !plan.entries.some(e=>e.kind==='task')} onClick={() => { void run(() => executionApi('/plan/confirm',{revision:state.revision,planId:plan.id,events:busyEvents,project:projectContext(projects.find(p=>p.id===plan.projectId))}),'계획을 확정했습니다. 캘린더와 체크리스트가 연결되었습니다.') }}>검토 후 확정·캘린더 반영</button></>}
      </div>
    </section>
  }

  return <section className="execution-workspace">
    <header className="ai-planning-intro"><div><p className="eyebrow">PERSONAL EXECUTION PLAN</p><h1>나에게 맞는 <em>실행 계획</em>.</h1><p>나의 리듬을 파악하고, 가능한 시간 안에 무엇을 할지 구체적으로 정해요.</p></div><span className="ai-draft-badge">{state.model}</span></header>
    <div className="execution-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => {
      if (!window.confirm('프로필과 대화 기록, 작성 중인 초안을 초기화할까요? 가용 시간과 확정 계획은 유지됩니다.')) return
      void run(() => executionApi('/profile/reset', { revision: state.revision }), '프로필을 초기화했습니다. 설문을 다시 작성해 주세요.').then(ok => {
        if (ok) { setEditing(true); setChatKey(key => key + 1); setConsent(false) }
      })
    }}>프로필 초기화하기</button></div>
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="execution-notice" role="status">{notice}</p>}
    {busy && <p role="status">요청을 처리하고 있습니다. 잠시 기다려 주세요.</p>}
    {editing ? <ProfileForm key={chatKey} initial={shownProfile?.declaredFacts ?? shownProfile?.facts} busy={busy} requestError={error} onCancel={shownProfile ? () => setEditing(false) : undefined} onGenerate={async answers => {
      const ok = await run(() => executionApi('/profile', { revision: state.revision, answers, mode: 'demo', consent: false }), '설문을 반영한 프로필 초안을 만들었어. 검토 후 확정해 줘.')
      if (ok) setEditing(false)
    }}/> : shownProfile &&
      <section className="execution-card"><p className="section-kicker">MY PROFILE · {shownProfile.status==='draft'?'확정 전 초안':'확정됨'}</p><h2>나의 실행 프로필</h2><p className="execution-help">{shownProfile.source==='llm'?'LLM 분석':'답변에서 계산한 계획 선호'}</p><p>{shownProfile.insights.summary}</p>
        <div className="execution-metrics"><div><strong>{shownProfile.planningPreferences.blockMinutes}분</strong><span>첫 집중 구간</span></div><div><strong>{shownProfile.planningPreferences.bufferPercent}%</strong><span>계획의 여유분</span></div></div>
        <p><strong>계획 방식: </strong>{shownProfile.planningPreferences.scheduleStyle === 'time_blocks' ? '시간 지정형 · 18:30~19:00' : '작업량 지정형 · A 1시간, B 2시간'}</p>
        <details open={shownProfile.status === 'draft'}><summary>설문 답변 확인</summary>{Object.entries(shownProfile.declaredFacts ?? shownProfile.facts).filter(([key]) => key !== 'dailyMinutes').map(([key,value]) => <p key={key}><strong>{answerLabels[key] ?? key}: </strong>{formatAnswer(key, value)}</p>)}<p className="execution-help">다르게 정리된 내용은 ‘설문 수정’에서 고친 뒤 확정해 주세요.</p></details>
        <details><summary>추천 근거와 추가 질문</summary>{shownProfile.insights.strategies.map((s,i)=><div key={i}><h3>{s.action}</h3><p>{s.reason}</p><small>답변 근거: {s.evidence.map(k=>answerLabels[k]??k).join(', ')}</small></div>)}{shownProfile.insights.followUpQuestions.map(q=><p key={q}>{q}</p>)}<p className="execution-help">선택한 답변은 ‘설문 수정’에서 바꿀 수 있어요. 추천값은 실행 후 조정할 초기 가설입니다.</p></details>
        <div className="execution-actions"><button className="secondary-button" disabled={busy} onClick={()=>{setEditing(true)}}>설문 수정</button><button className="secondary-button" onClick={()=>downloadJson(shownProfile,'replan-profile.json')}>프로필 JSON 다운로드</button>{state.profileDraft && <button type="button" className="primary-button" disabled={busy} onClick={()=>{void run(()=>executionApi('/profile/confirm',{revision:state.revision}),'프로필을 저장했어. 아래에서 계획할 시간을 고르고 이번 주 목표를 알려 줘.') }}>{busy?'프로필 저장 중…':'프로필 확정'}</button>}</div>
        {error && <p className="form-error" role="alert">{error}</p>}
        {notice && <p className="execution-notice" role="status">{notice}</p>}
        {shownProfile.status==='confirmed' && <div className="execution-next"><strong>프로필이 DB에 저장되었습니다.</strong><p>프로필 설정이 끝났어. 아래에서 계획할 시간을 고르고 이번 주 목표를 알려 줘.</p><a className="primary-button" href="#weekly-goal">이번 주 목표 입력으로 이동 →</a></div>}
      </section>}
    {state.profile && !editing && <>
      <details id="weekly-setup" className="execution-card" open={slots.length === 0 ? true : undefined}><summary>계획할 시간 · 주 {slots.length}시간</summary>
        <p className="execution-help">하루 작업량은 계획의 분량이고, 여기서는 실제로 배치할 요일과 시간을 골라 줘. 저장한 시간은 다음에도 그대로 사용할게. 고정 일정과 겹치는 시간은 선택에서 빼 줘.</p><AvailabilityGrid slots={slots} onChange={setSlots} disabled={busy}/>
        <button className="secondary-button" disabled={busy||!slotsDirty} onClick={()=>{void run(()=>executionApi('/settings',{revision:state.revision,settings:{...state.settings,slots}},'PUT'),'계획할 시간을 저장했어.') }}>시간 변경 저장</button>
      </details>
      <form id="weekly-goal" className="execution-card" onSubmit={e=>{e.preventDefault();void generatePlan()}}><fieldset className="execution-fieldset" disabled={busy}><h2>이번 주에 무엇을 할까요?</h2>
        <label className="execution-label">연결할 프로젝트<select value={projectId} onChange={e=>setProjectId(e.target.value)}><option value="">자유 목표 · 프로젝트 없이</option>{projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label>
        <label className="execution-label">목표와 할 일<textarea required maxLength={2000} value={goal} onChange={e=>setGoal(e.target.value)} placeholder="예: 금요일까지 전공 3장 연습문제 10개, 주말까지 포트폴리오 소개 페이지 완성. 전공 공부를 먼저 하고 싶어요." /></label>
        <label className="execution-label">계획 시작일<input type="date" required value={startDate} onChange={e=>setStartDate(e.target.value)}/></label>
        <p className="execution-help">시작일부터 7일 · 한국 시간. 지난 시간과 기존 캘린더 일정은 제외합니다. 연결한 프로젝트가 있으면 해당 기간 안에서만 배치합니다.</p>
        <label className="execution-inline"><input type="checkbox" required checked={consent} onChange={e=>setConsent(e.target.checked)}/>목표·프로필·기억·가용 시간·프로젝트와 기존 할 일을 OpenAI에 전송하는 데 동의합니다.</label>
        <p className="execution-help">선택한 가용 시간과 생성한 초안은 DB에 저장됩니다. 확정 전에는 기존 계획과 캘린더를 바꾸지 않습니다. 확정하면 이전 주간 계획을 대체합니다.</p>
        <button className="primary-button" type="submit" disabled={!slots.length||!state.llmAvailable}>{busy?'계획 생성 중…':'주간 계획 초안 만들기'}</button>{!state.llmAvailable&&<p className="execution-help">서버 API 키를 설정하면 LLM 계획을 만들 수 있습니다.</p>}
      </fieldset></form>
    </>}
    {state.planDraft && !editing && planCard(state.planDraft,true)}
    {state.plan && !editing && planCard(state.plan,false)}
    <ExecutionLearning state={state} busy={busy} run={run} approveProposal={approveProposal} events={busyEvents} memories={memories}/>
    <details className="execution-card"><summary>저장 및 초기화</summary><p className="execution-help">프로필·가용 시간·주간 계획·완료 상태는 SQLite DB에 저장됩니다. 기존 프로젝트·수동 일정·기억은 기존 브라우저 저장 방식을 유지합니다.</p><button className="secondary-button" disabled={busy} onClick={()=>{
      if(!window.confirm('실행 프로필·가용 시간·주간 계획·실행 기록·변경 후보를 모두 초기화할까요? 기존 프로젝트·수동 일정·기억은 유지됩니다.'))return
      void run(()=>executionApi('/reset',{revision:state.revision}),'실행 프로필과 계획을 초기화했습니다.').then(ok=>{if(ok){setSlots([]);setEditing(true);setGoal('');setConsent(false)}})
    }}>프로필부터 다시 시작</button></details>
  </section>
}
