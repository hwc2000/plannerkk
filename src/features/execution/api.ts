import type { CalendarEvent, ClosePreview, ExecutionPlan, ExecutionState, InsightPattern, InsightQuestion, InsightSlot, Memory, Milestone, ProfileUpdateProposal, Project } from '../../shared/types'

type ReplanInput = {
  goal: string
  startDate: string
  consent: boolean
  memories?: Memory[]
  project: ExecutionPlan['project']
  existingTasks: Array<{ title: string; startDate: string; dueDate: string; estimatedHours: number; status: string }>
  events: Array<{ date: string; startTime: string; endTime: string }>
}

async function requestState(url: string, body?: unknown, method = 'POST'): Promise<ExecutionState> {
  const response = await fetch(url, body === undefined ? undefined : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => ({}))
  if (response.status === 401) window.dispatchEvent(new Event('replan:unauthorized'))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '입력값 또는 서버 연결을 확인해 주세요.')
  if (!Number.isInteger(data.revision) || !data.settings) throw new Error('서버 응답 형식이 올바르지 않습니다.')
  return data
}

export async function executionApi(path = '', body?: unknown, method = 'POST'): Promise<ExecutionState> {
  return requestState(`/api/execution${path}`, body, method)
}

/** A lost response is not a failed save when the exact session was committed. */
export async function confirmCheckIn(state: ExecutionState, project: Project, actionId?: string): Promise<ExecutionState> {
  try {
    return await executionApi('/chat/check-in/confirm', { revision: state.revision, project: projectContext(project), ...(actionId ? { actionId } : {}) })
  } catch (error) {
    if (actionId) {
      try {
        const fresh = await executionApi()
        if (fresh.checkInSessions?.some(session => session.id === actionId && session.projectId === project.id)) return fresh
      } catch { /* Preserve the original failure when the outcome cannot be verified. */ }
    }
    throw error
  }
}

export async function adaptiveApi(path: string, body: unknown): Promise<ExecutionState> {
  return requestState(`/api/adaptive${path}`, body)
}

/** The fields the planner learns about the user, and the few a check-in would ask next. */
export async function fetchInsights(): Promise<{ slots: InsightSlot[]; next: InsightQuestion[]; candidatePatterns?: InsightPattern[] }> {
  const response = await fetch('/api/execution/insights')
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '알게 된 것을 불러오지 못했어요.')
  return data
}

/** What ending a project would carry to the user profile; nothing changes until the user ends it. */
export async function closePreview(projectId: string): Promise<ClosePreview> {
  const response = await fetch(`/api/execution/projects/${encodeURIComponent(projectId)}/close-preview`)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '미리보기를 불러오지 못했어요.')
  return data
}

function entryOwner(plan: ExecutionPlan, entry: ExecutionPlan['entries'][number]): string | null {
  return entry.projectId ?? plan.projectId ?? null
}

/** The settings version an entry's own project had when it was planned (older entries share the plan's). */
function entrySettings(plan: ExecutionPlan, entry: ExecutionPlan['entries'][number]): string | null {
  if (entry.projectProfileId !== undefined) return entry.projectProfileId ?? null
  return entryOwner(plan, entry) === plan.projectId ? plan.projectProfileId ?? null : null
}

/**
 * A user-profile change replans the current week; a project's change replans only that
 * project's open tasks, and only when this week has some.
 */
export function replansCurrentPlan(state: ExecutionState, proposal: ProfileUpdateProposal | undefined): boolean {
  const plan = state.plan
  if (!plan) return false
  if (!proposal?.projectId) return true
  return plan.entries.some(e => e.kind === 'task' && !e.completed && entryOwner(plan, e) === proposal.projectId)
}

/** Projects whose open tasks were planned with settings that changed since; the rest of the week is still current. */
export function staleProjectIds(state: ExecutionState, plan: ExecutionPlan): Array<string | null> {
  const current = (id: string | null) => (id ? state.projectProfiles?.[id]?.id ?? null : null)
  const ids = plan.entries
    .filter(e => e.kind === 'task' && !e.completed && entrySettings(plan, e) !== current(entryOwner(plan, e)))
    .map(e => entryOwner(plan, e))
  return [...new Set(ids)]
}

/** The plan was made with a user profile that has since changed, or some project's settings did. */
export function planIsStale(state: ExecutionState, plan: ExecutionPlan): boolean {
  return state.profile?.id !== plan.profileId || staleProjectIds(state, plan).length > 0
}

export async function approveProposalAndReplan(
  state: ExecutionState,
  proposalId: string,
  input: ReplanInput,
): Promise<ExecutionState> {
  const proposal = state.profileUpdateProposals?.find(item => item.id === proposalId)
  const replan = replansCurrentPlan(state, proposal)
  if (replan && !input.consent) throw new Error('재계획을 위한 LLM 전송에 동의해 주세요.')
  const approved = proposal?.status === 'approved'
    ? state
    : await executionApi(`/proposals/${proposalId}/approve`, { revision: state.revision })
  if (!replan) return approved
  return executionApi('/plan', {
    revision: approved.revision,
    ...input,
    profileChangeProposalId: proposalId,
  })
}

export function projectContext(project: Project | undefined) {
  if (!project) return null
  const { id, title, goal, startDate, dueDate } = project
  return { id, title, goal: goal.trim() || title, startDate, dueDate }
}

export function planProjectIds(plan: ExecutionPlan | null | undefined): string[] {
  if (!plan) return []
  if (plan.projects?.length) return plan.projects.map(p => p.id)
  return plan.projectId ? [plan.projectId] : []
}

export function existingTasksFor(milestones: Milestone[], projectIds: string[]) {
  return milestones.filter(m => projectIds.includes(m.projectId)).map(
    ({ title, startDate, dueDate, estimatedHours, status, projectId }) => ({ title, startDate, dueDate, estimatedHours, status, projectId }),
  )
}

export function planCalendarEvents(plan: ExecutionPlan | null, projects: Project[]): CalendarEvent[] {
  if (!plan || plan.status !== 'confirmed') return []
  return plan.entries.filter(e => e.kind === 'task').map(e => ({
    id: `execution:${plan.id}:${e.id}`, title: `${e.completed ? '✓ ' : ''}${e.title}`,
    date: e.start.slice(0, 10), startTime: e.start.slice(11, 16), endTime: e.end.slice(11, 16),
    projectId: projects.find(p => p.id === (e.projectId ?? plan.projectId))?.id,
    isFixed: false,
  }))
}

export function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
