import { useEffect, useRef, useState } from 'react'
import './styles.css'
import { AppShell } from './app/AppShell'
import { CalendarView } from './features/calendar/CalendarView'
import { EventForm } from './features/calendar/EventForm'
import { MemoryForm } from './features/memories/MemoryForm'
import { MemoryView } from './features/memories/MemoryView'
import { ProjectForm } from './features/projects/ProjectForm'
import { ProjectsView } from './features/projects/ProjectsView'
import { TODAY } from './shared/constants'
import { setProjectColors } from './shared/projectColors'
import { SEED_CLEANUP_KEY, withoutOldSeeds } from './shared/oldSeeds'
import { ExecutionView } from './features/execution/ExecutionView'
import { executionApi, planCalendarEvents } from './features/execution/api'
import type {
  CalendarEvent,
  Editor,
  Entity,
  EntityKind,
  Memory,
  Milestone,
  Project,
  View,
  ExecutionState,
  AuthUser,
  WorkspaceData,
} from './shared/types'

type AppProps = {
  initial: WorkspaceData
  onPersist: (workspace: WorkspaceData) => void
  user?: AuthUser
  onLogout?: () => void
  saveError?: string
}

function App({ initial, onPersist, user, onLogout, saveError }: AppProps) {
  const [projects, setProjects] = useState<Project[]>(initial.projects)
  const [milestones, setMilestones] = useState<Milestone[]>(initial.milestones)
  const [events, setEvents] = useState<CalendarEvent[]>(initial.events)
  const [memories, setMemories] = useState<Memory[]>(initial.memories)
  const persistRef = useRef(onPersist)
  persistRef.current = onPersist
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current && user) { firstRender.current = false; return }
    firstRender.current = false
    persistRef.current({ projects, milestones, events, memories })
  }, [projects, milestones, events, memories, user])
  // Home is the week on the calendar; a user without a profile is sent to the survey first.
  const [activeView, setActiveView] = useState<View>('calendar')
  const [activeProjectId, setActiveProjectId] = useState('')
  // A project opened from the home screen's check-in prompt starts its check-in.
  const [checkInFor, setCheckInFor] = useState('')
  const [selectedDate, setSelectedDate] = useState(TODAY)
  const [selectedProjectId, setSelectedProjectId] = useState(projects[0]?.id ?? '')
  const [editor, setEditor] = useState<Editor>(null)
  const [notice, setNotice] = useState('')
  const [execution, setExecution] = useState<ExecutionState | null>(null)
  const [executionError, setExecutionError] = useState('')
  async function loadExecution() {
    setExecutionError('')
    try { setExecution(await executionApi()) }
    catch (error) { setExecutionError(error instanceof Error ? error.message : '실행 프로필을 불러오지 못했습니다.') }
  }
  useEffect(() => { void loadExecution() }, [])
  const needsSurvey = !!execution && !execution.profile && !execution.profileDraft
  useEffect(() => { if (needsSurvey) setActiveView('execution') }, [needsSurvey])
  // Once per browser and account: drop the sample data older versions saved, now that the planner can tell what was used.
  const cleanupKey = user ? `${SEED_CLEANUP_KEY}:${user.id}` : SEED_CLEANUP_KEY
  useEffect(() => {
    if (!execution || localStorage.getItem(cleanupKey)) return
    const clean = withoutOldSeeds({ projects, milestones, events, memories }, execution)
    localStorage.setItem(cleanupKey, new Date().toISOString())
    if (!clean.removed.length) return
    setProjects(clean.projects); setMilestones(clean.milestones); setEvents(clean.events); setMemories(clean.memories)
    setNotice(`예전 버전이 넣어 둔 ${clean.removed.join(', ')}을 지웠어요. 계획에 더는 쓰이지 않아요.`)
  }, [execution, cleanupKey, projects, milestones, events, memories])
  const generatedEvents = planCalendarEvents(execution?.plan ?? null, projects)
  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? projects[0]

  function removeProject(projectId: string) {
    if (!window.confirm('프로젝트와 연결된 단계별 할 일을 삭제할까요? 연결 일정은 프로젝트 연결만 해제됩니다.')) return

    setProjects((items) => items.filter((item) => item.id !== projectId))
    setMilestones((items) => items.filter((item) => item.projectId !== projectId))
    setEvents((items) => items.map((item) => (
      item.projectId === projectId ? { ...item, projectId: undefined } : item
    )))
    setSelectedProjectId(projects.find((item) => item.id !== projectId)?.id ?? '')
    if (activeProjectId === projectId && activeView === 'project') setActiveView('calendar')
    setNotice('프로젝트를 삭제했습니다.')
  }

  function saveEntity(kind: EntityKind, value: Entity) {
    const replace = <T extends { id: string }>(items: T[], item: T) => (
      items.some((current) => current.id === item.id)
        ? items.map((current) => current.id === item.id ? item : current)
        : [...items, item]
    )

    if (kind === 'project') {
      const item = value as Project
      // A new project opens its conversation, where its plan is asked for.
      if (!projects.some((current) => current.id === item.id)) openProject(item.id)
      setProjects((items) => replace(items, item))
      setSelectedProjectId(item.id)
    }
    if (kind === 'milestone') setMilestones((items) => replace(items, value as Milestone))
    if (kind === 'event') setEvents((items) => replace(items, value as CalendarEvent))
    if (kind === 'memory') setMemories((items) => replace(items, value as Memory))
    setEditor(null)
    setNotice('저장했습니다.')
  }

  function openProject(projectId: string, checkIn = false) {
    setActiveProjectId(projectId)
    setCheckInFor(checkIn ? projectId : '')
    setActiveView('project')
  }

  const executionProps = execution && {
    state: execution, onChange: setExecution, projects, milestones, events, memories,
    onProjectStatus: (projectId: string, status: Project['status']) => setProjects(items => items.map(item => item.id === projectId ? { ...item, status } : item)),
    onGoHome: () => setActiveView('calendar'),
    onOpenProfile: () => setActiveView('execution'),
    onOpenProject: openProject,
    onCreateProject: () => setEditor({ kind: 'project' }),
    onEditProject: (projectId: string) => setEditor({ kind: 'project', id: projectId }),
    onOpenSchedule: () => setActiveView('schedule'),
  }
  const executionLoading = <section className="execution-card"><h1>내 플래너</h1>
    <p role={executionError ? 'alert' : 'status'}>{executionError || '저장된 프로필을 불러오는 중입니다…'}</p>
    {executionError && <button className="primary-button" onClick={() => { void loadExecution() }}>다시 불러오기</button>}
  </section>
  const calendarView = <CalendarView
    projects={projects}
    milestones={milestones}
    events={[...events, ...generatedEvents]}
    readOnlyEventIds={generatedEvents.map(event => event.id)}
    onOpenExecution={() => document.getElementById('my-week')?.scrollIntoView({ behavior: 'smooth' })}
    selectedDate={selectedDate}
    setSelectedDate={setSelectedDate}
    onCreateEvent={(date) => setEditor({ kind: 'event', date })}
    onCreateMilestone={(projectId) => setEditor({ kind: 'milestone', projectId })}
    onEditEvent={(eventId) => setEditor({ kind: 'event', id: eventId })}
    onDeleteEvent={(eventId) => setEvents((items) => items.filter((item) => item.id !== eventId))}
  />

  const entityForm = editor?.kind === 'project' || editor?.kind === 'milestone' ? (
    <ProjectForm
      editor={editor}
      projects={projects}
      milestones={milestones}
      onClose={() => setEditor(null)}
      onSave={(value) => saveEntity(editor.kind, value)}
    />
  ) : editor?.kind === 'event' ? (
    <EventForm
      editor={editor}
      projects={projects}
      events={events}
      onClose={() => setEditor(null)}
      onSave={(value) => saveEntity('event', value)}
    />
  ) : editor?.kind === 'memory' ? (
    <MemoryForm
      editor={editor}
      memories={memories}
      onClose={() => setEditor(null)}
      onSave={(value) => saveEntity('memory', value)}
    />
  ) : null

  setProjectColors(projects)

  return (
    <AppShell
      activeView={activeView}
      onChangeView={setActiveView}
      onCreateProject={() => setEditor({ kind: 'project' })}
      projectCount={projects.length}
      projects={projects}
      endedProjectIds={Object.keys(execution?.closedProjects ?? {})}
      activeProjectId={activeProjectId}
      onOpenProject={openProject}
      user={user}
      onLogout={onLogout}
      notice={notice || saveError || ''}
      onCloseNotice={() => setNotice('')}
      editor={entityForm}
    >
      {activeView === 'execution' && (executionProps
        ? <ExecutionView {...executionProps} section="profile" onProfileConfirmed={() => setActiveView('calendar')}/>
        : executionLoading)}
      {activeView === 'calendar' && (executionProps
        ? <ExecutionView {...executionProps} section="home" calendar={calendarView}/>
        : <>{executionLoading}{calendarView}</>)}
      {activeView === 'schedule' && (executionProps
        ? <ExecutionView {...executionProps} section="schedule"/>
        : executionLoading)}
      {activeView === 'project' && (executionProps
        ? <ExecutionView {...executionProps} section="project" projectId={activeProjectId}
            startCheckIn={checkInFor === activeProjectId} onCheckInStarted={() => setCheckInFor('')}/>
        : executionLoading)}

      {activeView === 'portfolio' && (
        <ProjectsView
          projects={projects}
          milestones={milestones}
          selectedProject={selectedProject}
          setSelectedProjectId={setSelectedProjectId}
          onCreateProject={() => setEditor({ kind: 'project' })}
          onEditProject={(projectId) => setEditor({ kind: 'project', id: projectId })}
          onDeleteProject={removeProject}
          onCreateMilestone={(projectId) => setEditor({ kind: 'milestone', projectId })}
          onEditMilestone={(milestoneId) => setEditor({ kind: 'milestone', id: milestoneId })}
          onDeleteMilestone={(milestoneId) => (
            setMilestones((items) => items.filter((item) => item.id !== milestoneId))
          )}
        />
      )}

      {activeView === 'memory' && (
        <MemoryView
          memories={memories}
          onCreate={() => setEditor({ kind: 'memory' })}
          onEdit={(memoryId) => setEditor({ kind: 'memory', id: memoryId })}
          onDelete={(memoryId) => setMemories((items) => items.filter((item) => item.id !== memoryId))}
        />
      )}
    </AppShell>
  )
}

export default App
