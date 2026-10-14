export type View = 'calendar' | 'memory' | 'portfolio' | 'execution'

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
  updatedAt?: string
  expiresAt?: string | null
  sensitive?: boolean
  useForPlanning?: boolean
  projectId?: string | null
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

export type ScheduleStyle = 'time_blocks' | 'flexible_queue'

export type ExecutionAnswers = {
  scheduleStyle?: ScheduleStyle | 'unknown'
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
  userId?: string
  version?: number
  declaredFacts?: ExecutionAnswers
  learnedPatterns?: LearnedPattern[]
  updatedAt?: string
  confirmedAt?: string | null
  surveyResponseId?: string | null
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
    scheduleStyle: ScheduleStyle
    scheduleStyleSource?: "user" | "rule" | "legacy"
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
export type ExecutionTask = { title: string; minutes: number; doneWhen: string; dueDate: string | null; projectId?: string | null }
export type ExecutionEntry = ExecutionTask & {
  id: string; kind: 'task' | 'break'; start: string; end: string; completed: boolean; starter?: boolean
}
/** Why the plan looks the way it does for this user; built by code from the values it applied. */
export type PlanReason = {
  key: string; applied: string; because: string
  source: 'declared' | 'learned' | 'default' | 'profile' | 'memory' | 'project'; fields: string[]
}
export type ExecutionPlan = {
  profileVersion?: number
  scheduleStyle?: ScheduleStyle
  id: string; profileId: string; projectId: string | null
  // The project's own settings version used for this plan; absent on older plans.
  projectProfileId?: string | null; projectProfileVersion?: number | null
  project: Pick<Project, 'id' | 'title' | 'goal' | 'startDate' | 'dueDate'> | null
  projects?: Array<Pick<Project, 'id' | 'title' | 'goal' | 'startDate' | 'dueDate'>>
  projectGoals?: Record<string, string>
  goal: string; startDate: string; endDate: string; timezone: string
  status: 'draft' | 'confirmed'; slots: AvailabilitySlot[]
  entries: ExecutionEntry[]; pendingTasks: Array<ExecutionTask & { reason: string }>
  personalization?: PlanReason[]
}
export type ExecutionState = {
  executionRecords?: ExecutionRecord[]; profileUpdateProposals?: ProfileUpdateProposal[]
  revision: number; profile: ExecutionProfile | null; profileDraft: ExecutionProfile | null
  settings: PlannerSettings; plan: ExecutionPlan | null; planDraft: ExecutionPlan | null
  projectProfiles?: Record<string, ProjectProfile>
  llmAvailable: boolean; model: string
  plannerThreads?: Record<string, PlannerThread>
}

/** Values that differ for one project, on top of the user profile. Absent keys follow the user profile. */
export type ProjectProfile = {
  id: string; projectId: string; userId: string; version: number
  overrides: Record<string, { value: number | string | null; source: 'declared' | 'learned'; proposalId: string | null }>
  learnedPatterns: LearnedPattern[]; createdAt: string; updatedAt: string
}
export type PlannerMessage = { id: string; role: 'user' | 'assistant'; content: string }
/** One conversation per project; the key is the project id, or '_free' for work without a project. */
export type PlannerThread = { messages: PlannerMessage[]; action: PlannerAction | null; updatedAt?: string }
export type PlannerAction =
  | { kind: 'plan'; revision: number; payload: { goal: string; startDate: string } }
  | { kind: 'settings'; revision: number; payload: PlannerSettings }

export type ExecutionRecord = {
  id: string; planId: string; taskId: string; profileId: string; taskTitle: string
  // Absent on records saved before they were added.
  profileVersion?: number | null; projectId?: string | null; projectProfileId?: string | null
  plannedMinutes: number; actualMinutes: number | null; remainingMinutes?: number | null
  result: 'completed' | 'partial' | 'not_started' | 'incomplete'
  reasonCode: string | null; note: string; difficulty: number | null
  recoveryAction: string | null; recoveryDecidedAt?: string; createdAt: string
}
export type ProfileUpdateProposal = {
  id: string; profileId: string; appliedProfileId?: string
  // Set when the change was learned from one project's records and applies to that project only.
  projectId?: string | null; projectProfileId?: string | null; appliedProjectProfileId?: string
  proposedChanges: { blockMinutes: { from: number; to: number } }
  reason: string; evidenceRecordIds: string[]; ruleVersion: string
  status: 'pending' | 'approved' | 'rejected'; createdAt: string; decidedAt: string | null
}

export type ExecutionSummary = {
  revision: number; days: number; periodStart: string; periodEnd: string
  planId: string | null; profileId: string | null; recordCount: number
  resultCounts: Record<ExecutionRecord['result'], number>
  completionRate: number | null
  plannedMinutes: number; actualMinutes: number; minutesDifference: number
  actualMinutesRecordCount: number
  incompleteReasonCounts: Record<string, number>; evidenceRecordIds: string[]
}

export type LearnedPattern = {
  id: string; observation: string; proposedChanges: Record<string, { from: number; to: number }>
  evidenceRecordIds: string[]; approvedProposalId: string; projectId: string | null
  status: 'active' | 'revoked' | 'superseded'; approvedAt: string; expiresAt: string | null
}
export type UserProfile = ExecutionProfile & {
  userId: string; version: number; schemaVersion: '2.0'; declaredFacts: ExecutionAnswers
  learnedPatterns: LearnedPattern[]; updatedAt: string; confirmedAt: string | null
  surveyResponseId: string | null
}
export type SurveyResponse = {
  id: string; userId: string; surveyVersion: string; answers: ExecutionAnswers
  submittedAt: string; conversationId?: string
}
export type PlanningContext = {
  schemaVersion: '1.0'; userId: string; profileId: string; profileVersion: number; generatedAt: string
  userProfile: { declaredFacts: Omit<ExecutionAnswers, 'constraints' | 'context'>;
    planningPreferences: ExecutionProfile['planningPreferences']; learnedPatterns: LearnedPattern[] }
  projectContext: Pick<Project, 'id' | 'title' | 'goal' | 'startDate' | 'dueDate'> | null
  availability: { timezone: string; slots: AvailabilitySlot[] }; memories: Memory[]; warnings: string[]
}
