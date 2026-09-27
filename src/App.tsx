import { useEffect, useState } from 'react'
import { Brain, CalendarDays, LayoutDashboard, Menu, MoreHorizontal, Pencil, Plus, Settings2, Sparkles, Target, Trash2, X } from 'lucide-react'
import './styles.css'
import { projectColor } from './projectColors'

type View = 'today' | 'calendar' | 'memory' | 'portfolio'
type ProjectStatus = 'active' | 'completed' | 'paused'
type MilestoneStatus = 'todo' | 'in_progress' | 'done' | 'deferred'
type MemoryCategory = 'availability' | 'preference' | 'priority' | 'context'
type Project = { id: string; title: string; goal: string; startDate: string; dueDate: string; priority: 'high' | 'medium' | 'low'; status: ProjectStatus }
type Milestone = { id: string; projectId: string; title: string; startDate: string; dueDate: string; estimatedHours: number; status: MilestoneStatus }
type CalendarEvent = { id: string; title: string; date: string; startTime: string; endTime: string; projectId?: string; isFixed: boolean }
type Memory = { id: string; content: string; category: MemoryCategory; source: 'user' | 'ai_approved'; createdAt: string }
type EntityKind = 'project' | 'milestone' | 'event' | 'memory'
type Editor = { kind: EntityKind; id?: string; projectId?: string; date?: string } | null

const weekdayNames = ['일', '월', '화', '수', '목', '금', '토']
const dateKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const now = new Date()
const TODAY = dateKey(now)
const shiftDay = (days: number) => dateKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + days))
const id = () => crypto.randomUUID()

const seedProjects: Project[] = [
  { id: 'project-planner', title: 'AI 플래너 MVP', goal: '프로젝트·일정·AI 조율이 연결된 개인 플래너 완성', startDate: shiftDay(-12), dueDate: shiftDay(8), priority: 'high', status: 'active' },
  { id: 'project-portfolio', title: '포트폴리오 정리', goal: '핵심 결과물과 소개 자료 정리', startDate: shiftDay(-21), dueDate: shiftDay(9), priority: 'medium', status: 'active' },
]
const seedMilestones: Milestone[] = [
  { id: 'milestone-schema', projectId: 'project-planner', title: 'DB 스키마 설계', startDate: TODAY, dueDate: shiftDay(4), estimatedHours: 4, status: 'in_progress' },
  { id: 'milestone-ui', projectId: 'project-planner', title: '화면 흐름 검토', startDate: TODAY, dueDate: TODAY, estimatedHours: 2, status: 'todo' },
]
const seedEvents: CalendarEvent[] = [
  { id: 'event-class', title: '고정 수업', date: TODAY, startTime: '15:00', endTime: '17:00', isFixed: true },
]
const seedMemories: Memory[] = [
  { id: 'memory-1', content: '평일에는 오후 7시 이후에 집중 작업을 배치하는 편이에요.', category: 'availability', source: 'user', createdAt: TODAY },
]

function useStoredState<T>(storageKey: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    const saved = localStorage.getItem(storageKey)
    if (!saved) return initial
    try { return JSON.parse(saved) as T } catch { return initial }
  })
  useEffect(() => { localStorage.setItem(storageKey, JSON.stringify(value)) }, [storageKey, value])
  return [value, setValue] as const
}

const milestoneLabel: Record<MilestoneStatus, string> = { todo: '시작 전', in_progress: '진행 중', done: '완료', deferred: '미룸' }
const priorityLabel = { high: '높음', medium: '보통', low: '낮음' }
const statusLabel: Record<ProjectStatus, string> = { active: '진행 중', completed: '완료', paused: '중지' }
const memoryLabel: Record<MemoryCategory, string> = { availability: '가용 시간', preference: '작업 성향', priority: '우선순위', context: '프로젝트 맥락' }

