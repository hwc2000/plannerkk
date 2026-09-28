import { describe, expect, it } from 'vitest'
import { draftTasksToMilestones, ensureDraftWithinProject, normalizePlanDraft } from './aiPlan'

const project = {
  id: 'project-1',
  startDate: '2026-09-27',
  dueDate: '2026-10-10',
}

describe('normalizePlanDraft', () => {
  it('accepts a valid structured AI draft', () => {
    expect(normalizePlanDraft({
      summary: '실행 가능한 세 단계로 나눴습니다.',
      tasks: [
        {
          title: '요구사항 정리',
          startDate: '2026-09-28',
          dueDate: '2026-09-29',
          estimatedHours: 2,
        },
      ],
    })).toEqual({
      summary: '실행 가능한 세 단계로 나눴습니다.',
      tasks: [
        {
          title: '요구사항 정리',
          startDate: '2026-09-28',
          dueDate: '2026-09-29',
          estimatedHours: 2,
        },
      ],
    })
  })

  it('rejects malformed dates and reversed ranges', () => {
    expect(() => normalizePlanDraft({
      summary: '잘못된 응답',
      tasks: [{
        title: '역순 일정',
        startDate: '2026-09-30',
        dueDate: '2026-09-28',
        estimatedHours: 1,
      }],
    })).toThrow('AI 계획 응답')
  })

  it('rejects oversized text before client persistence', () => {
    expect(() => normalizePlanDraft({
      summary: '요약',
      tasks: [{
        title: '가'.repeat(121),
        startDate: '2026-09-28',
        dueDate: '2026-09-29',
        estimatedHours: 1,
      }],
    })).toThrow('AI 계획 응답')
  })
})

describe('ensureDraftWithinProject', () => {
  it('rejects generated tasks outside the selected project period', () => {
    const draft = normalizePlanDraft({
      summary: '기간 밖 일정',
      tasks: [{
        title: '너무 늦은 작업',
        startDate: '2026-10-11',
        dueDate: '2026-10-12',
        estimatedHours: 2,
      }],
    })

    expect(() => ensureDraftWithinProject(draft, {
      startDate: '2026-09-27',
      dueDate: '2026-10-10',
    })).toThrow('프로젝트 기간')
  })
})

describe('draftTasksToMilestones', () => {
  it('converts reviewed tasks to project milestones without mutating the draft', () => {
    const draft = {
      summary: '두 단계',
      tasks: [
        {
          title: '자료 조사',
          startDate: '2026-09-28',
          dueDate: '2026-09-29',
          estimatedHours: 2,
        },
        {
          title: '초안 작성',
          startDate: '2026-09-30',
          dueDate: '2026-10-01',
          estimatedHours: 3,
        },
      ],
    }

    const milestones = draftTasksToMilestones(project, draft, () => 'fixed-id')

    expect(milestones).toEqual([
      {
        id: 'fixed-id-1',
        projectId: 'project-1',
        title: '자료 조사',
        startDate: '2026-09-28',
        dueDate: '2026-09-29',
        estimatedHours: 2,
        status: 'todo',
      },
      {
        id: 'fixed-id-2',
        projectId: 'project-1',
        title: '초안 작성',
        startDate: '2026-09-30',
        dueDate: '2026-10-01',
        estimatedHours: 3,
        status: 'todo',
      },
    ])
    expect(draft.tasks[0].title).toBe('자료 조사')
  })

  it('normalizes and validates the draft against the current project immediately before conversion', () => {
    expect(() => draftTasksToMilestones(project, {
      summary: '기간 밖 일정',
      tasks: [{
        title: '늦은 작업',
        startDate: '2026-10-10',
        dueDate: '2026-10-11',
        estimatedHours: 2,
      }],
    })).toThrow('프로젝트 기간')

    expect(() => draftTasksToMilestones(project, {
      summary: '잘못된 일정',
      tasks: [{
        title: '잘못된 작업',
        startDate: 'not-a-date',
        dueDate: '2026-10-01',
        estimatedHours: 2,
      }],
    })).toThrow('AI 계획 응답')
  })
})
