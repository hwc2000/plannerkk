export type View = 'today' | 'calendar' | 'memory' | 'portfolio'

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
