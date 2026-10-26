import type { CalendarEvent, ExecutionState, Memory, Milestone, Project } from './types'

/**
 * Sample data that older versions put into every new browser.  The planner sent it to the AI as the
 * user's own: the class blocked hours, the memory went in as an approved memory.
 */
const SEEDS = {
  projects: { 'project-planner': 'AI 플래너 MVP', 'project-portfolio': '포트폴리오 정리' } as Record<string, string>,
  milestones: { 'milestone-schema': 'DB 스키마 설계', 'milestone-ui': '화면 흐름 검토' } as Record<string, string>,
  events: { 'event-class': '고정 수업' } as Record<string, string>,
  memories: { 'memory-1': '평일에는 오후 7시 이후에 집중 작업을 배치하는 편이에요.' } as Record<string, string>,
}
export const SEED_CLEANUP_KEY = 'replan-seed-cleanup-v1'

type Data = { projects: Project[]; milestones: Milestone[]; events: CalendarEvent[]; memories: Memory[] }

/**
 * The browser's data without those samples.  Only an item the user never changed goes, and a sample
 * project only when the planner never used it (no conversation, plan, settings or ending).
 */
export function withoutOldSeeds(data: Data, execution: ExecutionState): Data & { removed: string[] } {
  const used = (id: string) => !!(execution.plannerThreads?.[id] || execution.projectProfiles?.[id] || execution.closedProjects?.[id]
    || [execution.plan, execution.planDraft].some(plan => plan?.projectId === id || plan?.projects?.some(p => p.id === id)))
  const projects = data.projects.filter(p => !(SEEDS.projects[p.id] === p.title && !used(p.id)))
  const gone = new Set(data.projects.filter(p => !projects.includes(p)).map(p => p.id))
  const milestones = data.milestones.filter(m => !(SEEDS.milestones[m.id] === m.title && gone.has(m.projectId)))
  const events = data.events.filter(e => SEEDS.events[e.id] !== e.title)
  const memories = data.memories.filter(m => SEEDS.memories[m.id] !== m.content)
  const removed = [
    ...data.projects.filter(p => gone.has(p.id)).map(p => `예시 프로젝트 ‘${p.title}’`),
    ...data.events.filter(e => !events.includes(e)).map(e => `예시 일정 ‘${e.title}’`),
    ...data.memories.filter(m => !memories.includes(m)).map(() => '예시 기억'),
  ]
  return { projects, milestones, events, memories, removed }
}