function App() {
  const [projects, setProjects] = useStoredState<Project[]>('replan-projects-v1', seedProjects)
  const [milestones, setMilestones] = useStoredState<Milestone[]>('replan-milestones-v1', seedMilestones)
  const [events, setEvents] = useStoredState<CalendarEvent[]>('replan-events-v1', seedEvents)
  const [memories, setMemories] = useStoredState<Memory[]>('replan-memories-v1', seedMemories)
  const [activeView, setActiveView] = useState<View>('portfolio')
  const [selectedDate, setSelectedDate] = useState(TODAY)
  const [selectedProjectId, setSelectedProjectId] = useState(projects[0]?.id ?? '')
  const [editor, setEditor] = useState<Editor>(null)
  const [notice, setNotice] = useState('')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? projects[0]

  function removeProject(projectId: string) {
    if (!window.confirm('프로젝트와 연결된 단계별 할 일을 삭제할까요? 연결 일정은 프로젝트 연결만 해제됩니다.')) return
    setProjects((items) => items.filter((item) => item.id !== projectId))
    setMilestones((items) => items.filter((item) => item.projectId !== projectId))
    setEvents((items) => items.map((item) => item.projectId === projectId ? { ...item, projectId: undefined } : item))
    setSelectedProjectId(projects.find((item) => item.id !== projectId)?.id ?? '')
    setNotice('프로젝트를 삭제했습니다.')
  }

  function saveEntity(kind: EntityKind, value: Project | Milestone | CalendarEvent | Memory) {
    const replace = <T extends { id: string }>(items: T[], item: T) => items.some((current) => current.id === item.id) ? items.map((current) => current.id === item.id ? item : current) : [...items, item]
    if (kind === 'project') { const item = value as Project; setProjects((items) => replace(items, item)); setSelectedProjectId(item.id) }
    if (kind === 'milestone') setMilestones((items) => replace(items, value as Milestone))
    if (kind === 'event') setEvents((items) => replace(items, value as CalendarEvent))
    if (kind === 'memory') setMemories((items) => replace(items, value as Memory))
    setEditor(null)
    setNotice('저장했습니다.')
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><Sparkles size={15}/></span><span>re:plan</span></div>
      <nav className="nav-list" aria-label="주요 메뉴">
        <button className={`nav-item ${activeView === 'today' ? 'active' : ''}`} onClick={() => setActiveView('today')}><LayoutDashboard size={18}/>오늘</button>
        <button className={`nav-item ${activeView === 'calendar' ? 'active' : ''}`} onClick={() => setActiveView('calendar')}><CalendarDays size={18}/>캘린더</button>
        <button className={`nav-item ${activeView === 'memory' ? 'active' : ''}`} onClick={() => setActiveView('memory')}><Brain size={18}/>기억</button>
        <button className={`nav-item ${activeView === 'portfolio' ? 'active' : ''}`} onClick={() => setActiveView('portfolio')}><Target size={18}/>전체 계획</button>
      </nav>
      <div className="sidebar-bottom"><button className="nav-item" onClick={() => setNotice('설정은 다음 단계에서 연결합니다.')}><Settings2 size={18}/>설정</button><div className="profile"><div className="avatar">H</div><div><strong>현우</strong><span>프로젝트 {projects.length}개</span></div><MoreHorizontal size={17}/></div></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><button className="mobile-menu" onClick={() => setMobileNavOpen((open) => !open)} aria-label="메뉴"><Menu size={20}/></button><div className="date-control"><CalendarDays size={17}/><div><span>LOCAL CRUD</span><strong>{activeView === 'portfolio' ? '전체 계획' : activeView === 'calendar' ? '캘린더' : activeView === 'memory' ? '기억 관리' : '오늘'}</strong></div></div><button className="primary-button compact" onClick={() => setEditor({ kind: 'project' })}><Plus size={16}/>새 프로젝트</button></header>
      {mobileNavOpen && <nav className="mobile-nav" aria-label="모바일 메뉴">{([['today', '오늘'], ['calendar', '캘린더'], ['memory', '기억'], ['portfolio', '전체 계획']] as const).map(([view, label]) => <button className={activeView === view ? 'active' : ''} key={view} onClick={() => { setActiveView(view); setMobileNavOpen(false) }}>{label}</button>)}</nav>}
      {activeView === 'today' && <section className="placeholder-workspace"><p className="eyebrow">TODAY</p><h1>오늘 계획은 다음 단계에서 연결합니다.</h1><p>현재 브랜치는 프로젝트·단계별 할 일·캘린더 일정·기억 CRUD만 담당합니다.</p></section>}
      {activeView === 'calendar' && <CalendarView projects={projects} milestones={milestones} events={events} selectedDate={selectedDate} setSelectedDate={setSelectedDate} onCreateEvent={(date) => setEditor({ kind: 'event', date })} onCreateMilestone={(projectId) => setEditor({ kind: 'milestone', projectId })} onEditEvent={(eventId) => setEditor({ kind: 'event', id: eventId })} onDeleteEvent={(eventId) => setEvents((items) => items.filter((item) => item.id !== eventId))} />}
      {activeView === 'portfolio' && <PortfolioView projects={projects} milestones={milestones} selectedProject={selectedProject} setSelectedProjectId={setSelectedProjectId} onCreateProject={() => setEditor({ kind: 'project' })} onEditProject={(projectId) => setEditor({ kind: 'project', id: projectId })} onDeleteProject={removeProject} onCreateMilestone={(projectId) => setEditor({ kind: 'milestone', projectId })} onEditMilestone={(milestoneId) => setEditor({ kind: 'milestone', id: milestoneId })} onDeleteMilestone={(milestoneId) => setMilestones((items) => items.filter((item) => item.id !== milestoneId))} />}
      {activeView === 'memory' && <MemoryView memories={memories} onCreate={() => setEditor({ kind: 'memory' })} onEdit={(memoryId) => setEditor({ kind: 'memory', id: memoryId })} onDelete={(memoryId) => setMemories((items) => items.filter((item) => item.id !== memoryId))} />}
    </main>
    {notice && <div className="notice-toast"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="알림 닫기"><X size={15}/></button></div>}
    {editor && <EntityForm editor={editor} projects={projects} milestones={milestones} events={events} memories={memories} onClose={() => setEditor(null)} onSave={saveEntity}/>}
  </div>
}

function ProjectLegend({ projects }: { projects: Project[] }) {
  return <div className="project-legend">{projects.map((project) => <span key={project.id}><i style={{ backgroundColor: projectColor(project.id) }}/>{project.title}</span>)}</div>
}

function CalendarView({ projects, milestones, events, selectedDate, setSelectedDate, onCreateEvent, onCreateMilestone, onEditEvent, onDeleteEvent }: { projects: Project[]; milestones: Milestone[]; events: CalendarEvent[]; selectedDate: string; setSelectedDate: (date: string) => void; onCreateEvent: (date: string) => void; onCreateMilestone: (projectId: string) => void; onEditEvent: (id: string) => void; onDeleteEvent: (id: string) => void }) {
  const selectedDateValue = new Date(`${selectedDate}T00:00:00`)
  const [visibleYear, setVisibleYear] = useState(selectedDateValue.getFullYear())
  const [visibleMonth, setVisibleMonth] = useState(selectedDateValue.getMonth())
  const calendarStart = new Date(visibleYear, visibleMonth, 1 - new Date(visibleYear, visibleMonth, 1).getDay())
  const calendarDays = Array.from({ length: 42 }, (_, index) => new Date(calendarStart.getFullYear(), calendarStart.getMonth(), calendarStart.getDate() + index))
  const monthTitle = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long' }).format(new Date(visibleYear, visibleMonth, 1))
  function moveMonth(offset: number) {
    const next = new Date(visibleYear, visibleMonth + offset, 1)
    setVisibleYear(next.getFullYear())
    setVisibleMonth(next.getMonth())
    setSelectedDate(dateKey(next))
  }
  const entries = (date: string) => [
    ...milestones.filter((item) => item.startDate === date || item.dueDate === date).map((item) => ({ id: item.id, label: item.title, color: projectColor(item.projectId), type: 'milestone' as const, suffix: item.dueDate === date ? '마감' : '시작' })),
    ...events.filter((item) => item.date === date).map((item) => ({ id: item.id, label: item.title, color: item.projectId ? projectColor(item.projectId) : undefined, type: 'event' as const, suffix: `${item.startTime}–${item.endTime}` })),
  ]
  const selected = calendarDays.find((day) => dateKey(day) === selectedDate) ?? now
  return <section className="calendar-workspace"><div className="calendar-intro"><div><p className="eyebrow">MONTHLY VIEW</p><h1>일정과 단계별 할 일을 <em>함께</em>.</h1><p>일정은 여기서 추가·수정·삭제하고, 단계별 할 일은 프로젝트에서 관리합니다.</p></div><button className="primary-button compact" onClick={() => onCreateEvent(selectedDate)}><Plus size={16}/>일정 추가</button></div><ProjectLegend projects={projects}/><div className="calendar-layout"><div className="month-card"><div className="month-card-head"><button className="month-nav" onClick={() => moveMonth(-1)} aria-label="이전 달">‹</button><h2>{monthTitle}</h2><button className="month-nav" onClick={() => moveMonth(1)} aria-label="다음 달">›</button></div><div className="weekday-row">{weekdayNames.map((day) => <span key={day}>{day}</span>)}</div><div className="month-grid">{calendarDays.map((day) => { const date = dateKey(day); const plans = entries(date); return <button className={`calendar-cell ${day.getMonth() !== visibleMonth ? 'outside' : ''} ${date === selectedDate ? 'selected' : ''}`} key={date} onClick={() => setSelectedDate(date)}><span className="calendar-date">{day.getDate()}</span><div className="calendar-pills">{plans.slice(0, 2).map((plan) => <span className="calendar-pill project" style={{ borderLeftColor: plan.color }} key={`${plan.type}-${plan.id}`}>{plan.label}</span>)}{plans.length > 2 && <small>+{plans.length - 2}개</small>}</div></button> })}</div></div><aside className="day-planner"><p className="section-kicker">{new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' }).format(selected)}</p><h2>이 날의 일정</h2><div className="selected-plan-list">{entries(selectedDate).map((entry) => <div key={`${entry.type}-${entry.id}`}><i style={{ backgroundColor: entry.color }}/><span>{entry.label}<small>{entry.suffix}</small></span>{entry.type === 'event' && <span className="row-actions"><button onClick={() => onEditEvent(entry.id)} aria-label="일정 수정"><Pencil size={14}/></button><button onClick={() => onDeleteEvent(entry.id)} aria-label="일정 삭제"><Trash2 size={14}/></button></span>}</div>)}{!entries(selectedDate).length && <span className="empty-day">등록된 항목이 없습니다.</span>}</div><button className="primary-button full" onClick={() => onCreateEvent(selectedDate)}><Plus size={16}/>일정 추가</button><button className="secondary-button full-spaced" disabled={!projects.length} onClick={() => projects[0] && onCreateMilestone(projects[0].id)}><Plus size={16}/>단계별 할 일 추가</button></aside></div></section>
}

function PortfolioView({ projects, milestones, selectedProject, setSelectedProjectId, onCreateProject, onEditProject, onDeleteProject, onCreateMilestone, onEditMilestone, onDeleteMilestone }: { projects: Project[]; milestones: Milestone[]; selectedProject?: Project; setSelectedProjectId: (id: string) => void; onCreateProject: () => void; onEditProject: (id: string) => void; onDeleteProject: (id: string) => void; onCreateMilestone: (id: string) => void; onEditMilestone: (id: string) => void; onDeleteMilestone: (id: string) => void }) {
  return <section className="portfolio-workspace"><div className="portfolio-intro"><div><p className="eyebrow">PROJECTS</p><h1>프로젝트와 단계별 할 일을 <em>관리</em>.</h1><p>달성률·위험도 계산 없이 프로젝트 원본 데이터만 관리합니다.</p></div><button className="primary-button compact" onClick={onCreateProject}><Plus size={16}/>새 프로젝트</button></div><ProjectLegend projects={projects}/><div className="portfolio-layout"><div className="project-list-panel"><div className="project-card-list">{projects.map((project) => <button className={`project-progress-card ${selectedProject?.id === project.id ? 'selected' : ''}`} key={project.id} onClick={() => setSelectedProjectId(project.id)}><div className="project-name-row"><h3><span className="project-color-dot" style={{ backgroundColor: projectColor(project.id) }}/>{project.title}</h3><span className="status-chip planned">{statusLabel[project.status]}</span></div><p className="project-insight">{project.startDate} ~ {project.dueDate}</p></button>)}{!projects.length && <div className="empty-state">프로젝트를 추가해 주세요.</div>}</div></div>{selectedProject && <aside className="project-detail-panel"><div className="detail-heading"><div><span className="status-chip planned">중요도 {priorityLabel[selectedProject.priority]}</span><h2>{selectedProject.title}</h2></div><span className="row-actions"><button onClick={() => onEditProject(selectedProject.id)} aria-label="프로젝트 수정"><Pencil size={16}/></button><button onClick={() => onDeleteProject(selectedProject.id)} aria-label="프로젝트 삭제"><Trash2 size={16}/></button></span></div><p className="detail-date">{selectedProject.startDate} ~ {selectedProject.dueDate}</p><p className="detail-goal">{selectedProject.goal || '등록된 목표가 없습니다.'}</p><div className="milestone-list"><div className="list-heading"><h3>단계별 할 일</h3><button className="text-button" onClick={() => onCreateMilestone(selectedProject.id)}><Plus size={14}/>추가</button></div>{milestones.filter((item) => item.projectId === selectedProject.id).map((item) => <div className="milestone-row" key={item.id}><span className={`milestone-status ${item.status}`}/><span><strong>{item.title}</strong><small>{item.startDate} ~ {item.dueDate} · {item.estimatedHours}시간 · {milestoneLabel[item.status]}</small></span><span className="row-actions"><button onClick={() => onEditMilestone(item.id)} aria-label="할 일 수정"><Pencil size={14}/></button><button onClick={() => onDeleteMilestone(item.id)} aria-label="할 일 삭제"><Trash2 size={14}/></button></span></div>)}{!milestones.some((item) => item.projectId === selectedProject.id) && <div className="empty-state">단계별 할 일이 없습니다.</div>}</div><button className="primary-button full" onClick={() => onCreateMilestone(selectedProject.id)}><Plus size={16}/>단계별 할 일 추가</button></aside>}</div></section>
}

function MemoryView({ memories, onCreate, onEdit, onDelete }: { memories: Memory[]; onCreate: () => void; onEdit: (id: string) => void; onDelete: (id: string) => void }) {
  return <section className="memory-workspace"><div className="calendar-intro"><div><p className="eyebrow">MEMORY</p><h1>나의 맥락을 <em>직접 관리</em>.</h1><p>현재는 사용자가 입력한 기억을 localStorage에 저장합니다.</p></div><button className="primary-button compact" onClick={onCreate}><Plus size={16}/>기억 추가</button></div><div className="memory-grid">{memories.map((memory) => <article className="memory-card" key={memory.id}><div><span className="status-chip planned">{memoryLabel[memory.category]}</span><span className="row-actions"><button onClick={() => onEdit(memory.id)} aria-label="기억 수정"><Pencil size={15}/></button><button onClick={() => onDelete(memory.id)} aria-label="기억 삭제"><Trash2 size={15}/></button></span></div><p>“{memory.content}”</p><small>{memory.createdAt} 저장</small></article>)}{!memories.length && <div className="empty-state">저장한 기억이 없습니다.</div>}</div></section>
}

function EntityForm({ editor, projects, milestones, events, memories, onClose, onSave }: { editor: Exclude<Editor, null>; projects: Project[]; milestones: Milestone[]; events: CalendarEvent[]; memories: Memory[]; onClose: () => void; onSave: (kind: EntityKind, value: Project | Milestone | CalendarEvent | Memory) => void }) {
  const existing = editor.kind === 'project' ? projects.find((item) => item.id === editor.id) : editor.kind === 'milestone' ? milestones.find((item) => item.id === editor.id) : editor.kind === 'event' ? events.find((item) => item.id === editor.id) : memories.find((item) => item.id === editor.id)
  const [title, setTitle] = useState(existing && 'title' in existing ? existing.title : existing && 'content' in existing ? existing.content : '')
  const [goal, setGoal] = useState(existing && 'goal' in existing ? existing.goal : '')
  const [startDate, setStartDate] = useState(existing && 'startDate' in existing ? existing.startDate : existing && 'date' in existing ? existing.date : editor.date ?? TODAY)
  const [dueDate, setDueDate] = useState(existing && 'dueDate' in existing ? existing.dueDate : TODAY)
  const [priority, setPriority] = useState<Project['priority']>(existing && 'priority' in existing ? existing.priority : 'medium')
  const [projectStatus, setProjectStatus] = useState<ProjectStatus>(existing && 'goal' in existing ? existing.status : 'active')
  const [milestoneStatus, setMilestoneStatus] = useState<MilestoneStatus>(existing && 'estimatedHours' in existing ? existing.status : 'todo')
  const [hours, setHours] = useState(existing && 'estimatedHours' in existing ? existing.estimatedHours : 2)
  const [projectId, setProjectId] = useState(existing && 'projectId' in existing ? existing.projectId ?? '' : editor.projectId ?? projects[0]?.id ?? '')
  const [startTime, setStartTime] = useState(existing && 'startTime' in existing ? existing.startTime : '18:00')
  const [endTime, setEndTime] = useState(existing && 'endTime' in existing ? existing.endTime : '19:00')
  const [isFixed, setIsFixed] = useState(existing && 'isFixed' in existing ? existing.isFixed : false)
  const [category, setCategory] = useState<MemoryCategory>(existing && 'category' in existing ? existing.category : 'context')
  const [error, setError] = useState('')
  const heading = `${existing ? '수정' : '추가'} · ${editor.kind === 'project' ? '프로젝트' : editor.kind === 'milestone' ? '단계별 할 일' : editor.kind === 'event' ? '일정' : '기억'}`

  function submit() {
    if (!title.trim()) return
    if (editor.kind === 'event' && (!startTime || !endTime || endTime <= startTime)) {
      setError(!startTime || !endTime ? '시작 시간과 종료 시간을 모두 입력해 주세요.' : '종료 시간은 시작 시간보다 늦어야 합니다.')
      return
    }
    const entityId = existing?.id ?? id()
    if (editor.kind === 'project') onSave('project', { id: entityId, title: title.trim(), goal: goal.trim(), startDate, dueDate, priority, status: projectStatus })
    if (editor.kind === 'milestone' && projectId) onSave('milestone', { id: entityId, projectId, title: title.trim(), startDate, dueDate, estimatedHours: hours, status: milestoneStatus })
    if (editor.kind === 'event') onSave('event', { id: entityId, title: title.trim(), date: startDate, startTime, endTime, projectId: projectId || undefined, isFixed })
    if (editor.kind === 'memory') onSave('memory', { id: entityId, content: title.trim(), category, source: existing && 'source' in existing ? existing.source : 'user', createdAt: existing && 'createdAt' in existing ? existing.createdAt : TODAY })
  }

  return <div className="modal-backdrop" onMouseDown={onClose}><form className="data-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); submit() }}><button className="close-button" type="button" onClick={onClose} aria-label="닫기"><X size={18}/></button><p className="section-kicker">LOCAL CRUD</p><h2>{heading}</h2><label>{editor.kind === 'memory' ? '기억 내용' : '제목'}<input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} required/></label>{editor.kind === 'project' && <><label>목표<textarea rows={3} value={goal} onChange={(event) => setGoal(event.target.value)}/></label><div className="form-date-grid"><label>중요도<select value={priority} onChange={(event) => setPriority(event.target.value as Project['priority'])}><option value="high">높음</option><option value="medium">보통</option><option value="low">낮음</option></select></label><label>상태<select value={projectStatus} onChange={(event) => setProjectStatus(event.target.value as ProjectStatus)}><option value="active">진행 중</option><option value="paused">중지</option><option value="completed">완료</option></select></label></div></>}{editor.kind === 'memory' && <label>분류<select value={category} onChange={(event) => setCategory(event.target.value as MemoryCategory)}>{Object.entries(memoryLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>}{(editor.kind === 'milestone' || editor.kind === 'event') && <label>연결 프로젝트<select value={projectId} onChange={(event) => setProjectId(event.target.value)} required={editor.kind === 'milestone'}><option value="">연결 안 함</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.title}</option>)}</select></label>}{editor.kind !== 'memory' && <div className="form-date-grid"><label>{editor.kind === 'event' ? '날짜' : '시작일'}<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required/></label>{editor.kind !== 'event' && <label>마감일<input type="date" min={startDate} value={dueDate} onChange={(event) => setDueDate(event.target.value)} required/></label>}</div>}{editor.kind === 'milestone' && <div className="form-date-grid"><label>예상 시간<input type="number" min="1" value={hours} onChange={(event) => setHours(Number(event.target.value))}/></label><label>상태<select value={milestoneStatus} onChange={(event) => setMilestoneStatus(event.target.value as MilestoneStatus)}><option value="todo">시작 전</option><option value="in_progress">진행 중</option><option value="done">완료</option><option value="deferred">미룸</option></select></label></div>}{editor.kind === 'event' && <><div className="form-date-grid"><label>시작 시간<input type="time" required value={startTime} onChange={(event) => { setStartTime(event.target.value); setError('') }}/></label><label>종료 시간<input type="time" required value={endTime} onChange={(event) => { setEndTime(event.target.value); setError('') }}/></label></div><label className="checkbox-label"><input type="checkbox" checked={isFixed} onChange={(event) => setIsFixed(event.target.checked)}/>고정 일정</label></>}{error && <p className="form-error" role="alert">{error}</p>}<button className="primary-button full" type="submit">저장</button></form></div>
}

export default App
