// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ProjectAttention } from './ProjectAttention'
import type { AttentionItem, ExecutionState, Project } from '../../shared/types'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear() })

const essay = { id: 'essay', title: '에세이', goal: '초안', startDate: '2030-01-01', dueDate: '2030-01-31', status: 'active' } as Project
const gym = { id: 'gym', title: '운동', goal: '주 3회', startDate: '2030-01-01', dueDate: '2030-01-31', status: 'paused' } as Project
const state = { revision: 4, plan: { id: 'week1' }, closedProjects: {} } as unknown as ExecutionState
const idle: AttentionItem = {
  projectId: 'essay', title: '에세이', dueDate: '2030-01-31', kind: 'idle', silentInRow: 3,
  tasks: [{ taskId: 't7', title: '서론', start: '2030-01-07T18:00', minutes: 30 },
    { taskId: 't8', title: '본론', start: '2030-01-08T18:00', minutes: 30 }],
}

function serve(items: AttentionItem[]) {
  const calls: Array<{ url: string; body: unknown }> = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url, body })
    const data = url.endsWith('/attention') ? { items } : { ...state, revision: 5, settings: {} }
    return { ok: true, status: 200, json: async () => data } as Response
  }))
  return calls
}

function show(props: Partial<Parameters<typeof ProjectAttention>[0]> = {}) {
  const run = vi.fn(async (action: () => Promise<ExecutionState>) => { await action(); return true })
  render(<ProjectAttention state={state} projects={[essay, gym]} busy={false} run={run} onCloseProject={vi.fn()} {...props}/>)
  return run
}

it('asks only about open projects, and offers a break or a new plan for a silent one', async () => {
  const calls = serve([idle])
  const pause = vi.fn(); const openProject = vi.fn()
  show({ onPause: pause, onOpenProject: openProject })
  expect(await screen.findByText(/최근 계획한 작업 3개에 기록이 없어요/)).toBeTruthy()
  const sent = (calls[0].body as { projects: Array<{ id: string }> }).projects.map(p => p.id)
  expect(sent).toEqual(['essay'])  // the paused project is never asked about
  fireEvent.click(screen.getByText('잠시 쉬기'))
  expect(pause).toHaveBeenCalledWith('essay')
  fireEvent.click(screen.getByText('다시 계획하기'))
  expect(openProject).toHaveBeenCalledWith('essay')
})

it('records missed tasks afterwards by result only, unknown by default', async () => {
  const calls = serve([idle])
  show()
  fireEvent.click(await screen.findByText('밀린 기록 남기기 · 2개'))
  fireEvent.click(screen.getAllByText('끝냈어요')[0])
  fireEvent.click(screen.getByText('기록 저장'))
  await waitFor(() => expect(calls.some(c => c.url.endsWith('/records/late'))).toBe(true))
  const late = calls.find(c => c.url.endsWith('/records/late'))!.body
  expect(late).toEqual({ revision: 4, planId: 'week1', items: [
    { taskId: 't7', result: 'completed' }, { taskId: 't8', result: 'incomplete' }] })
})

it('offers a longer deadline for an overdue project and stays quiet for a week after "later"', async () => {
  serve([{ ...idle, kind: 'overdue', tasks: [] }])
  const edit = vi.fn()
  show({ onEditProject: edit })
  fireEvent.click(await screen.findByText('기간 늘리기'))
  expect(edit).toHaveBeenCalledWith('essay')
  expect(screen.queryByText(/밀린 기록 남기기/)).toBeNull()
  fireEvent.click(screen.getByText('나중에'))
  await waitFor(() => expect(screen.queryByLabelText('확인할 프로젝트')).toBeNull())
})
