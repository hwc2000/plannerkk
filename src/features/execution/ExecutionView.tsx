import { useState } from 'react'
import './execution.css'
import type { CalendarEvent, ExecutionPlan, ExecutionState, Milestone, Project } from '../../shared/types'
import { dateKey } from '../../shared/constants'
import { ExecutionLearning } from './ExecutionLearning'
import { AvailabilityGrid } from './AvailabilityGrid'
import { answerLabels, ProfileForm } from './ProfileForm'
import { downloadJson, executionApi, projectContext } from './api'

export function ExecutionView({ state, onChange, projects, milestones, events }: {
  state: ExecutionState; onChange: (state: ExecutionState) => void
  projects: Project[]; milestones: Milestone[]; events: CalendarEvent[]
}) {
  const [editing, setEditing] = useState(!state.profile && !state.profileDraft)
  const [slots, setSlots] = useState(state.settings.slots)
  const [goal, setGoal] = useState(state.planDraft?.goal ?? state.plan?.goal ?? '')
  const [startDate, setStartDate] = useState(dateKey(new Date()))
  const [projectId, setProjectId] = useState('')
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
        revision: current.revision, goal, startDate, consent, project: projectContext(selectedProject), events: busyEvents,
        existingTasks: milestones.filter(m => m.projectId === projectId).map(({ title, startDate, dueDate, estimatedHours, status }) => ({ title, startDate, dueDate, estimatedHours, status })),
      })
    }, '주간 계획 초안을 만들었습니다. 검토 후 확정하면 캘린더에도 표시됩니다.')
  }

  function planCard(plan: ExecutionPlan, draft: boolean) {
    const entries = plan.entries.filter(e => state.settings.view==='timeline' || e.kind==='task')
    const dates = [...new Set(entries.map(e => e.start.slice(0,10)))]
    const completed = plan.entries.filter(e => e.kind==='task' && e.completed).length
    return <section className="execution-card" key={plan.id} aria-label={draft?'주간 계획 초안':'확정한 주간 계획'}>
      <p className="section-kicker">{draft?'REVIEW DRAFT':'MY WEEK'}</p><h2>{draft?'주간 계획 초안':'확정한 주간 계획'}</h2>
      <p>{plan.goal}</p><p className="execution-help">{plan.startDate} ~ {plan.endDate} · 한국 시간{!draft && ` · ${completed}개 완료`}</p>
      {!draft && state.profile?.id!==plan.profileId && <p className="execution-help">이 계획은 이전 프로필로 만들었습니다. 새 프로필로 적용하려면 다시 생성해 주세요.</p>}
      {dates.map(day => <div key={day}><h3>{day} · {new Intl.DateTimeFormat('ko-KR',{ weekday:'long' }).format(new Date(`${day}T12:00:00`))}</h3>
        {entries.filter(e => e.start.startsWith(day)).map(e => e.kind==='break'?<div className="execution-break" key={e.id}>{e.start.slice(11)} ~ {e.end.slice(11)} · 휴식</div>:
          <label className={`execution-task ${e.completed?'done':''}`} key={e.id}>
            <input aria-label={`${e.title} 완료`} type="checkbox" checked={e.completed} disabled={draft||busy} onChange={event => { void run(() => executionApi('/task',{ revision:state.revision,planId:plan.id,taskId:e.id,completed:event.target.checked }),'완료 상태를 저장했습니다.') }} />
            <span>{state.settings.view==='timeline' && <b className="execution-task-time">{e.start.slice(11)} ~ {e.end.slice(11)}</b>}<strong>{e.title}</strong><small>{e.doneWhen} · {e.minutes}분</small></span>
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
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="execution-notice" role="status">{notice}</p>}
    {busy && <p role="status">요청을 처리하고 있습니다. 잠시 기다려 주세요.</p>}
    {editing ? <ProfileForm key={shownProfile?.id??'new'} initial={shownProfile?.facts} busy={busy} llmAvailable={state.llmAvailable} requestError={error} onCancel={shownProfile?()=>setEditing(false):undefined}
      onGenerate={async (answers,mode,consent) => { if(await run(() => executionApi('/profile',{revision:state.revision,answers,mode,consent}),'프로필 초안을 만들었습니다. 확인 후 확정해 주세요.'))setEditing(false) }} /> : shownProfile &&
      <section className="execution-card"><p className="section-kicker">MY PROFILE · {shownProfile.status==='draft'?'확정 전 초안':'확정됨'}</p><h2>나의 실행 프로필</h2><p className="execution-help">{shownProfile.source==='llm'?'LLM 분석':'규칙 기반 미리보기 · LLM 미사용'}</p><p>{shownProfile.insights.summary}</p>
        <div className="execution-metrics"><div><strong>{shownProfile.planningPreferences.blockMinutes}분</strong><span>첫 집중 구간</span></div><div><strong>{shownProfile.planningPreferences.bufferPercent}%</strong><span>계획의 여유분</span></div><div><strong>{shownProfile.planningPreferences.dailyPlannedMinutes??'미정'}</strong><span>하루 작업 예산(분)</span></div></div>
        <details><summary>추천 근거와 추가 질문</summary>{shownProfile.insights.strategies.map((s,i)=><div key={i}><h3>{s.action}</h3><p>{s.reason}</p><small>답변 근거: {s.evidence.map(k=>answerLabels[k]??k).join(', ')}</small></div>)}{shownProfile.insights.followUpQuestions.map(q=><p key={q}>{q}</p>)}<p className="execution-help">추가 질문은 답변 수정의 추가 설명에 적어 주세요. 추천값은 실행 후 조정할 초기 가설입니다.</p></details>
        <div className="execution-actions"><button className="secondary-button" disabled={busy} onClick={()=>setEditing(true)}>답변 수정</button><button className="secondary-button" onClick={()=>downloadJson(shownProfile,'replan-profile.json')}>프로필 JSON 다운로드</button>{state.profileDraft && <button type="button" className="primary-button" disabled={busy} onClick={()=>{void run(()=>executionApi('/profile/confirm',{revision:state.revision}),'프로필 저장 완료. 아래에서 가용 시간을 선택하고 주간 계획을 요청해 주세요.') }}>{busy?'프로필 저장 중…':'프로필 확정'}</button>}</div>
        {error && <p className="form-error" role="alert">{error}</p>}
        {notice && <p className="execution-notice" role="status">{notice}</p>}
        {shownProfile.status==='confirmed' && <div className="execution-next"><strong>프로필이 DB에 저장되었습니다.</strong><p>다음 단계는 가용 시간 선택과 목표 입력입니다.</p><a className="primary-button" href="#weekly-setup">가용 시간·계획 입력으로 이동 →</a></div>}
      </section>}
    {state.profile && !editing && <>
      <section id="weekly-setup" className="execution-card"><h2>요일별 시간과 플래너 방식</h2><AvailabilityGrid slots={slots} onChange={setSlots} disabled={busy}/>
        <fieldset className="execution-fieldset" disabled={busy}><legend>플래너 방식 · 택 1</legend><div className="execution-options">{(['timeline','checklist'] as const).map(view=><label key={view} className="execution-option"><input type="radio" name="planner-view" checked={state.settings.view===view} onChange={()=>{void run(()=>executionApi('/settings',{revision:state.revision,settings:{...state.settings,view}},'PUT'),'플래너 방식을 저장했습니다.') }}/>{view==='timeline'?'시간 플래너':'할 일 플래너'}</label>)}</div></fieldset>
        <p className="execution-help">두 화면은 같은 작업과 완료 상태를 공유해요. 가용 시간을 변경한 뒤에는 계획을 다시 생성해야 반영됩니다.</p>
        <button className="secondary-button" disabled={busy||!slotsDirty} onClick={()=>{void run(()=>executionApi('/settings',{revision:state.revision,settings:{...state.settings,slots}},'PUT'),'가용 시간을 저장했습니다. 새 계획부터 반영됩니다.') }}>가용 시간 저장</button>
        {slotsDirty && <span className="execution-help"> 저장하지 않은 시간 선택이 있습니다.</span>}
      </section>
      <form className="execution-card" onSubmit={e=>{e.preventDefault();void generatePlan()}}><fieldset className="execution-fieldset" disabled={busy}><h2>이번 주에 무엇을 할까요?</h2>
        <label className="execution-label">연결할 프로젝트<select value={projectId} onChange={e=>setProjectId(e.target.value)}><option value="">자유 목표 · 프로젝트 없이</option>{projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label>
        <label className="execution-label">목표와 할 일<textarea required maxLength={2000} value={goal} onChange={e=>setGoal(e.target.value)} placeholder="예: 금요일까지 전공 3장 연습문제 10개, 주말까지 포트폴리오 소개 페이지 완성. 전공 공부를 먼저 하고 싶어요." /></label>
        <label className="execution-label">계획 시작일<input type="date" required value={startDate} onChange={e=>setStartDate(e.target.value)}/></label>
        <p className="execution-help">시작일부터 7일 · 한국 시간. 지난 시간과 기존 캘린더 일정은 제외합니다. 연결한 프로젝트가 있으면 해당 기간 안에서만 배치합니다.</p>
        <label className="execution-inline"><input type="checkbox" required checked={consent} onChange={e=>setConsent(e.target.checked)}/>목표·프로필·가용 시간·프로젝트와 기존 할 일을 OpenAI에 전송하는 데 동의합니다.</label>
        <p className="execution-help">선택한 가용 시간과 생성한 초안은 DB에 저장됩니다. 확정 전에는 기존 계획과 캘린더를 바꾸지 않습니다. 확정하면 이전 주간 계획을 대체합니다.</p>
        <button className="primary-button" type="submit" disabled={!slots.length||!state.llmAvailable}>{busy?'계획 생성 중…':'주간 계획 초안 만들기'}</button>{!state.llmAvailable&&<p className="execution-help">서버 API 키를 설정하면 LLM 계획을 만들 수 있습니다.</p>}
      </fieldset></form>
    </>}
    {state.planDraft && !editing && planCard(state.planDraft,true)}
    {state.plan && !editing && planCard(state.plan,false)}
    <ExecutionLearning state={state} busy={busy} run={run}/>
    <details className="execution-card"><summary>저장 및 초기화</summary><p className="execution-help">프로필·가용 시간·주간 계획·완료 상태는 SQLite DB에 저장됩니다. 기존 프로젝트·수동 일정·기억은 기존 브라우저 저장 방식을 유지합니다.</p><button className="secondary-button" disabled={busy} onClick={()=>{
      if(!window.confirm('실행 프로필·가용 시간·주간 계획·실행 기록·변경 후보를 모두 초기화할까요? 기존 프로젝트·수동 일정·기억은 유지됩니다.'))return
      void run(()=>executionApi('/reset',{revision:state.revision}),'실행 프로필과 계획을 초기화했습니다.').then(ok=>{if(ok){setSlots([]);setEditing(true);setGoal('');setConsent(false)}})
    }}>프로필부터 다시 시작</button></details>
  </section>
}
