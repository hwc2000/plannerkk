import type { CalendarEvent, ExecutionPlan, ExecutionState, Memory, Project } from '../../shared/types'

type ReplanInput = {
  goal: string
  startDate: string
  consent: boolean
  memories?: Memory[]
  project: ExecutionPlan['project']
  existingTasks: Array<{ title: string; startDate: string; dueDate: string; estimatedHours: number; status: string }>
  events: Array<{ date: string; startTime: string; endTime: string }>
}

export async function executionApi(path = '', body?: unknown, method = 'POST'): Promise<ExecutionState> {
  const response = await fetch(`/api/execution${path}`, body === undefined ? undefined : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '입력값 또는 서버 연결을 확인해 주세요.')
  if (!Number.isInteger(data.revision) || !data.settings) throw new Error('서버 응답 형식이 올바르지 않습니다.')
  return data
}

export async function approveProposalAndReplan(
  state: ExecutionState,
  proposalId: string,
  input: ReplanInput,
): Promise<ExecutionState> {
  if (state.plan && !input.consent) throw new Error('재계획을 위한 LLM 전송에 동의해 주세요.')
  const proposal = state.profileUpdateProposals?.find(item => item.id === proposalId)
  const approved = proposal?.status === 'approved'
    ? state
    : await executionApi(`/proposals/${proposalId}/approve`, { revision: state.revision })
  if (!state.plan) return approved
  return executionApi('/plan', {
    revision: approved.revision,
    ...input,
    profileChangeProposalId: proposalId,
  })
}

export function projectContext(project: Project | undefined) {
  if (!project) return null
  const { id, title, goal, startDate, dueDate } = project
  return { id, title, goal, startDate, dueDate }
}

export function planCalendarEvents(plan: ExecutionPlan | null, projects: Project[]): CalendarEvent[] {
  if (!plan || plan.status !== 'confirmed') return []
  return plan.entries.filter(e => e.kind === 'task').map(e => ({
    id: `execution:${plan.id}:${e.id}`, title: `${e.completed ? '✓ ' : ''}${e.title}`,
    date: e.start.slice(0, 10), startTime: e.start.slice(11, 16), endTime: e.end.slice(11, 16),
    projectId: projects.some(p => p.id === plan.projectId) ? plan.projectId ?? undefined : undefined,
    isFixed: false,
  }))
}

export function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
