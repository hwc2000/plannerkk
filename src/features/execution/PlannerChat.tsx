import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Plus } from 'lucide-react'
import type { ExecutionState, Project } from '../../shared/types'
import { projectColor } from '../../shared/projectColors'
import { dateKey } from '../../shared/constants'
import { executionApi, projectContext } from './api'

const days = '월화수목금토일'
const FREE = '_free'
const FREE_COLOR = '#5855d6'

/** One conversation per project, like separate chats; the weekly plan stays shared. */
export function PlannerChat({ state, busy, run, projects, onCreateProject, onApplyPlan, projectInfo }: {
  state: ExecutionState; busy: boolean
  run: (action: () => Promise<ExecutionState>, message: string) => Promise<boolean>
  projects: Project[]; onCreateProject?: () => void
  onApplyPlan: (goal: string, startDate: string, project: Project | null, consent: boolean) => Promise<boolean>
  /** What this project adapted on top of the user profile, shown under its chat header. */
  projectInfo?: (project: Project) => ReactNode
}) {
  const threads = state.plannerThreads ?? {}
  const [selected, setSelected] = useState(() => mostRecentThread(threads, projects))
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [consent, setConsent] = useState(false)
  const known = useRef(new Set(projects.map(p => p.id)))
  const end = useRef<HTMLDivElement>(null)
  const project = projects.find(p => p.id === selected) ?? null
  const key = project?.id ?? FREE
  const thread = threads[key]
  const messages = thread?.messages ?? []
  // A card is stale once anything else has changed the saved state.
  const action = thread?.action?.revision === state.revision ? thread.action : null
  const text = drafts[key] ?? ''
  const color = project ? projectColor(project.id) : FREE_COLOR
  const week = state.plan && state.plan.endDate >= dateKey(new Date()) ? state.plan : null
  const weekTasks = week?.entries.filter(e => e.kind === 'task' && (e.projectId ?? week.projectId ?? null) === (project?.id ?? null)) ?? []

  // A newly created project opens its own fresh conversation, like starting a new chat.
  useEffect(() => {
    const added = projects.find(p => !known.current.has(p.id))
    known.current = new Set(projects.map(p => p.id))
    if (added) setSelected(added.id)
  }, [projects])
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }) }, [messages.length, key])

  async function send() {
    if (!text.trim() || !consent || busy) return
    const ok = await run(() => executionApi('/chat/message', {
      revision: state.revision, text, consent, project: projectContext(project ?? undefined),
    }), '플래너가 답했어요.')
    if (ok) setDrafts(d => ({ ...d, [key]: '' }))
  }

  const threadItems = [...projects.map(p => ({ id: p.id, title: p.title, color: projectColor(p.id), sub: `${p.startDate} ~ ${p.dueDate}` })),
    { id: FREE, title: '자유 계획', color: FREE_COLOR, sub: '프로젝트 없이' }]

  return <section className="planner-workspace" id="weekly-goal" aria-label="대화형 플래너" style={{ '--thread-color': color } as CSSProperties}>
    <nav className="planner-threads" aria-label="프로젝트 대화 목록">
      <div className="planner-threads-head"><strong>프로젝트 대화</strong>
        {onCreateProject && <button type="button" className="planner-new" onClick={onCreateProject} aria-label="새 프로젝트 대화"><Plus size={15}/>새 프로젝트</button>}
      </div>
      {threadItems.map(item => {
        const last = threads[item.id]?.messages.at(-1)
        return <button type="button" key={item.id} aria-current={item.id === key ? 'true' : undefined}
          className={`planner-thread ${item.id === key ? 'active' : ''}`} style={{ '--item-color': item.color } as CSSProperties}
          onClick={() => setSelected(item.id)}>
          <i className="project-dot" style={{ background: item.color }}/>
          <span><b>{item.title}</b><small>{last ? last.content : item.sub}</small></span>
          {threads[item.id]?.action?.revision === state.revision && <em className="planner-badge" aria-label="확인할 제안 있음"/>}
        </button>
      })}
    </nav>

    <div className="planner-chat execution-card" aria-label={`${project?.title ?? '자유 계획'} 대화`}>
      <header className="planner-chat-head">
        <i className="project-dot" style={{ background: color }}/>
        <div><h2>{project?.title ?? '자유 계획'}</h2>
          <p className="execution-help">{project ? `${project.startDate} ~ ${project.dueDate}${project.goal ? ` · ${project.goal}` : ''}` : '프로젝트에 속하지 않은 할 일을 계획해요.'}</p></div>
        {messages.length > 0 && <button type="button" className="secondary-button" disabled={busy} onClick={() => {
          if (window.confirm(`‘${project?.title ?? '자유 계획'}’ 대화 기록을 지울까요? 계획과 다른 프로젝트 대화는 유지됩니다.`))
            void run(() => executionApi('/chat/reset', { revision: state.revision, projectId: project?.id ?? null }), '새 대화를 시작했어요.')
        }}>새 대화</button>}
      </header>
      {project && projectInfo?.(project)}
      {week && <p className="planner-week">이번 주 계획 {week.startDate} ~ {week.endDate} · 이 프로젝트 작업 {weekTasks.length}개 ({weekTasks.filter(t => t.completed).length}개 완료)</p>}

      <div className="profile-chat-log" role="log" aria-live="polite" aria-label="플래너 대화 기록">
        {!messages.length && <div className="profile-chat-message assistant"><small>플래너</small><p>{!state.settings.slots.length
          ? '먼저 이번 주에 계획을 넣을 수 있는 요일과 시간을 알려 주세요. 예: 평일 저녁 7시부터 9시까지 가능해요.'
          : project
            ? `‘${project.title}’에서 이번 주에 하고 싶은 일을 알려 주세요. 마감이나 우선순위도 말해 주시면 계획 초안을 준비할게요.`
            : '프로젝트와 상관없는 할 일을 알려 주세요. 언제부터 시작할지도 말해 주시면 계획 초안을 준비할게요.'}</p></div>}
        {messages.map(m => <div key={m.id} className={`profile-chat-message ${m.role}`}><small>{m.role === 'user' ? '나' : '플래너'}</small><p>{m.content}</p></div>)}
        {busy && <p role="status">플래너가 생각하고 있어요…</p>}
        <div ref={end}/>
      </div>

      {action && <div className="planner-action" aria-label="확인 카드">
        {action.kind === 'plan' ? <>
          <h3>이 내용으로 계획 초안을 만들까요?</h3>
          <p><strong>목표: </strong>{action.payload.goal}</p>
          <p><strong>기간: </strong>{action.payload.startDate}부터 7일</p>
          {week && <p className="execution-help">이번 주 계획에서 이 {project ? '프로젝트' : '자유 계획'}의 남은 작업만 바꿔요. 다른 프로젝트 작업과 완료한 작업은 그대로 둬요.</p>}
          {!state.settings.slots.length && <p className="form-error">계획할 시간이 아직 없어요. 가능한 요일과 시간을 먼저 알려 주세요.</p>}
          <button className="primary-button" disabled={busy || !consent || !state.settings.slots.length} onClick={() => { void onApplyPlan(action.payload.goal, action.payload.startDate, project, consent) }}>확인하고 계획 초안 만들기</button>
        </> : <>
          <h3>계획할 시간을 이렇게 바꿀까요?</h3>
          <p>{action.payload.slots.length ? action.payload.slots.map(s => `${days[s.day]} ${s.hour}~${s.hour + 1}시`).join(', ') : '선택한 시간 없음'}</p>
          <p className="execution-help">모든 프로젝트가 함께 쓰는 시간이에요. 기존에 저장한 시간을 모두 이 내용으로 바꿔요.</p>
          <button className="primary-button" disabled={busy} onClick={() => { void run(() => executionApi('/settings', { revision: state.revision, settings: action.payload }, 'PUT'), '계획할 시간을 저장했어요.') }}>확인하고 시간 저장</button>
        </>}
        <p className="execution-help">고칠 내용이 있으면 아래 대화로 알려 주세요.</p>
      </div>}

      <form onSubmit={e => { e.preventDefault(); void send() }}>
        <label className="execution-label">메시지<textarea maxLength={2000} value={text} disabled={busy} onChange={e => setDrafts(d => ({ ...d, [key]: e.target.value }))}
          placeholder={project ? `예: ${project.title} 이번 주에는 발표 자료 초안까지 끝내고 싶어요. 금요일이 마감이에요.` : '예: 다음 주 월요일부터 운동 3번, 책 한 권 읽기를 계획해 줘.'}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }}/></label>
        <label className="execution-inline"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>대화·프로필·기억·가용 시간·프로젝트와 기존 할 일을 OpenAI에 전송하는 데 동의합니다.</label>
        <button className="primary-button" disabled={busy || !consent || !text.trim() || !state.llmAvailable}>{busy ? '보내는 중…' : '보내기'}</button>
        {!state.llmAvailable && <p className="execution-help">서버 API 키를 설정하면 플래너와 대화할 수 있습니다.</p>}
      </form>
    </div>
  </section>
}

function mostRecentThread(threads: NonNullable<ExecutionState['plannerThreads']>, projects: Project[]) {
  const recent = Object.entries(threads)
    .filter(([id]) => id === FREE || projects.some(p => p.id === id))
    .sort(([, a], [, b]) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))[0]
  return recent?.[0] ?? projects[0]?.id ?? FREE
}
