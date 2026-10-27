// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CheckIn, checkInTasks, type CheckInDraft } from './CheckIn'
import { AboutMe } from './AboutMe'
import { PlannerChat } from './PlannerChat'
import { ExecutionView } from './ExecutionView'
import { confirmCheckIn } from './api'
import type { ExecutionState, Project } from '../../shared/types'
import { dateKey } from '../../shared/constants'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const a = { id: 'a', title: '에세이', goal: '초안', startDate: '2020-01-01', dueDate: '2030-12-31', priority: 'high', status: 'active' } as Project
const b = { ...a, id: 'b', title: '발표' }
function state(count = 1): ExecutionState {
  return { revision: 9, profile: { id: 'p', planningPreferences: {}, insights: {}, facts: {} }, profileDraft: null,
    settings: { slots: [{ day: 0, hour: 18 }], view: 'timeline' }, llmAvailable: true, model: 'test', planDraft: null,
    plan: { id: 'plan', projectId: 'a', project: a, status: 'confirmed', startDate: '2020-01-01', endDate: '2030-12-31', pendingTasks: [], entries: Array.from({ length: count }, (_, i) => ({ id: `t${i}`, projectId: 'a', kind: 'task', title: `작업${i}`, start: '2020-01-01T18:00', end: '2020-01-01T18:30', minutes: 30, completed: false })) },
  } as unknown as ExecutionState
}
const run = vi.fn(async (action: () => Promise<ExecutionState>) => { await action(); return true })
function props(s = state()) { return { state: s, project: a, busy: false, run, consent: true, onConsent: vi.fn(), onClose: vi.fn() } }
function insights() { vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ slots: [], next: Array.from({ length: 6 }, (_, i) => ({ key: `q${i}`, question: `선택 질문 ${i}` })) }) })) }
it('uses the Korean calendar date for check-in eligibility and known daily context', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-27T15:30:00Z'))
  try {
    const s = state()
    s.plan!.entries[0].start = '2026-10-28T09:00'
    s.checkInSessions = [{ id: 'today', date: '2026-10-28', projectId: 'b', place: '집', focus: 'good', atmosphere: 'quiet', condition: 'ok', note: '' }]
    expect(checkInTasks(s, 'a').due).toHaveLength(1)
    render(<CheckIn {...props(s)} draft={{ planId: 'plan', tasks: s.plan!.entries, results: { t0: 'completed' }, step: 'details', questions: [], said: '', text: '', note: '' }}/>)
    expect(screen.getByText(/오늘 이미 알려 준 상태/).textContent).toContain('집')
  } finally { vi.useRealTimers() }
})
it('shows an evidence-backed place as an optional hint without changing task title', () => {
  const s = state()
  const entry = s.plan!.entries[0]
  entry.environmentSuggestion = { place: '도서관', optional: true, knownFocusDays: 4, goodFocusDays: 3 }
  render(<ExecutionView state={s} onChange={vi.fn()} projects={[a]} events={[]} milestones={[]} memories={[]} section="home"/>)
  expect(screen.getByText(/장소 제안 \(선택\): 도서관/)).toBeTruthy()
  expect(screen.getByText('작업0')).toBeTruthy()
})
it('starts a fresh batch after a completed draft instead of reopening the thank-you screen', () => {
  const draft = { planId: 'plan', tasks: [], results: {}, questions: [], step: 'done', said: '', text: '', note: '' } as CheckInDraft
  render(<CheckIn {...props()} draft={draft}/> )
  expect(screen.getByText('다 했어요')).toBeTruthy()
})
it('caps each check-in batch at twenty tasks', () => {
  render(<CheckIn {...props(state(23))}/> )
  expect(screen.getAllByRole('button', { name: '다 했어요' })).toHaveLength(20)
})
it('offers the remaining batch after twenty confirmed tasks', () => {
  const s = state(23)
  s.executionRecords = s.plan!.entries.slice(0, 20).map(t => ({ planId: 'plan', taskId: t.id, result: 'completed', checkInId: 'batch-one' })) as ExecutionState['executionRecords']
  const draft = { planId: 'plan', tasks: [], results: {}, questions: [], step: 'done', said: '', text: '', note: '' } as CheckInDraft
  render(<CheckIn {...props(s)} draft={draft}/> )
  expect(screen.getAllByRole('button', { name: '다 했어요' })).toHaveLength(3)
  expect(screen.getByText('작업20')).toBeTruthy()
  expect(screen.queryByText('작업0')).toBeNull()
})
it('does not mistake a different project session for committed confirmation', async () => {
  const failure = new Error('confirmation failed')
  const fresh = { ...state(), checkInSessions: [{ id: 'same-id', projectId: 'b', date: dateKey(new Date()) }] }
  vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce({ ok: true, json: async () => fresh }))
  await expect(confirmCheckIn(state(), a, 'same-id')).rejects.toBe(failure)
})
it('asks broad optional daily context once, with at most three optional followups and back navigation', async () => {
  insights()
  const s = { ...state(), checkInSessions: [{ id: 'day', date: dateKey(new Date()), projectId: 'b', place: '도서관', atmosphere: 'quiet', focus: 'good', condition: 'ok', note: '' }] } as ExecutionState
  render(<CheckIn {...props(s)}/> )
  fireEvent.click(screen.getByText('다 했어요')); fireEvent.click(screen.getByText('다음'))
  await waitFor(() => expect(screen.getByText('답해주시면 다음 계획에 도움이 돼요, 건너뛰어도 괜찮아요')).toBeTruthy())
  expect(screen.getByText(/오늘 이미 알려 준 상태/).textContent).toContain('도서관')
  expect(screen.queryByText(/어디서 했고/)).toBeNull()
  expect(screen.getAllByText(/선택 질문/)).toHaveLength(3)
  fireEvent.change(screen.getByLabelText('답하기 (선택)'), { target: { value: '내 메모' } })
  fireEvent.click(screen.getByText('이전'))
  fireEvent.click(screen.getByText('다음'))
  await waitFor(() => expect((screen.getByLabelText('답하기 (선택)') as HTMLTextAreaElement).value).toBe('내 메모'))
})
it.each(['session', 'record'] as const)('restores the exact server-card selection and %s note after a memory reset', async source => {
  const s = state(23)
  const records = [
    { taskId: 't22', taskTitle: '작업22', result: 'partial', ...(source === 'record' ? { note: '이전 설명' } : {}) },
    { taskId: 't1', taskTitle: '작업1', result: 'not_started' },
  ]
  s.plannerThreads = { a: { messages: [], action: { kind: 'check_in', id: 'resumed', projectId: 'a', valid: true, revision: 2,
    payload: { records, ...(source === 'session' ? { session: { note: '이전 설명' } } : {}) } } } } as unknown as ExecutionState['plannerThreads']
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => s })
  vi.stubGlobal('fetch', fetcher)
  render(<CheckIn {...props(s)}/> )
  fireEvent.click(screen.getByText('이전'))
  expect(screen.getAllByRole('button', { name: '다 했어요' })).toHaveLength(2)
  expect(screen.getAllByRole('button', { name: '조금 했어요' })[0].getAttribute('aria-pressed')).toBe('true')
  expect(screen.getAllByRole('button', { name: '못 했어요' })[1].getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByText('다음'))
  const input = await screen.findByLabelText('답하기 (선택)')
  fireEvent.change(input, { target: { value: '수정 설명' } })
  fireEvent.click(screen.getByText('고쳐서 다시 정리'))
  await waitFor(() => expect(fetcher.mock.calls.some(([, init]) => !!init?.body)).toBe(true))
  const [, init] = fetcher.mock.calls.find(([, init]) => !!init?.body)!
  expect(JSON.parse(init.body)).toMatchObject({ project: { id: 'a' }, text: '이전 설명\n수정 설명',
    results: [{ taskId: 't22', result: 'partial' }, { taskId: 't1', result: 'not_started' }] })
})
it('reuses server-card knownDaily as optional context without forcing it into a correction', async () => {
  const s = state()
  s.plannerThreads = { a: { messages: [], action: { kind: 'check_in', id: 'resumed', projectId: 'a', valid: true, revision: 2,
    payload: { date: dateKey(new Date()), knownDaily: { place: '도서관', focus: 'good' }, records: [{ taskId: 't0', taskTitle: '작업0', result: 'completed' }] } } } } as unknown as ExecutionState['plannerThreads']
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => s })
  vi.stubGlobal('fetch', fetcher)
  render(<CheckIn {...props(s)}/> )
  expect(screen.getByText(/오늘 이미 알려 준 상태/).textContent).toContain('도서관')
  expect(screen.getByText(/오늘의 .*원하면/).textContent).not.toContain('장소')
  fireEvent.change(screen.getByLabelText('답하기 (선택)'), { target: { value: '분량만 수정' } })
  fireEvent.click(screen.getByText('고쳐서 다시 정리'))
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  const body = JSON.parse(fetcher.mock.calls[0][1].body)
  expect(body.text).toBe('분량만 수정')
  expect(body).not.toHaveProperty('place')
  expect(body.results[0]).not.toHaveProperty('focus')
})
it('resumes a valid card despite unrelated revision changes and confirms using current revision plus actionId', async () => {
  const s = { ...state(), plannerThreads: { a: { messages: [], action: { kind: 'check_in', id: 'card', projectId: 'a', valid: true, revision: 2, payload: { records: [] } } } } } as unknown as ExecutionState
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => s }); vi.stubGlobal('fetch', fetch)
  render(<CheckIn {...props(s)}/> )
  expect(screen.getByRole('heading', { name: '에세이 · 체크인 확인' })).toBeTruthy()
  fireEvent.click(screen.getByText('확인하고 기록'))
  await waitFor(() => expect(fetch).toHaveBeenCalled())
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ revision: 9, actionId: 'card' })
  await waitFor(() => expect(screen.getByText(/작업에 배정한 시간/)).toBeTruthy())
  fireEvent.click(screen.getByText('짧았어요'))
  fireEvent.click(screen.getByText('의견 저장'))
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({ revision: 9, timeFit: 'too_short' })
  expect(JSON.parse(fetch.mock.calls[1][1].body)).not.toHaveProperty('load')
  expect(fetch.mock.calls[1][0]).toBe('/api/execution/projects/a/feedback')
  expect(JSON.parse(fetch.mock.calls[1][1].body)).not.toHaveProperty('profile')
  expect(JSON.parse(fetch.mock.calls[1][1].body)).not.toHaveProperty('overrides')
})
it('preserves check-in input across project switching and cancel/resume without showing it to another project', async () => {
  insights()
  const p = { ...props(), onApplyPlan: vi.fn() }
  const view = render(<PlannerChat {...p}/>)
  fireEvent.click(screen.getByRole('button', { name: /체크인/ }))
  fireEvent.click(screen.getByText('다 했어요')); fireEvent.click(screen.getByText('다음'))
  await waitFor(() => expect(screen.getByLabelText('답하기 (선택)')).toBeTruthy())
  fireEvent.change(screen.getByLabelText('답하기 (선택)'), { target: { value: '에세이 메모' } })
  view.rerender(<PlannerChat {...p} project={b}/>)
  expect(screen.queryByDisplayValue('에세이 메모')).toBeNull()
  view.rerender(<PlannerChat {...p}/>)
  fireEvent.click(screen.getByRole('button', { name: /체크인/ }))
  expect((screen.getByLabelText('답하기 (선택)') as HTMLTextAreaElement).value).toBe('에세이 메모')
  fireEvent.click(screen.getByText('취소·나중에 이어하기'))
  fireEvent.click(screen.getByRole('button', { name: /체크인/ }))
  expect(screen.getByDisplayValue('에세이 메모')).toBeTruthy()
})
it('keeps an in-flight chat reply and input cleanup associated with its original project', async () => {
  let finish!: (next: ExecutionState) => void
  const pending = new Promise<ExecutionState>(resolve => { finish = resolve })
  const fetch = vi.fn().mockImplementation(async () => ({ ok: true, json: async () => pending }))
  vi.stubGlobal('fetch', fetch)
  const p = { ...props(), onApplyPlan: vi.fn() }
  const view = render(<PlannerChat {...p}/> )
  fireEvent.click(screen.getByLabelText(/대화·프로필·기억/))
  fireEvent.change(screen.getByLabelText('메시지'), { target: { value: '에세이 요청' } })
  fireEvent.click(screen.getByRole('button', { name: '보내기' }))
  view.rerender(<PlannerChat {...p} project={b}/> )
  fireEvent.change(screen.getByLabelText('메시지'), { target: { value: '발표 입력 유지' } })
  finish(state())
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  expect(JSON.parse(fetch.mock.calls[0][1].body).project.id).toBe('a')
  await waitFor(() => expect(screen.getByDisplayValue('발표 입력 유지')).toBeTruthy())
  view.rerender(<PlannerChat {...p}/> )
  await waitFor(() => expect((screen.getByLabelText('메시지') as HTMLTextAreaElement).value).toBe(''))
  view.unmount()
  render(<PlannerChat {...p} project={b}/> )
  expect((screen.getByLabelText('메시지') as HTMLTextAreaElement).value).toBe('')
})
it('never shows another project draft in this project view', () => {
  const s = state(); s.planDraft = { ...s.plan!, id: 'draft', status: 'draft', projectId: 'b', project: b, entries: s.plan!.entries.map(e => ({ ...e, projectId: 'b' })) }
  render(<ExecutionView state={s} onChange={vi.fn()} projects={[a, b]} milestones={[]} events={[]} section="project" projectId="a"/> )
  expect(screen.queryByLabelText('주간 계획 초안')).toBeNull()
})
it('labels mixed-project drafts using task ownership and hides them from unrelated projects', () => {
  const s = state(2)
  s.planDraft = { ...s.plan!, id: 'draft', status: 'draft', projectId: null, project: null, entries: s.plan!.entries.map((e, i) => ({ ...e, projectId: i ? 'b' : 'a' })) }
  const view = render(<ExecutionView state={s} onChange={vi.fn()} projects={[a, b, { ...a, id: 'c' }]} milestones={[]} events={[]} section="project" projectId="a"/> )
  expect(screen.getByText('여러 프로젝트 공동 계획:').parentElement?.textContent).toContain('에세이 · 발표')
  view.rerender(<ExecutionView state={s} onChange={vi.fn()} projects={[a, b, { ...a, id: 'c' }]} milestones={[]} events={[]} section="project" projectId="c"/> )
  expect(screen.queryByLabelText('주간 계획 초안')).toBeNull()
})
it('explicit invalidity hides a card even when its revision matches', () => {
  const s = { ...state(), plannerThreads: { a: { messages: [], action: { kind: 'plan', valid: false, revision: 9, payload: { goal: '숨겨야 함', startDate: '2026-10-27' } } } } } as unknown as ExecutionState
  render(<PlannerChat {...props(s)} onApplyPlan={vi.fn()}/> )
  expect(screen.queryByText('숨겨야 함')).toBeNull()
})
it('distinguishes backend confirmed declaration metadata from observations', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ slots: [{ key: 'place', label: '주로 하는 곳', value: '도서관', history: ['도서관'], kind: 'declared', source: 'check_in', status: 'confirmed' }], next: [] }) }))
  render(<AboutMe revision={1}/> )
  await waitFor(() => expect(screen.getByText('확인한 직접 진술·선호')).toBeTruthy())
  expect(screen.queryByText(/ABOUT ME · 1\/1/)).toBeNull()
})
it('does not ask already known daily fields again through optional followups', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ slots: [], next: [{ key: 'place', question: '오늘 어디서 했나요?' }, { key: 'tone', question: '어떤 말투가 좋나요?' }] }) }))
  const s = { ...state(), checkInSessions: [{ id: 'day', date: dateKey(new Date()), projectId: 'b', place: '도서관' }] } as ExecutionState
  render(<CheckIn {...props(s)}/> )
  fireEvent.click(screen.getByText('다 했어요')); fireEvent.click(screen.getByText('다음'))
  await screen.findByText('어떤 말투가 좋나요?')
  expect(screen.queryByText('오늘 어디서 했나요?')).toBeNull()
})
it('keeps checkbox-only completion eligible but excludes confirmed empty check-ins and follows latest records', () => {
  const s = state(3)
  s.executionRecords = [
    { planId: 'plan', taskId: 't0', result: 'completed' },
    { planId: 'plan', taskId: 't1', result: 'completed', checkInId: 'saved' },
    { planId: 'plan', taskId: 't2', result: 'partial' },
    { planId: 'plan', taskId: 't2', result: 'completed' },
  ] as ExecutionState['executionRecords']
  expect(checkInTasks(s, 'a').due.map(t => t.id)).toEqual(['t0', 't2'])
})

