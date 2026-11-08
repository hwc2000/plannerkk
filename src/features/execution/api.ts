import type { AvailabilitySlot, CalendarEvent, ClosePreview, ExecutionPlan, ExecutionState, InsightPattern, InsightQuestion, InsightSlot, Memory, Milestone, ProfileUpdateProposal, Project } from '../../shared/types'

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
  try {
    return await executionApi('/plan', {
      revision: approved.revision,
      ...input,
      profileChangeProposalId: proposalId,
    })
  } catch (error) {
    // Late in the week no chosen time may be left to replan in: the change is saved and applies from the next plan.
    if (error instanceof Error && NO_TIME_LEFT.test(error.message)) return approved
    throw error
  }
}

const NO_TIME_LEFT = /사용 가능한 시간이 없습니다|계획할 시간이 남지 않았습니다/

export function projectContext(project: Project | undefined) {
  if (!project) return null
  const { id, title, goal, startDate, dueDate } = project
  return { id, title, goal: goal.trim() || title, startDate, dueDate }
}

const WEEKDAYS = '월화수목금토일'

/** '월·수·금 19~20시' for the hours a project is done in; [] is "no fixed time". */
export function hoursText(slots: AvailabilitySlot[] | null | undefined) {
  if (slots == null) return '아직 안 정함'
  if (!slots.length) return '정해진 시간 없음'
  const byDay = new Map<number, number[]>()
  for (const s of [...slots].sort((a, b) => a.day - b.day || a.hour - b.hour)) byDay.set(s.day, [...(byDay.get(s.day) ?? []), s.hour])
  const groups = new Map<string, string[]>()
  for (const [day, hours] of byDay) {
    const ranges: string[] = []
    let start = hours[0], end = hours[0] + 1
    for (const hour of hours.slice(1)) {
      if (hour === end) { end = hour + 1; continue }
      ranges.push(`${start}~${end}시`); start = hour; end = hour + 1
    }
    ranges.push(`${start}~${end}시`)
    const key = ranges.join(', ')
    groups.set(key, [...(groups.get(key) ?? []), WEEKDAYS[day]])
  }
  return [...groups].map(([hours, days]) => `${days.join('·')} ${hours}`).join(' / ')
}

/** Save the hours a project is done in, keeping the other values the user set for it. */
export function saveProjectHours(state: ExecutionState, projectId: string, slots: AvailabilitySlot[]) {
  const declared = Object.fromEntries(Object.entries(state.projectProfiles?.[projectId]?.overrides ?? {})
    .filter(([, item]) => item.source === 'declared').map(([key, item]) => [key, item.value]))
  return executionApi(`/projects/${encodeURIComponent(projectId)}/profile`,
    { revision: state.revision, overrides: { ...declared, timeSlots: slots } }, 'PUT')
}

/** The other open projects of the week: a plan asked for in one project's chat plans them too when they have no tasks yet. */
export function weekProjects(projects: Project[], closed: Record<string, unknown> | undefined, startDate: string) {
  const end = new Date(`${startDate}T00:00:00`)
  end.setDate(end.getDate() + 6)
  const last = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`
  return projects
    .filter(p => p.status === 'active' && !closed?.[p.id] && p.startDate <= last && p.dueDate >= startDate)
    .map(p => projectContext(p)!)
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
