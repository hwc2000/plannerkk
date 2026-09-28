export type View = 'today' | 'calendar' | 'memory' | 'portfolio' | 'execution'

export type ProjectStatus = 'active' | 'completed' | 'paused'
export type MilestoneStatus = 'todo' | 'in_progress' | 'done' | 'deferred'
export type MemoryCategory = 'availability' | 'preference' | 'priority' | 'context'

export type Project = {
  id: string
  title: string
  goal: string
  startDate: string
  dueDate: string
  priority: 'high' | 'medium' | 'low'
  status: ProjectStatus
}

export type Milestone = {
  id: string
  projectId: string
  title: string
  startDate: string
  dueDate: string
  estimatedHours: number
  status: MilestoneStatus
}

export type CalendarEvent = {
  id: string
  title: string
  date: string
  startTime: string
  endTime: string
  projectId?: string
  isFixed: boolean
}

export type Memory = {
  id: string
  content: string
  category: MemoryCategory
  source: 'user' | 'ai_approved'
  createdAt: string
}

export type EntityKind = 'project' | 'milestone' | 'event' | 'memory'

export type Editor = {
  kind: EntityKind
  id?: string
  projectId?: string
  date?: string
} | null

export type Entity = Project | Milestone | CalendarEvent | Memory

export type ExecutionAnswers = {
  roles: string[]
  regularity: string
  barriers: string[]
  focusMinutes: number | null
  dailyMinutes: number | null
  energy: string
  recovery: string
  constraints: string
  context: string
}

export type ExecutionProfile = {
  id: string
  schemaVersion: string
  createdAt: string
  source: 'demo' | 'llm'
  status: 'draft' | 'confirmed'
  facts: ExecutionAnswers
  planningPreferences: {
    blockMinutes: number
    breakMinutes: number
    bufferPercent: number
    dailyPlannedMinutes: number | null
    scheduleStyle: string
    recoveryPreference: string
    starterMinutes: number | null
    status: string
  }
  insights: {
    summary: string
    strategies: Array<{ action: string; reason: string; evidence: string[] }>
    followUpQuestions: string[]
  }
}

export type AvailabilitySlot = { day: number; hour: number }
export type PlannerSettings = { slots: AvailabilitySlot[]; view: 'timeline' | 'checklist' }
export type ExecutionTask = { title: string; minutes: number; doneWhen: string; dueDate: string | null }
export type ExecutionEntry = ExecutionTask & {
  id: string; kind: 'task' | 'break'; start: string; end: string; completed: boolean
}
export type ExecutionPlan = {
  id: string; profileId: string; projectId: string | null
  project: Pick<Project, 'id' | 'title' | 'goal' | 'startDate' | 'dueDate'> | null
  goal: string; startDate: string; endDate: string; timezone: string
  status: 'draft' | 'confirmed'; slots: AvailabilitySlot[]
  entries: ExecutionEntry[]; pendingTasks: Array<ExecutionTask & { reason: string }>
}
export type ExecutionState = {
  revision: number; profile: ExecutionProfile | null; profileDraft: ExecutionProfile | null
  settings: PlannerSettings; plan: ExecutionPlan | null; planDraft: ExecutionPlan | null
  llmAvailable: boolean; model: string
}