it('resumes A pending confirmation and input after visiting B without leaking to B', () => {
  const s = { ...state(), plannerThreads: { a: { messages: [], action: { kind: 'check_in', id: 'pending-a', projectId: 'a', valid: true, revision: 1, payload: { records: [{ taskId: 't0', taskTitle: '에세이 초안', result: 'completed' }] } } } } } as unknown as ExecutionState
  const p = { ...props(s), onApplyPlan: vi.fn() }
  const view = render(<PlannerChat {...p}/> )
  fireEvent.click(screen.getByText('체크인 이어하기·수정'))
  fireEvent.change(screen.getByLabelText('답하기 (선택)'), { target: { value: 'A만의 수정 내용' } })
  view.rerender(<PlannerChat {...p} project={b}/> )
  expect(screen.queryByLabelText('체크인 확인 카드')).toBeNull()
  expect(screen.queryByText(/에세이 초안/)).toBeNull()
  expect(screen.queryByDisplayValue('A만의 수정 내용')).toBeNull()
  view.rerender(<PlannerChat {...p}/> )
  fireEvent.click(screen.getByText('체크인 이어하기·수정'))
  expect(screen.getByDisplayValue('A만의 수정 내용')).toBeTruthy()
  expect(screen.getByLabelText('체크인 확인 카드').textContent).toContain('에세이 초안')
})

