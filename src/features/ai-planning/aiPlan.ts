import type { Milestone, Project } from '../../shared/types'

export type AiPlanTask = {
  title: string
  startDate: string
  dueDate: string
  estimatedHours: number
}

export type AiPlanDraft = {
  summary: string
  tasks: AiPlanTask[]
}

const datePattern = /^\d{4}-\d{2}-\d{2}$/

function isValidIsoDate(value: string): boolean {
  if (!datePattern.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function isValidTask(value: unknown): value is AiPlanTask {
  if (!value || typeof value !== 'object') return false
  const task = value as Partial<AiPlanTask>
  return typeof task.title === 'string'
    && task.title.trim().length > 0
    && task.title.trim().length <= 120
    && typeof task.startDate === 'string'
    && isValidIsoDate(task.startDate)
    && typeof task.dueDate === 'string'
    && isValidIsoDate(task.dueDate)
    && task.startDate <= task.dueDate
    && typeof task.estimatedHours === 'number'
    && Number.isFinite(task.estimatedHours)
    && task.estimatedHours > 0
    && task.estimatedHours <= 1000
}

export function normalizePlanDraft(value: unknown): AiPlanDraft {
  if (!value || typeof value !== 'object') throw new Error('AI 계획 응답 형식이 올바르지 않습니다.')
  const draft = value as Partial<AiPlanDraft>
  if (typeof draft.summary !== 'string'
    || draft.summary.trim().length < 1
    || draft.summary.trim().length > 500
    || !Array.isArray(draft.tasks)
    || draft.tasks.length < 1
    || draft.tasks.length > 12
    || !draft.tasks.every(isValidTask)) {
    throw new Error('AI 계획 응답 형식이 올바르지 않습니다.')
  }
  return {
    summary: draft.summary.trim(),
    tasks: draft.tasks.map((task) => ({ ...task, title: task.title.trim() })),
  }
}

export function ensureDraftWithinProject(
  draft: AiPlanDraft,
  project: Pick<ProjectPeriod, 'startDate' | 'dueDate'>,
): AiPlanDraft {
  if (draft.tasks.some((task) => (
    task.startDate < project.startDate || task.dueDate > project.dueDate
  ))) {
    throw new Error('AI 계획에 프로젝트 기간을 벗어난 할 일이 있습니다.')
  }
  return draft
}

type ProjectPeriod = {
  startDate: string
  dueDate: string
}

export function draftTasksToMilestones(
  project: Pick<Project, 'id' | 'startDate' | 'dueDate'>,
  draft: unknown,
  idFactory: () => string = () => crypto.randomUUID(),
): Milestone[] {
  const validDraft = ensureDraftWithinProject(normalizePlanDraft(draft), project)
  return validDraft.tasks.map((task, index) => ({
    id: `${idFactory()}-${index + 1}`,
    projectId: project.id,
    title: task.title.trim(),
    startDate: task.startDate,
    dueDate: task.dueDate,
    estimatedHours: task.estimatedHours,
    status: 'todo',
  }))
}

export async function requestPlanDraft(input: {
  goal: string
  project: { id: string; title: string; goal: string; startDate: string; dueDate: string }
  existingTasks: Array<Pick<Milestone, 'title' | 'startDate' | 'dueDate' | 'estimatedHours' | 'status'>>
}): Promise<AiPlanDraft> {
  const response = await fetch('/api/ai/plan-draft', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      goal: input.goal,
      project: {
        id: input.project.id, title: input.project.title, goal: input.project.goal,
        startDate: input.project.startDate, dueDate: input.project.dueDate,
      },
      existingTasks: input.existingTasks.map(({title, startDate, dueDate, estimatedHours, status}) =>
        ({title, startDate, dueDate, estimatedHours, status})),
    }),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail
      : response.status === 422
        ? '입력 내용을 확인해 주세요. 요청은 3자 이상, 프로젝트 목표와 기간은 필수이며 기존 할 일의 예상 시간은 0보다 커야 합니다.'
        : 'AI 계획을 만들지 못했습니다.'
    throw new Error(detail)
  }
  const draft = normalizePlanDraft(payload)
  return ensureDraftWithinProject(draft, input.project)
}
