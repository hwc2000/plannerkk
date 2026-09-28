// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AiPlanningView } from './AiPlanningView'
import type { AiPlanDraft } from './aiPlan'
import type { Project } from '../../shared/types'

const projects: Project[] = [{
  id: 'project-1',
  title: 'PlannerKK',
  goal: 'AI 플래너 완성',
  startDate: '2026-09-27',
  dueDate: '2026-10-10',
  priority: 'high',
  status: 'active',
}]

const secondProject: Project = {
  id: 'project-2',
  title: '두 번째 프로젝트',
  goal: '별도 프로젝트',
  startDate: '2026-09-27',
  dueDate: '2026-10-10',
  priority: 'medium',
  status: 'active',
}

const draft: AiPlanDraft = {
  summary: '두 단계로 나눴습니다.',
  tasks: [{
    title: 'API 연결',
    startDate: '2026-09-28',
    dueDate: '2026-09-29',
    estimatedHours: 2,
  }],
}

afterEach(cleanup)

describe('AiPlanningView', () => {
  it('shows a draft first and applies it only after explicit review', async () => {
    const requestDraft = vi.fn().mockResolvedValue(draft)
    const onApply = vi.fn()
    render(
      <AiPlanningView
        projects={projects}
        milestones={[]}
        selectedProjectId="project-1"
        onSelectProject={() => {}}
        onApply={onApply}
        requestDraft={requestDraft}
      />,
    )

    fireEvent.change(screen.getByLabelText('AI에게 요청할 내용'), {
      target: { value: 'API 연동 계획을 만들어줘' },
    })
    fireEvent.click(screen.getByRole('button', { name: '계획 초안 만들기' }))

    await screen.findByText('API 연결')
    expect(onApply).not.toHaveBeenCalled()
    expect(screen.getByText('두 단계로 나눴습니다.')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '검토 후 단계별 할 일에 반영' }))

    await waitFor(() => expect(onApply).toHaveBeenCalledWith('project-1', draft))
  })

  it('locks project selection while a draft request is in flight', () => {
    const requestDraft = vi.fn(() => new Promise<AiPlanDraft>(() => {}))
    render(
      <AiPlanningView
        projects={projects}
        milestones={[]}
        selectedProjectId="project-1"
        onSelectProject={() => {}}
        onApply={() => {}}
        requestDraft={requestDraft}
      />,
    )

    fireEvent.change(screen.getByLabelText('AI에게 요청할 내용'), {
      target: { value: 'API 연동 계획을 만들어줘' },
    })
    fireEvent.click(screen.getByRole('button', { name: '계획 초안 만들기' }))

    expect((screen.getByRole('combobox', { name: '프로젝트' }) as HTMLSelectElement).disabled).toBe(true)
  })

  it('discards a resolved draft when the selected project changed during the request', async () => {
    let resolveDraft!: (value: AiPlanDraft) => void
    const requestDraft = vi.fn(() => new Promise<AiPlanDraft>((resolve) => { resolveDraft = resolve }))
    const onApply = vi.fn()
    const { rerender } = render(
      <AiPlanningView
        projects={[...projects, secondProject]}
        milestones={[]}
        selectedProjectId="project-1"
        onSelectProject={() => {}}
        onApply={onApply}
        requestDraft={requestDraft}
      />,
    )

    fireEvent.change(screen.getByLabelText('AI에게 요청할 내용'), {
      target: { value: '첫 프로젝트 계획을 만들어줘' },
    })
    fireEvent.click(screen.getByRole('button', { name: '계획 초안 만들기' }))

    rerender(
      <AiPlanningView
        projects={[...projects, secondProject]}
        milestones={[]}
        selectedProjectId="project-2"
        onSelectProject={() => {}}
        onApply={onApply}
        requestDraft={requestDraft}
      />,
    )
    resolveDraft(draft)

    await screen.findByRole('alert')
    expect(screen.queryByText('API 연결')).toBeNull()
    expect(screen.getByRole('alert').textContent).toContain('다시 요청')
    expect(onApply).not.toHaveBeenCalled()
  })

  it.each([
    ['was deleted', [secondProject], 'project-1'],
    ['had its period changed', [{ ...projects[0], dueDate: '2026-10-09' }, secondProject], 'project-1'],
  ])('discards a resolved draft when the requested project %s', async (_reason, nextProjects, nextSelectedProjectId) => {
    let resolveDraft!: (value: AiPlanDraft) => void
    const requestDraft = vi.fn(() => new Promise<AiPlanDraft>((resolve) => { resolveDraft = resolve }))
    const onApply = vi.fn()
    const { rerender } = render(
      <AiPlanningView
        projects={[...projects, secondProject]}
        milestones={[]}
        selectedProjectId="project-1"
        onSelectProject={() => {}}
        onApply={onApply}
        requestDraft={requestDraft}
      />,
    )

    fireEvent.change(screen.getByLabelText('AI에게 요청할 내용'), {
      target: { value: '첫 프로젝트 계획을 만들어줘' },
    })
    fireEvent.click(screen.getByRole('button', { name: '계획 초안 만들기' }))
    rerender(
      <AiPlanningView
        projects={nextProjects}
        milestones={[]}
        selectedProjectId={nextSelectedProjectId}
        onSelectProject={() => {}}
        onApply={onApply}
        requestDraft={requestDraft}
      />,
    )
    resolveDraft(draft)

    await screen.findByRole('alert')
    expect(screen.queryByText('API 연결')).toBeNull()
    expect(screen.getByRole('alert').textContent).toContain('다시 요청')
    expect(onApply).not.toHaveBeenCalled()
  })

  it('does not request a plan when the instruction is blank', () => {
    const requestDraft = vi.fn()
    render(
      <AiPlanningView
        projects={projects}
        milestones={[]}
        selectedProjectId="project-1"
        onSelectProject={() => {}}
        onApply={() => {}}
        requestDraft={requestDraft}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '계획 초안 만들기' }))

    expect(requestDraft).not.toHaveBeenCalled()
    expect(screen.getByText('요청 내용을 입력해주세요.')).toBeTruthy()
  })
})