it('shows prior-merged-plan checkbox completions but excludes confirmed siblings in UI', () => {
  const s = state(2)
  s.plan!.entries.forEach(t => { t.completed = true })
  s.executionRecords = [
    { planId: 'prior-plan', taskId: 't0', result: 'completed' },
    { planId: 'prior-plan', taskId: 't1', result: 'completed', checkInId: 'saved' },
  ] as ExecutionState['executionRecords']
  render(<CheckIn {...props(s)}/> )
  const completed = screen.getByRole('button', { name: '다 했어요' }) as HTMLButtonElement
  expect(completed.getAttribute('aria-pressed')).toBe('true')
  expect(completed.disabled).toBe(true)
  expect(screen.getByText('작업0')).toBeTruthy()
  expect(screen.queryByText('작업1')).toBeNull()
  expect((screen.getByText('다음') as HTMLButtonElement).disabled).toBe(false)
})

it('does not submit known daily context as a new project statement, and allows skipping details without consent', async () => {
  const s = { ...state(), checkInSessions: [{ id: 'b-day', projectId: 'b', date: dateKey(new Date()), place: '도서관', focus: 'good' }] } as ExecutionState
  const fetcher = vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => ({ ok: true, json: async () => init ? s : { slots: [], next: [] } }))
  vi.stubGlobal('fetch', fetcher)
  render(<CheckIn {...props(s)} consent={false}/> )
  fireEvent.click(screen.getByText('다 했어요')); fireEvent.click(screen.getByText('다음'))
  fireEvent.click(await screen.findByText('덧붙일 말 없이 기록'))
  await waitFor(() => expect(fetcher.mock.calls.some(([, init]) => !!init?.body)).toBe(true))
  const [, init] = fetcher.mock.calls.find(([, init]) => !!init?.body)!
  const body = JSON.parse(String(init?.body))
  expect(body).toMatchObject({ project: { id: 'a' }, consent: false, text: '', results: [{ taskId: 't0', result: 'completed' }] })
  expect(body).not.toHaveProperty('place')
  expect(body).not.toHaveProperty('focus')
  expect(body.results[0]).not.toHaveProperty('place')
})

