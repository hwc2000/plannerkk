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
  const [activeView, setActiveView] = useState<View>('portfolio')
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
      setProjects((items) => replace(items, item))
      setSelectedProjectId(item.id)
    }
    if (kind === 'milestone') setMilestones((items) => replace(items, value as Milestone))
    if (kind === 'event') setEvents((items) => replace(items, value as CalendarEvent))
    if (kind === 'memory') setMemories((items) => replace(items, value as Memory))
    setEditor(null)
    setNotice('저장했습니다.')
  }

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

  return (
    <AppShell
      activeView={activeView}
      onChangeView={setActiveView}
      onCreateProject={() => setEditor({ kind: 'project' })}
      onShowSettingsNotice={() => setActiveView('execution')}
      projectCount={projects.length}
      user={user}
      onLogout={onLogout}
      notice={notice || saveError || ''}
      onCloseNotice={() => setNotice('')}
      editor={entityForm}
    >
      {activeView === 'execution' && (execution ? <ExecutionView
        state={execution} onChange={setExecution} projects={projects} milestones={milestones} events={events} memories={memories}
        onCreateProject={() => setEditor({ kind: 'project' })}
      /> : <section className="execution-card"><h1>실행 프로필과 주간 계획</h1>
        <p role={executionError ? 'alert' : 'status'}>{executionError || '저장된 프로필을 불러오는 중입니다…'}</p>
        {executionError && <button className="primary-button" onClick={() => { void loadExecution() }}>다시 불러오기</button>}
      </section>)}
      {activeView === 'calendar' && (
        <CalendarView
          projects={projects}
          milestones={milestones}
          events={[...events, ...generatedEvents]}
          readOnlyEventIds={generatedEvents.map(event => event.id)}
          onOpenExecution={() => setActiveView('execution')}
          selectedDate={selectedDate}
          setSelectedDate={setSelectedDate}
          onCreateEvent={(date) => setEditor({ kind: 'event', date })}
          onCreateMilestone={(projectId) => setEditor({ kind: 'milestone', projectId })}
          onEditEvent={(eventId) => setEditor({ kind: 'event', id: eventId })}
          onDeleteEvent={(eventId) => setEvents((items) => items.filter((item) => item.id !== eventId))}
        />
      )}

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
