import { useState } from 'react'
import './styles.css'
import { AppShell } from './app/AppShell'
import { AiPlanningView } from './features/ai-planning/AiPlanningView'
import { draftTasksToMilestones, type AiPlanDraft } from './features/ai-planning/aiPlan'
import { CalendarView } from './features/calendar/CalendarView'
import { EventForm } from './features/calendar/EventForm'
import { MemoryForm } from './features/memories/MemoryForm'
import { MemoryView } from './features/memories/MemoryView'
import { ProjectForm } from './features/projects/ProjectForm'
import { ProjectsView } from './features/projects/ProjectsView'
import {
  seedEvents,
  seedMemories,
  seedMilestones,
  seedProjects,
  TODAY,
} from './shared/constants'
import { useStoredState } from './shared/storage'
import type {
  CalendarEvent,
  Editor,
  Entity,
  EntityKind,
  Memory,
  Milestone,
  Project,
  View,
} from './shared/types'

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

  function applyAiDraft(projectId: string, draft: AiPlanDraft) {
    const project = projects.find((item) => item.id === projectId)
    if (!project) {
      setNotice('프로젝트가 변경되었습니다. AI 계획 초안을 다시 요청해주세요.')
      return
    }
    let generated: Milestone[]
    try {
      generated = draftTasksToMilestones(project, draft)
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : 'AI 계획 초안을 반영하지 못했습니다.')
      return
    }
    setMilestones((items) => [...items, ...generated])
    setSelectedProjectId(projectId)
    setNotice(`AI 초안의 단계별 할 일 ${generated.length}개를 반영했습니다.`)
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
      onShowSettingsNotice={() => setNotice('설정은 다음 단계에서 연결합니다.')}
      projectCount={projects.length}
      notice={notice}
      onCloseNotice={() => setNotice('')}
      editor={entityForm}
    >
      {activeView === 'today' && (
        <AiPlanningView
          projects={projects}
          milestones={milestones}
          selectedProjectId={selectedProject?.id ?? ''}
          onSelectProject={setSelectedProjectId}
          onApply={applyAiDraft}
        />
      )}

      {activeView === 'calendar' && (
        <CalendarView
          projects={projects}
          milestones={milestones}
          events={events}
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