it('hides explicitly invalid check-in cards even at matching revision', () => {
  const s = { ...state(), plannerThreads: { a: { messages: [], action: { kind: 'check_in', valid: false, revision: 9, payload: { records: [] } } } } } as unknown as ExecutionState
  render(<CheckIn {...props(s)}/> )
  expect(screen.queryByLabelText('체크인 확인 카드')).toBeNull()
  expect(screen.getByText('다 했어요')).toBeTruthy()
})

it('recovers a committed check-in after a lost response rather than reporting failure', async () => {
  const s = { ...state(), plannerThreads: { a: { messages: [], action: { kind: 'check_in', id: 'committed', projectId: 'a', valid: true, revision: 9, payload: { records: [] } } } } } as unknown as ExecutionState
  const fresh = { ...s, revision: 10, checkInSessions: [{ id: 'committed', date: dateKey(new Date()), projectId: 'a' }] }
  const fetcher = vi.fn().mockRejectedValueOnce(new Error('response lost')).mockResolvedValueOnce({ ok: true, json: async () => fresh })
  vi.stubGlobal('fetch', fetcher)
  render(<CheckIn {...props(s)}/> )
  fireEvent.click(screen.getByText('확인하고 기록'))
  expect(await screen.findByText(/체크인은 기록했어요/)).toBeTruthy()
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(fetcher.mock.calls[1][0]).toBe('/api/execution')
})

