import { expect, it } from 'vitest'
import { withoutOldSeeds } from './oldSeeds'
import type { CalendarEvent, ExecutionState, Memory, Milestone, Project } from './types'

it('drops untouched sample data the planner never used, and nothing else', () => {
  const projects = [
    { id: 'project-planner', title: 'AI 플래너 MVP' }, { id: 'project-portfolio', title: '포트폴리오 정리' }, { id: 'mine', title: '토익' },
  ] as Project[]
  const milestones = [
    { id: 'milestone-schema', projectId: 'project-planner', title: 'DB 스키마 설계' }, { id: 'm2', projectId: 'mine', title: 'LC 1회' },
  ] as Milestone[]
  const events = [{ id: 'event-class', title: '고정 수업' }, { id: 'e2', title: '고정 수업' }] as CalendarEvent[]
  const memories = [
    { id: 'memory-1', content: '평일에는 오후 7시 이후에 집중 작업을 배치하는 편이에요.' },
    { id: 'memory-2', content: '아침이 좋아요' },
  ] as Memory[]
  // The user already talked to the planner about the sample portfolio project: it is theirs now.
  const execution = { plannerThreads: { 'project-portfolio': { messages: [], action: null } } } as unknown as ExecutionState

  const clean = withoutOldSeeds({ projects, milestones, events, memories }, execution)

  expect(clean.projects.map(p => p.id)).toEqual(['project-portfolio', 'mine'])
  expect(clean.milestones.map(m => m.id)).toEqual(['m2'])
  expect(clean.events.map(e => e.id)).toEqual(['e2'])
  expect(clean.memories.map(m => m.id)).toEqual(['memory-2'])
  expect(clean.removed).toEqual(['예시 프로젝트 ‘AI 플래너 MVP’', '예시 일정 ‘고정 수업’', '예시 기억'])

  const edited = withoutOldSeeds({ projects: [], milestones: [], events: [], memories: [{ ...memories[0], content: '평일 저녁 9시 이후' }] }, execution)
  expect(edited.removed).toEqual([])
})