it('drops memory-only inputs when the account-keyed workspace unmounts', () => {
  const p = { state: state(), onChange: vi.fn(), projects: [a], milestones: [], events: [], section: 'project' as const, projectId: 'a' }
  const view = render(<ExecutionView key="account-one" {...p}/> )
  fireEvent.change(screen.getByLabelText('메시지'), { target: { value: '계정 1 비공개 입력' } })
  view.rerender(<ExecutionView key="account-two" {...p}/> )
  expect(screen.queryByDisplayValue('계정 1 비공개 입력')).toBeNull()
  expect((screen.getByLabelText('메시지') as HTMLTextAreaElement).value).toBe('')
})

it('shows declaration evidence separately from provisional observation metadata', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ next: [], slots: [{ key: 'place', label: '주로 하는 곳', value: '도서관', history: [], kind: 'declared', evidence: { confirmations: 2, distinctDays: 2, windowDays: 30 } }], candidatePatterns: [{ field: 'place', value: '도서관', status: 'insufficient', samples: 2, distinctDays: 1, unknownFocus: 1, windowDays: 30 }] }) }))
  render(<AboutMe revision={1}/> )
  expect(await screen.findByText(/직접 진술 근거: 2회 · 2일/)).toBeTruthy()
  const patterns = screen.getByLabelText('관찰 후보의 근거')
  expect(patterns.textContent).toContain('근거 부족')
  expect(patterns.textContent).toContain('체크인 2회 · 1일')
  expect(patterns.textContent).toContain('집중 미응답 1회')
  expect(patterns.textContent).toContain('연관성이지 원인은 아니에요')
})
