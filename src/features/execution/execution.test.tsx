// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { AvailabilityGrid } from './AvailabilityGrid'
import { ProfileForm } from './ProfileForm'
import { ExecutionView } from './ExecutionView'
import { ExecutionLearning } from './ExecutionLearning'
import { PlannerChat } from './PlannerChat'
import { CheckIn, checkInCounts, checkInLabel, checkInTasks } from './CheckIn'
import { AboutMe } from './AboutMe'
import { PlanReasons } from './PlanReasons'
import { ProjectSettings } from './ProjectSettings'
import { approveProposalAndReplan, planCalendarEvents, planIsStale, replansCurrentPlan, staleProjectIds } from './api'
import type { AvailabilitySlot, ExecutionPlan, ExecutionState, Project } from '../../shared/types'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear() })
it('selects and deselects weekly hours without duplicates', () => {
  function Harness() { const [slots,setSlots]=useState<AvailabilitySlot[]>([]); return <AvailabilityGrid slots={slots} onChange={setSlots}/> }
  render(<Harness/>);
  fireEvent.click(screen.getByLabelText('월요일 18시부터 19시'))
  expect(screen.getByRole('status').textContent).toContain('1시간')
  fireEvent.click(screen.getByText('평일 18~21시 선택'))
  expect(screen.getByRole('status').textContent).toContain('15시간')
  fireEvent.click(screen.getByText('평일 18~21시 선택'))
  expect(screen.getByRole('status').textContent).toContain('15시간')
  fireEvent.click(screen.getByText('선택 해제'))
  expect(screen.getByRole('status').textContent).toContain('0시간')
})
it('preserves unknown duration and exclusive no-barrier answer', async () => {
  const generate = vi.fn().mockResolvedValue(undefined)
  render(<ProfileForm busy={false} onGenerate={generate}/>)
  fireEvent.click(screen.getByLabelText('학생'))
  fireEvent.click(screen.getByLabelText('대체로 규칙적'))
  fireEvent.click(screen.getByText('다음'))
  fireEvent.click(screen.getByLabelText('시작이 어려움'))
  fireEvent.click(screen.getByLabelText('특별한 어려움 없음'))
  expect((screen.getByLabelText('시작이 어려움') as HTMLInputElement).checked).toBe(false)
  fireEvent.click(screen.getByText('다음'))
  // When the user focuses best is learned from records, not asked.
  expect(screen.queryByLabelText('저녁·밤')).toBeNull()
  fireEvent.click(screen.getByText('다음'))
  fireEvent.click(screen.getByLabelText('할 일을 줄임'))
  fireEvent.click(screen.getByLabelText('시간 지정형 · 18:30~19:00 공부'))
  fireEvent.click(screen.getByText('프로필 생성'))
  await waitFor(() => expect(generate).toHaveBeenCalledWith(expect.objectContaining({
    roles: ['student'], barriers: ['none'], focusMinutes: null,
    dailyMinutes: null, scheduleStyle: 'time_blocks', energy: 'unknown',
  }), 'demo', false))
})
it('maps confirmed tasks once and omits breaks', () => {
  const plan={id:'week1',status:'confirmed',projectId:null,entries:[{id:'task1',kind:'task',start:'2030-01-07T18:00',end:'2030-01-07T18:25',title:'문제 풀기',completed:true},{id:'break1',kind:'break',start:'2030-01-07T18:25',end:'2030-01-07T18:30'}]} as ExecutionPlan
  const events=planCalendarEvents(plan,[])
  expect(events).toHaveLength(1)
  expect(events[0]).toMatchObject({id:'execution:week1:task1',title:'✓ 문제 풀기',date:'2030-01-07',startTime:'18:00',endTime:'18:25'})
  expect(planCalendarEvents({...plan,status:'draft'},[])).toEqual([])
})
it('colors each calendar task by its own project in a multi-project week', () => {
  const projects=[{id:'essay'},{id:'app'}] as Project[]
  const plan={id:'week2',status:'confirmed',projectId:null,entries:[
    {id:'a',kind:'task',start:'2030-01-07T19:00',end:'2030-01-07T19:20',title:'개요',completed:false,projectId:'essay'},
    {id:'b',kind:'task',start:'2030-01-09T19:00',end:'2030-01-09T19:20',title:'로그인',completed:false,projectId:'app'},
    {id:'c',kind:'task',start:'2030-01-10T19:00',end:'2030-01-10T19:20',title:'정리',completed:false,projectId:'deleted'},
  ]} as ExecutionPlan
  expect(planCalendarEvents(plan,projects).map(e=>e.projectId)).toEqual(['essay','app',undefined])
})

describe('screens', () => {
  const profile = { id: 'profile1', status: 'confirmed', source: 'demo', schemaVersion: '2.0', createdAt: '', learnedPatterns: [],
    declaredFacts: { roles: ['student'], regularity: 'regular', barriers: ['none'], focusMinutes: 30, dailyMinutes: null, energy: 'unknown', recovery: 'reduce', constraints: '', context: '' },
    planningPreferences: { blockMinutes: 30, breakMinutes: 5, dailyPlannedMinutes: null, scheduleStyle: 'time_blocks', recoveryPreference: 'reduce', starterMinutes: null, focusTime: 'unknown', status: 'confirmed' },
    insights: { summary: '요약', strategies: [], followUpQuestions: [] } }
  const state = { revision: 3, profile, profileDraft: null, settings: { slots: [], view: 'timeline' }, plan: null, planDraft: null,
    llmAvailable: true, model: 'test' } as unknown as ExecutionState
  const essay = { id: 'essay', title: '에세이', goal: '초안', startDate: '2030-01-01', dueDate: '2030-01-31', priority: 'high', status: 'active' } as Project

  it('asks for this week\'s hours on its own page and points there from home', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 4, settings: { slots: [{ day: 0, hour: 18 }], view: 'timeline' } }) })
    vi.stubGlobal('fetch', fetchMock)
    const openSchedule = vi.fn()
    const home = render(<ExecutionView state={state} onChange={vi.fn()} projects={[]} milestones={[]} events={[]} section="home" calendar={<p>달력</p>} onOpenSchedule={openSchedule}/>)
    expect(screen.getByText('달력')).toBeTruthy()
    expect(screen.queryByLabelText('월요일 18시부터 19시')).toBeNull()
    fireEvent.click(screen.getByText('시간 고르기'))
    expect(openSchedule).toHaveBeenCalled()
    home.unmount()
    render(<ExecutionView state={state} onChange={vi.fn()} projects={[]} milestones={[]} events={[]} section="schedule"/>)
    expect(screen.getByText(/이번 주 계획할 시간 · .* · 아직 안 고름/)).toBeTruthy()
    expect(screen.getByText(/매주 새로 고르고/)).toBeTruthy()
    expect(screen.queryByText(/고정 일정/)).toBeNull()
    fireEvent.click(screen.getByLabelText('월요일 18시부터 19시'))
    fireEvent.click(screen.getByText('이번 주 시간 저장'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/settings')
  })
  it('sends a user without a profile to the survey', () => {
    const open = vi.fn()
    render(<ExecutionView state={{ ...state, profile: null }} onChange={vi.fn()} projects={[]} milestones={[]} events={[]} section="home" onOpenProfile={open}/>)
    fireEvent.click(screen.getByText('설문하러 가기'))
    expect(open).toHaveBeenCalled()
  })
  it('opens one project\'s conversation and points to the weekly hours page while this week has no hours', () => {
    const schedule = vi.fn()
    render(<ExecutionView state={state} onChange={vi.fn()} projects={[essay]} milestones={[]} events={[]} section="project" projectId="essay" onOpenSchedule={schedule}/>)
    expect(screen.getByRole('heading', { name: '에세이' })).toBeTruthy()
    fireEvent.click(screen.getByText('시간 고르기'))
    expect(schedule).toHaveBeenCalled()
  })
  it('lists the projects in progress on the home screen with their deadline', () => {
    const open = vi.fn()
    render(<ExecutionView state={state} onChange={vi.fn()} projects={[{ ...essay, dueDate: '2099-01-31' }]} milestones={[]} events={[]} section="home" onOpenProject={open}/>)
    const card = screen.getByRole('region', { name: '진행 중인 프로젝트' })
    expect(card.textContent).toContain('에세이')
    expect(card.textContent).toContain('2030-01-01 ~ 2099-01-31 · 마감 D-')
    fireEvent.click(screen.getByRole('button', { name: /에세이/ }))
    expect(open).toHaveBeenCalledWith('essay')
  })
  it('shows a draft for review only, without boxes to tick, and ends it at the project deadline', () => {
    const draft = { id: 'd1', goal: '초안', startDate: '2030-01-01', endDate: '2030-01-07', projectId: 'essay',
      project: { id: 'essay', title: '에세이', dueDate: '2030-01-03' }, pendingTasks: [], personalization: [],
      entries: [{ id: 't1', kind: 'task', start: '2030-01-02T19:00', end: '2030-01-02T19:30', title: '초안 쓰기', doneWhen: '초안 저장', minutes: 30, completed: false, projectId: 'essay' }] }
    render(<ExecutionView state={{ ...state, planDraft: draft } as unknown as ExecutionState} onChange={vi.fn()} projects={[essay]} milestones={[]} events={[]} section="project" projectId="essay"/>)
    const card = screen.getByRole('region', { name: '주간 계획 초안' })
    expect(card.querySelector('input[type=checkbox]')).toBeNull()
    expect(card.textContent).toContain('2030-01-01 ~ 2030-01-03 (프로젝트 마감)')
  })
  it('moves on once the first profile is confirmed', async () => {
    const draft = { ...profile, status: 'draft' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 4 }) }))
    const confirmed = vi.fn()
    render(<ExecutionView state={{ ...state, profile: null, profileDraft: draft } as unknown as ExecutionState} onChange={vi.fn()} projects={[]} milestones={[]} events={[]}
      section="profile" onProfileConfirmed={confirmed}/>)
    fireEvent.click(screen.getByText('프로필 확정'))
    await waitFor(() => expect(confirmed).toHaveBeenCalled())
  })
})

describe('check-in', () => {
  const essay = { id: 'essay', title: '에세이', goal: '초안', startDate: '2030-01-01', dueDate: '2030-01-31', priority: 'high', status: 'active' } as Project
  const task = (id: string, start: string, extra = {}) => ({ id, kind: 'task', start, end: start, title: `작업 ${id}`, doneWhen: '끝', minutes: 30, completed: false, projectId: 'essay', ...extra })
  const plan = { id: 'p1', projectId: 'essay', entries: [task('a', '2030-01-07T19:00'), task('b', '2030-01-08T19:00'),
    task('s', '2030-01-07T18:55', { starter: true }), task('c', '2030-01-09T19:00', { completed: true }), task('x', '2030-01-07T20:00', { projectId: 'other' })] }
  const state = { revision: 5, profile: { id: 'pr' }, settings: { slots: [], view: 'timeline' }, plan, planDraft: null, executionRecords: [],
    plannerThreads: {}, llmAvailable: true, model: 'test' } as unknown as ExecutionState

  it('asks about this project\'s unrecorded tasks up to today, or the next ones when none are due', () => {
    expect(checkInTasks(state, 'essay', '2030-01-07').due.map(t => t.id)).toEqual(['a'])
    expect(checkInTasks(state, 'essay', '2030-01-08').due.map(t => t.id)).toEqual(['a', 'b'])
    expect(checkInTasks(state, 'essay', '2030-01-06').early.map(t => t.id)).toEqual(['a', 'b'])
    const recorded = { ...state, executionRecords: [{ planId: 'p1', taskId: 'a', result: 'partial', place: '집' }] } as unknown as ExecutionState
    expect(checkInTasks(recorded, 'essay', '2030-01-08').due.map(t => t.id)).toEqual(['b'])
    // Ticked off without saying how it went: asked too, as done.
    const withTick = { ...state, executionRecords: [{ planId: 'p1', taskId: 'c', result: 'completed', place: null }] } as unknown as ExecutionState
    const ticked = checkInTasks(withTick, 'essay', '2030-01-09')
    expect(ticked.due.map(t => t.id)).toEqual(['a', 'b', 'c'])
    expect([...ticked.ticked]).toEqual(['c'])
  })
  it('turns taps and one sentence into a card, saves on confirm, then asks how the plan felt', async () => {
    const calls: Array<[string, unknown]> = []
    const card = { kind: 'check_in', revision: 6, payload: { learned: ['말투: 편한 반말'], records: [{ planId: 'p1', taskId: 'a', taskTitle: '작업 a', plannedMinutes: 30, result: 'partial',
      actualMinutes: 15, reasonCode: 'fatigue', place: '도서관', atmosphere: 'quiet', focus: 'poor', condition: 'poor', note: '' }] } }
    const run = vi.fn(async (action: () => Promise<ExecutionState>) => { await action(); return true })
    const next = [{ key: 'tone', label: '말투', question: '제가 어떤 말투로 얘기하면 편하세요?' }]
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (!init?.body) return { ok: true, json: async () => ({ slots: [], next }) }  // what the planner would like to know
      calls.push([url, JSON.parse(String(init.body))]); return { ok: true, json: async () => state }
    }))
    const view = (current: ExecutionState) => <CheckIn state={current} project={essay} busy={false} run={run} consent={true} onConsent={vi.fn()} onClose={vi.fn()}/>
    const { rerender } = render(view(state))
    const row = screen.getByText('작업 a').closest('li')!
    fireEvent.click(row.querySelector('button:nth-child(2)')!)  // 조금 했어요
    fireEvent.click(screen.getByText('다음'))
    fireEvent.change(await screen.findByLabelText('답하기 (선택)'), { target: { value: '도서관에서 15분 하다가 피곤해서 멈춤' } })
    expect(screen.getByText(/답해주시면 다음 계획에 도움이 돼요, 건너뛰어도 괜찮아요/)).toBeTruthy()
    expect(screen.getByText('제가 어떤 말투로 얘기하면 편하세요?')).toBeTruthy()
    fireEvent.click(screen.getByText('보내기'))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0][0]).toBe('/api/execution/chat/check-in')
    expect(calls[0][1]).toMatchObject({ revision: 5, consent: true, text: '도서관에서 15분 하다가 피곤해서 멈춤', asked: ['tone'], results: [{ taskId: 'a', result: 'partial' }], project: { id: 'essay' } })

    rerender(view({ ...state, revision: 6, plannerThreads: { essay: { messages: [], action: card } } } as unknown as ExecutionState))
    const shown = screen.getByRole('generic', { name: '체크인 확인 카드' })
    expect(shown.textContent).toContain('조금 함 · 실제 15분 · 이유: 피로')
    expect(shown.textContent).toContain('장소 도서관 · 분위기 조용한 곳 · 집중 안 됨 · 컨디션 나쁨')
    expect(shown.textContent).toContain('대화에서 정리한 내용 (관찰·선호 후보): 말투: 편한 반말')
    fireEvent.click(screen.getByText('확인하고 기록'))
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1][0]).toBe('/api/execution/chat/check-in/confirm')
    fireEvent.click(await screen.findByText('많았어요'))
    expect(calls).toHaveLength(2) // Feedback is optional and saved only on explicit submission.
    fireEvent.click(screen.getByText('의견 저장'))
    await waitFor(() => expect(calls).toHaveLength(3))
    expect(calls[2]).toEqual(['/api/execution/projects/essay/feedback', { revision: 6, load: 'too_much', note: '' }])
    expect(await screen.findByText(/다음에 이 프로젝트를 계획할 때 참고해요/)).toBeTruthy()
  })
})

it('shows what check-ins taught about the user, and which fields are still empty', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ next: [], slots: [
    { key: 'tone', label: '말투', value: '편한 반말', history: ['casual'], updatedAt: '' },
    { key: 'place', label: '주로 하는 곳', value: '카페', history: ['도서관', '카페'], updatedAt: '' },
    { key: 'rest', label: '쉬는 방식', value: null, history: [], updatedAt: null }] }) }))
  render(<AboutMe revision={1}/>)
  const card = await screen.findByRole('region', { name: '나에 대해 알게 된 것' })
  expect(card.textContent).toContain('ABOUT ME · 기록된 항목 2개')
  expect(card.textContent).toContain('아직 가설')
  expect(card.textContent).toContain('편한 반말')
  expect(card.textContent).toContain('도서관, 카페')
  expect(card.textContent).toContain('아직 기록 없음 · 답변은 선택이에요')
})

describe('onboarding survey', () => {
  const state: ExecutionState = { revision: 0, profile: null, profileDraft: null, settings: { slots: [], view: 'timeline' }, plan: null, planDraft: null, llmAvailable: false, model: 'test' }
  it('opens a checkbox survey without chat or AI requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revision: 0, session: null }) }))
    render(<ExecutionView state={state} onChange={vi.fn()} projects={[]} milestones={[]} events={[]}/>)
    expect(screen.getByText('생활의 리듬')).toBeTruthy()
    expect(screen.queryByText('설문 양식으로 입력·수정')).toBeNull()
    expect(screen.queryByRole('log')).toBeNull()
    expect(fetch).not.toHaveBeenCalled()

  })
  it('resets profile only after confirmation and returns to the survey', async () => {
    const fetcher = vi.fn().mockImplementation(async (url: string) => ({ok:true,json:async()=>url.endsWith('/profile/reset') ? {...state,revision:1} : {revision:0,session:null}}))
    vi.stubGlobal('fetch',fetcher)
    const confirm = vi.spyOn(window,'confirm').mockReturnValue(false)
    const changed = vi.fn()
    render(<ExecutionView state={state} onChange={changed} projects={[]} milestones={[]} events={[]}/>)

    fireEvent.click(screen.getByText('프로필 초기화하기'))
    expect(fetcher.mock.calls.some(c=>c[0].endsWith('/profile/reset'))).toBe(false)
    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByText('프로필 초기화하기'))
    await waitFor(()=>expect(changed).toHaveBeenCalledWith(expect.objectContaining({revision:1,profile:null})))
    expect(fetcher.mock.calls.filter(c=>c[0].endsWith('/profile/reset'))).toHaveLength(1)
  })
})
it('submits checked survey answers without LLM interaction', async () => {
  const submit = vi.fn().mockResolvedValue(undefined)
  render(<ProfileForm busy={false} onGenerate={submit}/>)
  fireEvent.click(screen.getByLabelText('학생'))
  fireEvent.click(screen.getByLabelText('직장인'))
  fireEvent.click(screen.getByLabelText('대체로 규칙적'))
  fireEvent.click(screen.getByText('다음'))
  fireEvent.click(screen.getByLabelText('시작이 어려움'))
  fireEvent.click(screen.getByText('다음'))
  fireEvent.click(screen.getByLabelText('25분'))
  fireEvent.click(screen.getByText('다음'))
  fireEvent.click(screen.getByLabelText('할 일을 줄임'))
  fireEvent.click(screen.getByLabelText('작업량 지정형 · 공부 1시간, 운동 30분'))
  fireEvent.click(screen.getByText('프로필 생성'))
  await waitFor(()=>expect(submit).toHaveBeenCalledWith(expect.objectContaining({roles:['student','employee'],focusMinutes:25,dailyMinutes:null,scheduleStyle:'flexible_queue'}),'demo',false))
  expect(screen.queryByRole('textbox')).toBeNull()
})

it('sends an unfinished task to the AI for sizing only when the user opts in', async () => {
  const settings = { slots: [{ day: 0, hour: 18 }], view: 'timeline' as const }
  const plan = {
    id: 'week1', profileId: 'profile1', projectId: null, project: null, goal: '시험 공부',
    startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul', status: 'confirmed',
    slots: settings.slots, pendingTasks: [], entries: [{
      id: 'task1', kind: 'task', title: '문제 풀기', minutes: 30, doneWhen: '10문제 풀이', dueDate: null,
      start: '2030-01-07T18:00', end: '2030-01-07T18:30', completed: false,
    }],
  } as ExecutionPlan
  const state = {
    revision: 4, profile: null, profileDraft: null, settings, plan, planDraft: null,
    llmAvailable: true, model: 'test', executionRecords: [], profileUpdateProposals: [],
  } as ExecutionState
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 5 }) })
  vi.stubGlobal('fetch', fetchMock)
  const run = vi.fn(async (action: () => Promise<ExecutionState>) => { await action(); return true })
  render(<ExecutionLearning state={state} busy={false} run={run}/>)

  fireEvent.change(screen.getByLabelText('작업'), { target: { value: 'task1' } })
  fireEvent.change(screen.getByLabelText('실행 결과'), { target: { value: 'partial' } })
  fireEvent.change(screen.getByLabelText('실제 시간(분)'), { target: { value: '15' } })
  fireEvent.change(screen.getByLabelText('미완료·지연 이유'), { target: { value: 'time_shortage' } })
  fireEvent.click(screen.getByLabelText(/작업 내용까지 보고 판단받는 데 동의/))
  fireEvent.click(screen.getByText('실행 결과 저장'))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/records')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ taskId: 'task1', result: 'partial', consent: true })
})

it('sends priority-change check-ins through adaptive full replanning with explicit consent', async () => {
  const settings = { slots: [{ day: 0, hour: 18 }], view: 'timeline' as const }
  const plan = {
    id: 'week1', profileId: 'profile1', projectId: null, project: null, goal: '시험 공부',
    startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul', status: 'confirmed',
    slots: settings.slots, pendingTasks: [], entries: [{
      id: 'task1', kind: 'task', title: '문제 풀기', minutes: 30, doneWhen: '10문제 풀이', dueDate: null,
      start: '2030-01-07T18:00', end: '2030-01-07T18:30', completed: false,
    }],
  } as ExecutionPlan
  const state = {
    revision: 4, profile: null, profileDraft: null, settings, plan, planDraft: null,
    llmAvailable: true, model: 'test', executionRecords: [], profileUpdateProposals: [],
  } as ExecutionState
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 5 }) })
  vi.stubGlobal('fetch', fetchMock)
  const run = vi.fn(async (action: () => Promise<ExecutionState>) => { await action(); return true })
  const memories = [{ id: 'memory1', content: '저녁 집중', category: 'preference', source: 'user', createdAt: '2030-01-01' }] as const
  render(<ExecutionLearning
    state={state} busy={false} run={run}
    events={[{ date: '2030-01-08', startTime: '19:00', endTime: '20:00' }]}
    memories={[...memories]}
  />)

  fireEvent.change(screen.getByLabelText('작업'), { target: { value: 'task1' } })
  fireEvent.change(screen.getByLabelText('실행 결과'), { target: { value: 'partial' } })
  fireEvent.change(screen.getByLabelText('실제 시간(분)'), { target: { value: '15' } })
  fireEvent.change(screen.getByLabelText('남은 작업 예상 시간(분)'), { target: { value: '20' } })
  fireEvent.change(screen.getByLabelText('미완료·지연 이유'), { target: { value: 'priority_changed' } })

  const submit = screen.getByText('재계획 초안 만들기') as HTMLButtonElement
  expect(submit.disabled).toBe(true)
  fireEvent.click(screen.getByLabelText(/현재 계획·작업·체크인 정보를 LLM에 전송/))
  expect(submit.disabled).toBe(false)
  fireEvent.click(submit)

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(fetchMock.mock.calls[0][0]).toBe('/api/adaptive/check-in')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
    revision: 4,
    taskId: 'task1',
    strategy: 'replan',
    consent: true,
    events: [{ date: '2030-01-08', startTime: '19:00', endTime: '20:00' }],
    memories: [{ id: 'memory1', content: '저녁 집중' }],
    checkIn: {
      completed: false,
      actualMinutes: 15,
      remainingMinutes: 20,
      reasonCode: 'priority_changed',
    },
  })
})

describe('getting a failed task back into the week', () => {
  const settings = { slots: [{ day: 0, hour: 18 }], view: 'timeline' as const }
  const task = { id: 'task1', kind: 'task' as const, title: '문제 풀기', minutes: 30, doneWhen: '10문제 풀이', dueDate: null,
    start: '2030-01-07T18:00', end: '2030-01-07T18:30', completed: false }
  const plan = {
    id: 'week1', profileId: 'profile1', projectId: null, project: null, goal: '시험 공부',
    startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul', status: 'confirmed',
    slots: settings.slots, pendingTasks: [], entries: [task],
  } as ExecutionPlan
  const state = {
    revision: 4, profile: null, profileDraft: null, settings, plan, planDraft: null,
    llmAvailable: true, model: 'test', executionRecords: [], profileUpdateProposals: [],
  } as ExecutionState
  const draft = { id: 'd1', planId: 'week1', taskId: 'task1', recordId: 'r1', strategy: 'reschedule' as const, revisionCount: 0,
    checkIn: { completed: false, actualMinutes: 0, remainingMinutes: null, reasonCode: 'time_shortage', note: '', difficulty: null },
    draft: { kind: 'reschedule' as const, replacesTaskId: 'task1', appliedReasons: ['시간이 부족했다는 체크인을 반영했어요.'], droppedScope: [], carryOverMinutes: 0,
      tasks: [{ title: '문제 풀기', minutes: 30, doneWhen: '10문제 풀이', start: '2030-01-08T18:00', end: '2030-01-08T18:30' }] } }
  const live = (initial: ExecutionState) => {
    const messages: string[] = []
    function Harness() {
      const [current, setCurrent] = useState(initial)
      const run = async (action: () => Promise<ExecutionState>, message: string | ((next: ExecutionState) => string)) => {
        const next = await action(); setCurrent(next); messages.push(typeof message === 'string' ? message : message(next)); return true
      }
      return <ExecutionLearning state={current} busy={false} run={run}/>
    }
    return { Harness, messages }
  }

  it('asks the planner for a way back only with consent, and lets the user pick when it cannot', async () => {
    const asked = { ...state, revision: 5, executionRecords: [{ id: 'r1', planId: 'week1', taskId: 'task1' }] as ExecutionState['executionRecords'],
      result: { approvalStatus: 'needs_input' as const, fallback: { action: 'request_input', missingFields: ['strategy'] } } }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => asked })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...asked, revision: 6, recoveryDrafts: { task1: draft },
        result: { approvalStatus: 'waiting', strategy: 'reschedule' } }) })
    vi.stubGlobal('fetch', fetchMock)
    const { Harness, messages } = live(state)
    render(<Harness/>)

    fireEvent.change(screen.getByLabelText('작업'), { target: { value: 'task1' } })
    fireEvent.change(screen.getByLabelText('실행 결과'), { target: { value: 'not_started' } })
    fireEvent.change(screen.getByLabelText('실제 시간(분)'), { target: { value: '0' } })
    fireEvent.change(screen.getByLabelText('미완료·지연 이유'), { target: { value: 'other' } })
    fireEvent.click(screen.getByLabelText(/다시 넣을 방법\(다른 빈 시간으로 옮기기·줄이기\)/))
    fireEvent.click(screen.getByText('결과 저장하고 다시 넣을 방법 받기'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/adaptive/check-in')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ taskId: 'task1', strategy: null, consent: true,
      checkIn: { completed: false, actualMinutes: 0, remainingMinutes: null, reasonCode: 'other' } })
    expect(messages[0]).toContain('어떻게 다시 넣을지 골라 주세요')

    fireEvent.click(await screen.findByText('다른 빈 시간으로 옮기기'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ revision: 5, taskId: 'task1', strategy: 'reschedule' })
    await waitFor(() => expect(messages[1]).toContain('복구안을 만들었어요'))
    expect(screen.getByText(/다른 시간으로 옮기기 · 문제 풀기/)).toBeTruthy()
  })

  it('approves a waiting draft through the planner review', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 5, result: { approvalStatus: 'approved' } }) })
    vi.stubGlobal('fetch', fetchMock)
    const { Harness, messages } = live({ ...state, recoveryDrafts: { task1: draft } })
    render(<Harness/>)

    expect(screen.getByText(/18:00~18:30 · 문제 풀기 · 30분/)).toBeTruthy()
    fireEvent.click(screen.getByText('승인하고 계획에 반영'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/adaptive/review')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ revision: 4, draftId: 'd1', decision: 'approve' })
    await waitFor(() => expect(messages[0]).toBe('복구안을 계획에 반영했어요.'))
  })

  it('asks about tasks whose time has passed without a record', async () => {
    const past = { ...task, id: 'old', title: '어제 할 일', start: '2020-01-06T18:00', end: '2020-01-06T18:30' }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 5 }) })
    vi.stubGlobal('fetch', fetchMock)
    const { Harness } = live({ ...state, plan: { ...plan, entries: [past, task] } })
    render(<Harness/>)

    const missed = screen.getByLabelText('지난 작업 확인')
    expect(missed.textContent).toContain('시간이 지난 작업 1개')
    expect(missed.textContent).toContain('어제 할 일')
    expect(missed.textContent).not.toContain('문제 풀기')
    fireEvent.click(screen.getByText('못 했어요'))
    expect((screen.getByLabelText('작업') as HTMLSelectElement).value).toBe('old')
    expect((screen.getByLabelText('실행 결과') as HTMLSelectElement).value).toBe('not_started')
    fireEvent.click(screen.getByText('했어요'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ planId: 'week1', taskId: 'old', completed: true })
  })
})

it('lists what an ended project carried, with nothing left to approve', () => {
  const carried = { id: 'c1', profileId: 'p1', appliedProfileId: 'p2', projectId: null, sourceProjectId: 'essay', reason: '‘에세이’ 프로젝트를 끝내며 기본 프로필로 옮긴 습관',
    proposedChanges: { blockMinutes: { from: 30, to: 20 }, recoveryPreference: { from: 'unknown', to: 'reduce' } },
    evidenceRecordIds: [], ruleVersion: 'project-close-v1', status: 'approved' as const, createdAt: '', decidedAt: '' }
  const state = { revision: 4, profile: { id: 'p2' }, profileDraft: null, settings: { slots: [], view: 'timeline' }, plan: { id: 'w', entries: [] },
    planDraft: null, llmAvailable: true, model: 'test', executionRecords: [], profileUpdateProposals: [carried] } as unknown as ExecutionState
  render(<ExecutionLearning state={state} busy={false} run={vi.fn()}/>)
  expect(screen.getByText('집중 구간 30분 → 20분 · 계획이 틀어졌을 때 잘 모르겠어요 → 할 일을 줄임')).toBeTruthy()
  expect(screen.getByText('상태: 프로젝트를 끝내며 반영함')).toBeTruthy()
  expect(screen.queryByRole('button')).toBeNull()
})

describe('profile proposal replan flow', () => {
  it('uses the approval response revision for the replan request', async () => {
    const settings = { slots: [{ day: 0, hour: 18 }], view: 'timeline' as const }
    const plan = {
      id: 'week1', profileId: 'old', projectId: null, project: null, goal: '시험 공부',
      startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul', status: 'confirmed',
      slots: settings.slots, entries: [], pendingTasks: [],
    } as ExecutionPlan
    const state = { revision: 4, settings, plan } as unknown as ExecutionState
    const approved = { revision: 5, settings, plan }
    const replanned = { revision: 6, settings, plan, planDraft: { ...plan, id: 'draft1', profileId: 'new', status: 'draft' } }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => approved })
      .mockResolvedValueOnce({ ok: true, json: async () => replanned })
    vi.stubGlobal('fetch', fetchMock)

    const result = await approveProposalAndReplan(state, 'proposal-1', {
      goal: plan.goal, startDate: plan.startDate, consent: true, project: null,
      existingTasks: [], events: [{ date: '2030-01-08', startTime: '19:00', endTime: '20:00' }],
    })

    expect(result.revision).toBe(6)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/proposals/proposal-1/approve')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ revision: 4 })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/execution/plan')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      revision: 5, profileChangeProposalId: 'proposal-1', consent: true,
      goal: '시험 공부', startDate: '2030-01-07',
    })
  })

  it('retries an approved proposal without approving it again', async () => {
    const settings = { slots: [{ day: 0, hour: 18 }], view: 'timeline' as const }
    const plan = {
      id: 'week1', profileId: 'old', projectId: null, project: null, goal: '시험 공부',
      startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul', status: 'confirmed',
      slots: settings.slots, entries: [], pendingTasks: [],
    } as ExecutionPlan
    const state = {
      revision: 5, settings, plan,
      profileUpdateProposals: [{ id: 'proposal-1', status: 'approved', appliedProfileId: 'new' }],
    } as unknown as ExecutionState
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...state, revision: 6 }) })
    vi.stubGlobal('fetch', fetchMock)

    await approveProposalAndReplan(state, 'proposal-1', {
      goal: plan.goal, startDate: plan.startDate, consent: true, project: null, existingTasks: [], events: [],
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/plan')
  })

  it('approves a change learned in another project without replanning the current plan', async () => {
    const settings = { slots: [{ day: 0, hour: 18 }], view: 'timeline' as const }
    const plan = {
      id: 'week1', profileId: 'profile1', projectId: null, project: null, goal: '졸업작품',
      startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul', status: 'confirmed',
      slots: settings.slots, pendingTasks: [],
      // A shared week: project B still has open work, project A has none.
      entries: [
        { id: 't1', kind: 'task', projectId: 'project-b', completed: false, title: '시연', minutes: 30, doneWhen: '끝', dueDate: null, start: '2030-01-07T18:00', end: '2030-01-07T18:30' },
        { id: 't2', kind: 'task', projectId: 'project-a', completed: true, title: '단어', minutes: 20, doneWhen: '끝', dueDate: null, start: '2030-01-07T18:35', end: '2030-01-07T18:55' },
      ],
    } as ExecutionPlan
    const state = {
      revision: 4, settings, plan,
      profileUpdateProposals: [{ id: 'proposal-1', status: 'pending', projectId: 'project-a' }],
    } as unknown as ExecutionState
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...state, revision: 5 }) })
    vi.stubGlobal('fetch', fetchMock)

    const result = await approveProposalAndReplan(state, 'proposal-1', {
      goal: plan.goal, startDate: plan.startDate, consent: false, project: null, existingTasks: [], events: [],
    })

    expect(result.revision).toBe(5)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/proposals/proposal-1/approve')
    expect(replansCurrentPlan(state, { ...state.profileUpdateProposals![0], projectId: 'project-b' })).toBe(true)
  })

  it('marks only the projects whose settings changed as stale', () => {
    const plan = { id: 'week1', profileId: 'profile1', projectId: null, entries: [
      { id: 'a1', kind: 'task', projectId: 'project-a', projectProfileId: null, completed: false },
      { id: 'b1', kind: 'task', projectId: 'project-b', projectProfileId: 'project-b-v1', completed: false },
    ] } as unknown as ExecutionPlan
    const state = { profile: { id: 'profile1' }, projectProfiles: { 'project-b': { id: 'project-b-v1' } } } as unknown as ExecutionState
    expect(planIsStale(state, plan)).toBe(false)
    const changedA = { ...state, projectProfiles: { ...state.projectProfiles, 'project-a': { id: 'project-a-v1' } } } as unknown as ExecutionState
    expect(staleProjectIds(changedA, plan)).toEqual(['project-a'])
    expect(planIsStale({ ...state, profile: { id: 'profile2' } } as unknown as ExecutionState, plan)).toBe(true)
  })

  it('does not approve before replan consent is given', async () => {
    const settings = { slots: [], view: 'timeline' as const }
    const state = { revision: 4, settings, plan: { id: 'week1' } } as unknown as ExecutionState
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await expect(approveProposalAndReplan(state, 'proposal-1', {
      goal: '시험 공부', startDate: '2030-01-07', consent: false, project: null, existingTasks: [], events: [],
    })).rejects.toThrow('동의')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
describe('conversational planner', () => {
  const base: ExecutionState = { revision: 4, profile: null, profileDraft: null, settings: { slots: [{ day: 0, hour: 19 }], view: 'timeline' }, plan: null, planDraft: null, llmAvailable: true, model: 'test' }
  const essay = { id: 'essay', title: '에세이', goal: '초안', startDate: '2030-01-01', dueDate: '2030-01-31', priority: 'high', status: 'active' } as Project
  const app = { ...essay, id: 'app', title: '앱 개발' }
  const run = (action: () => Promise<ExecutionState>) => action().then(() => true)
  const threads = {
    essay: { messages: [{ id: 'e1', role: 'user' as const, content: '에세이 초안 쓰기' }], action: null, updatedAt: '2030-01-02T10:00:00' },
    app: { messages: [{ id: 'a1', role: 'user' as const, content: '로그인 화면' }], action: { kind: 'plan' as const, revision: 4, payload: { goal: '로그인 화면', startDate: '2030-01-07' } }, updatedAt: '2030-01-03T10:00:00' },
  }
  it('shows the conversation of the project it is given, in one continuing session', () => {
    const { rerender } = render(<PlannerChat state={{ ...base, plannerThreads: threads }} busy={false} run={run} project={app} onApplyPlan={vi.fn()}/>)
    expect(screen.getByRole('heading', { name: '앱 개발' })).toBeTruthy()
    expect(screen.getByRole('log').textContent).toContain('로그인 화면')
    expect(screen.queryByText('새 대화')).toBeNull()
    rerender(<PlannerChat state={{ ...base, plannerThreads: threads }} busy={false} run={run} project={essay} onApplyPlan={vi.fn()}/>)
    expect(screen.getByRole('heading', { name: '에세이' })).toBeTruthy()
    expect(screen.getByRole('log').textContent).toContain('에세이 초안 쓰기')
    expect(screen.getByRole('log').textContent).not.toContain('로그인 화면')
  })
  it('asks before fitting a project to what the user said, and applies it to that project only', async () => {
    const card = { kind: 'project_settings' as const, revision: 4, payload: {
      projectId: 'essay', overrides: { blockMinutes: 25 }, changes: { blockMinutes: { from: 50, to: 25 } } } }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...base, revision: 5 }) })
    vi.stubGlobal('fetch', fetchMock)
    render(<PlannerChat state={{ ...base, plannerThreads: { essay: { ...threads.essay, action: card, updatedAt: '2030-01-09T10:00:00' } } }}
      busy={false} run={run} project={essay} onApplyPlan={vi.fn()}/>)

    expect(screen.getByRole('heading', { name: '‘에세이’ 프로젝트를 이렇게 맞출까요?' })).toBeTruthy()
    expect(screen.getByText('한 번에 집중할 시간: 50분 → 25분')).toBeTruthy()
    fireEvent.click(screen.getByText('확인하고 이 프로젝트에 적용'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/projects/essay/profile')
    expect(fetchMock.mock.calls[0][1].method).toBe('PUT')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ revision: 4, overrides: { blockMinutes: 25 } })
  })
  it('applies the waiting card when the user agrees in words, as its button would', async () => {
    const card = { kind: 'project_settings' as const, revision: 4, payload: {
      projectId: 'essay', overrides: { blockMinutes: 25 }, changes: { blockMinutes: { from: 50, to: 25 } } } }
    const agreed = { ...base, revision: 5, plannerThreads: { essay: { messages: [
      { id: 'u1', role: 'user' as const, content: '응 그렇게 해 줘' },
      { id: 'c1', role: 'assistant' as const, content: '확인했어요. 카드 내용대로 적용할게요.', skill: 'confirm', lookups: [] }],
      action: { ...card, revision: 5 }, updatedAt: '2030-01-09T10:01:00' } } }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => agreed })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...agreed, revision: 6 }) })
    vi.stubGlobal('fetch', fetchMock)
    function Harness() {
      const [state, setState] = useState<ExecutionState>({ ...base, plannerThreads: { essay: { ...threads.essay, action: card, updatedAt: '2030-01-09T10:00:00' } } })
      const live = async (action: () => Promise<ExecutionState>) => { setState(await action()); return true }
      return <PlannerChat state={state} busy={false} run={live} project={essay} onApplyPlan={vi.fn()}/>
    }
    render(<Harness/>)
    fireEvent.change(screen.getByLabelText('메시지'), { target: { value: '응 그렇게 해 줘' } })
    fireEvent.click(screen.getByLabelText(/OpenAI에 전송하는 데 동의/))
    fireEvent.click(screen.getByText('보내기'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/execution/projects/essay/profile')
    // Applied with the revision the chat reply produced, not the one before it.
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ revision: 5, overrides: { blockMinutes: 25 } })
  })
  it('shows what ending a project carries to the user profile before it ends', async () => {
    const preview = { openTasks: 2,
      carried: [{ key: 'blockMinutes', label: '한 번에 집중할 시간', from: '30분', to: '20분', because: '20분 작업 3건 중 3건을 끝냈어요.' }],
      kept: [{ label: '하루 계획량', value: '60분', why: '이 프로젝트에만 정한 값이라 기본 프로필에는 넘기지 않아요.' }] }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => preview })
    vi.stubGlobal('fetch', fetchMock)
    const close = vi.fn().mockResolvedValue(true)
    const late = { ...essay, startDate: '2020-01-01', dueDate: '2020-01-31' }
    render(<PlannerChat state={{ ...base, plannerThreads: { essay: threads.essay } }} busy={false} run={run} project={late}
      onApplyPlan={vi.fn()} onCloseProject={close}/>)

    fireEvent.click(screen.getByText('마감 지남 · 끝내기'))  // past its due date, ending it is offered as such
    expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/projects/essay/close-preview')
    const panel = await screen.findByLabelText('프로젝트 끝내기')
    await waitFor(() => expect(panel.textContent).toContain('한 번에 집중할 시간: 30분 → 20분'))
    expect(panel.textContent).toContain('남은 이 프로젝트 작업 2개는 계획에서 빠져요')
    expect(panel.textContent).toContain('이 프로젝트에만 남는 것 1개')
    fireEvent.click(screen.getByLabelText('여기서 그만둘게요'))
    fireEvent.click(screen.getByText('끝내고 기본 프로필에 반영'))
    expect(close).toHaveBeenCalledWith(late, 'abandoned')
  })
  it('keeps an ended project apart, read-only, until it is opened again', () => {
    const ended = { title: '에세이', outcome: 'completed' as const, closedAt: '2030-01-20T10:00:00+00:00', removedTasks: 1, kept: [],
      carried: [{ key: 'blockMinutes', label: '한 번에 집중할 시간', from: '30분', to: '20분', because: '' }] }
    const reopen = vi.fn().mockResolvedValue(true)
    render(<PlannerChat state={{ ...base, plannerThreads: threads, closedProjects: { essay: ended } }} busy={false} run={run}
      project={essay} onApplyPlan={vi.fn()} onCloseProject={vi.fn()} onReopenProject={reopen}/>)

    expect(screen.getByLabelText('끝낸 프로젝트').textContent).toContain('기본 프로필로 넘긴 습관: 한 번에 집중할 시간 30분 → 20분')
    expect(screen.queryByLabelText('메시지')).toBeNull()
    expect(screen.queryByText('프로젝트 끝내기')).toBeNull()
    fireEvent.click(screen.getByText('다시 열기'))
    expect(reopen).toHaveBeenCalledWith(essay)
  })
  it('opens a project with what it plans with now', () => {
    const state = { ...base, projectProfiles: { essay: { id: 'v1', projectId: 'essay', userId: 'local', version: 1, learnedPatterns: [], createdAt: '', updatedAt: '',
      overrides: { blockMinutes: { value: 20, source: 'learned' as const, proposalId: 'p1' } } } } }
    render(<PlannerChat state={state} busy={false} run={run} project={essay} onApplyPlan={vi.fn()}/>)
    expect(screen.getByRole('log').textContent).toContain('이 프로젝트만의 값으로 계획해요: 한 번에 집중할 시간 20분.')
  })
  it('sends the selected project with the message after consent', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...base, revision: 5 }) })
    vi.stubGlobal('fetch', fetchMock)
    render(<PlannerChat state={base} busy={false} run={run} project={essay} onApplyPlan={vi.fn()}/>)
    fireEvent.change(screen.getByLabelText('메시지'), { target: { value: '금요일까지 초안' } })
    expect((screen.getByText('보내기') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText(/OpenAI에 전송하는 데 동의/))
    fireEvent.click(screen.getByText('보내기'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/execution/chat/message', expect.objectContaining({ method: 'POST' })))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ revision: 4, text: '금요일까지 초안', consent: true, project: { id: 'essay' } })
  })
  it('applies a plan card for its own project only while it is current', () => {
    const apply = vi.fn().mockResolvedValue(true)
    const state = { ...base, plannerThreads: threads }
    const { rerender } = render(<PlannerChat state={state} busy={false} run={run} project={app} onApplyPlan={apply}/>)
    fireEvent.click(screen.getByLabelText(/OpenAI에 전송하는 데 동의/))
    fireEvent.click(screen.getByText('확인하고 계획 초안 만들기'))
    expect(apply).toHaveBeenCalledWith('로그인 화면', '2030-01-07', app, true)
    rerender(<PlannerChat state={{ ...state, revision: 5 }} busy={false} run={run} project={app} onApplyPlan={apply}/>)
    expect(screen.queryByText('확인하고 계획 초안 만들기')).toBeNull()
  })
  it('asks before taking hours out of the week and replanning this project', async () => {
    const card = { kind: 'adjust' as const, revision: 4, payload: {
      blockedTimes: [{ date: '2030-01-09', startHour: 18, endHour: 21 }], goal: '에세이 초안, 분량 절반', startDate: '2030-01-07' } }
    const adjust = vi.fn().mockResolvedValue(true)
    render(<PlannerChat state={{ ...base, plannerThreads: { essay: { ...threads.essay, action: card, updatedAt: '2030-01-09T10:00:00' } } }}
      busy={false} run={run} project={essay} onApplyPlan={vi.fn()} onAdjust={adjust}/>)

    expect(screen.getByRole('heading', { name: '이번 주 계획을 이렇게 바꿀까요?' })).toBeTruthy()
    expect(screen.getByText('1/9(수) 18~21시')).toBeTruthy()
    const confirm = screen.getByText('확인하고 계획 다시 짜기') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)  // replanning sends the goal to the AI
    fireEvent.click(screen.getByLabelText(/OpenAI에 전송하는 데 동의/))
    fireEvent.click(confirm)
    expect(adjust).toHaveBeenCalledWith(card.payload.blockedTimes, '에세이 초안, 분량 절반', '2030-01-07', essay, true)
  })
  it('shows a weekly time change as what it adds', () => {
    const card = { kind: 'settings' as const, revision: 4, payload: { slots: [{ day: 0, hour: 9 }, { day: 0, hour: 10 }, { day: 0, hour: 19 }], view: 'timeline' as const },
      change: { added: [{ day: 0, hour: 9 }, { day: 0, hour: 10 }], removed: [] } }
    render(<PlannerChat state={{ ...base, plannerThreads: { essay: { messages: [], action: card } } }} busy={false} run={run} project={essay} onApplyPlan={vi.fn()}/>)
    expect(screen.getByText('월 9~11시')).toBeTruthy()
    expect(screen.getByText(/바꾼 뒤에는 주 3시간/)).toBeTruthy()
  })
  it('says the plan runs until the project deadline when that comes first', () => {
    const card = { kind: 'plan' as const, revision: 4, payload: { goal: '초안', startDate: '2030-01-07' } }
    render(<PlannerChat state={{ ...base, plannerThreads: { essay: { messages: [], action: card } } }} busy={false} run={run}
      project={{ ...essay, dueDate: '2030-01-09' }} onApplyPlan={vi.fn()}/>)
    expect(screen.getByText('2030-01-07 ~ 2030-01-09 (프로젝트 마감까지)')).toBeTruthy()
  })
  it('shows which skill answered and what it looked up', () => {
    const answered = { messages: [{ id: 'm1', role: 'assistant' as const, content: '수요일은 1시간 남았어요.', skill: 'answer', lookups: ['week'] }], action: null }
    render(<PlannerChat state={{ ...base, plannerThreads: { essay: answered } }} busy={false} run={run} project={essay} onApplyPlan={vi.fn()}/>)
    expect(screen.getByText('답하기 · 이번 주 시간표 확인')).toBeTruthy()
  })
  it('opens a fresh conversation for a newly created project', () => {
    const fresh = { ...essay, id: 'new', title: '새 공부' }
    render(<PlannerChat state={{ ...base, plannerThreads: threads }} busy={false} run={run} project={fresh} onApplyPlan={vi.fn()}/>)
    expect(screen.getByRole('heading', { name: '새 공부' })).toBeTruthy()
    expect(screen.getByRole('log').textContent).toContain('‘새 공부’ 대화를 시작해요.')
    expect(screen.getByRole('log').textContent).toContain('이 프로젝트만 다르게 하고 싶은 점')
  })
})

it('shows why the plan fits this user, with where each value came from', () => {
  render(<PlanReasons open reasons={[
    { key: 'taskLength', applied: '작업은 한 번에 20분 이하로 나눴습니다.', because: '확정한 집중 가능 시간 20분에 맞췄습니다.', source: 'declared', fields: ['focusMinutes'] },
    { key: 'scheduleStyle', applied: '시각 대신 순서만 정한 할 일 목록으로 보여 줍니다.', because: '일정이 불규칙하다고 답했습니다.', source: 'declared', fields: ['regularity'] },
    { key: 'taskLength2', applied: '작업은 한 번에 20분 이하로 나눴습니다.', because: '최근 실행 기록 3건을 근거로 승인한 변경(50분 → 20분)을 따랐습니다.', source: 'learned', fields: ['learnedPatterns'] },
    { key: 'dailyCap', applied: '하루에 최대 60분만 계획했습니다.', because: '이 프로젝트에서 하루 계획량을 따로 정했습니다. 기본 프로필 값은 90분입니다.', source: 'project', fields: ['dailyPlannedMinutes'] },
  ]}/>)
  expect(screen.getByText('이 계획에 반영한 나의 특성 4가지')).toBeTruthy()
  expect(screen.getByText('이 프로젝트 설정')).toBeTruthy()
  expect(screen.getByText('확정한 집중 가능 시간 20분에 맞췄습니다.')).toBeTruthy()
  expect(screen.getByText('설문 답변 · 한 번의 집중 시간')).toBeTruthy()
  expect(screen.getByText('설문 답변 · 생활 규칙성')).toBeTruthy()
  expect(screen.getByText('실행 기록으로 학습')).toBeTruthy()
})

it('renders nothing for plans made before reasons existed', () => {
  const { container } = render(<PlanReasons open reasons={[]}/>)
  expect(container.innerHTML).toBe('')
})

it('shows a learned focus time proposal with its numbers', () => {
  const proposal = {
    id: 'p1', profileId: 'profile1', projectId: null, status: 'pending', ruleVersion: 'focus-time-v1', createdAt: '', decidedAt: null,
    proposedChanges: { focusTime: { from: 'unknown', to: 'evening' } }, sizedBy: 'evidence', sizing: '끝낸 비율이 가장 높은 저녁을 제안합니다.',
    focusStats: { morning: { planned: 4, finished: 1 }, evening: { planned: 5, finished: 5 } },
    reason: '최근 기록에서 오전 4건 중 1건, 저녁 5건 중 5건을 끝냈습니다.', evidenceRecordIds: ['r1'],
  } as const
  const state = { revision: 2, settings: { slots: [], view: 'timeline' }, plan: null, profile: { id: 'profile1' }, executionRecords: [], profileUpdateProposals: [proposal] } as unknown as ExecutionState
  render(<ExecutionLearning state={state} busy={false} run={vi.fn()}/>)
  expect(screen.getByRole('heading', { name: '집중이 잘 되는 시간대 모름 → 저녁' })).toBeTruthy()
  expect(screen.getByText('오전 4건 중 1건 완료 · 저녁 5건 중 5건 완료')).toBeTruthy()
})

it('shows that the focus time is learned from records, not asked', () => {
  const profile = { id: 'profile1', status: 'confirmed', source: 'demo', schemaVersion: '2.0', createdAt: '', learnedPatterns: [],
    declaredFacts: { roles: ['student'], regularity: 'regular', barriers: ['none'], focusMinutes: 30, dailyMinutes: null, energy: 'unknown', recovery: 'reduce', constraints: '', context: '' },
    planningPreferences: { blockMinutes: 30, breakMinutes: 5, dailyPlannedMinutes: null, scheduleStyle: 'time_blocks', recoveryPreference: 'reduce', starterMinutes: null, focusTime: 'unknown', status: 'confirmed' },
    insights: { summary: '요약', strategies: [], followUpQuestions: [] } }
  const state = { revision: 3, profile, profileDraft: null, settings: { slots: [{ day: 0, hour: 18 }], view: 'timeline' }, plan: null, planDraft: null,
    llmAvailable: false, model: 'test' } as unknown as ExecutionState
  render(<ExecutionView state={state} onChange={vi.fn()} projects={[]} milestones={[]} events={[]}/>)

  expect(screen.getByText('아직 몰라요')).toBeTruthy()
  expect(screen.queryByText(/집중이 잘되는 시간:/)).toBeNull()
})

describe('project settings', () => {
  const project = { id: 'project-a', title: '토익', goal: '800점', startDate: '2030-01-01', dueDate: '2030-03-31', priority: 'high', status: 'active' } as Project
  const state = {
    revision: 3, settings: { slots: [], view: 'timeline' }, plan: null,
    profile: { planningPreferences: { blockMinutes: 30, dailyPlannedMinutes: 90, starterMinutes: null, recoveryPreference: 'reduce' } },
    projectProfiles: { 'project-a': { id: 'pp1', version: 1, overrides: { blockMinutes: { value: 20, source: 'learned', proposalId: 'proposal-1' } } } },
  } as unknown as ExecutionState

  it('shows what this project learned and saves only the values the user set', async () => {
    const run = vi.fn(async (action: () => Promise<ExecutionState>) => { await action(); return true })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 4 }) })
    vi.stubGlobal('fetch', fetchMock)
    render(<ProjectSettings state={state} project={project} busy={false} run={run} editable/>)

    expect(screen.getByText('개발용 · 프로젝트 값 직접 넣기 · 한 번에 집중할 시간 20분(기록으로 학습)')).toBeTruthy()
    expect(screen.getByText('이 프로젝트 기록으로 학습한 값: 20분 · 값을 정하면 직접 정한 값으로 바뀝니다')).toBeTruthy()
    expect(screen.getByPlaceholderText('비우면 20분')).toBeTruthy()  // empty keeps the learned value
    fireEvent.change(screen.getByLabelText(/하루 계획량/), { target: { value: '60' } })
    fireEvent.click(screen.getByText('이 프로젝트 설정 저장'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/execution/projects/project-a/profile')
    expect(fetchMock.mock.calls[0][1].method).toBe('PUT')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ revision: 3, overrides: { dailyPlannedMinutes: 60 } })
  })

  it('shows users what the project adapted, without settings to tune', () => {
    render(<ProjectSettings state={state} project={project} busy={false} run={vi.fn()}/>)
    const note = screen.getByRole('note').textContent
    expect(note).toContain('기본 프로필 · 모든 프로젝트 공통 · 한 번에 집중할 시간 30분 · 하루 계획량 90분')
    expect(note).toContain('이 프로젝트만 · 한 번에 집중할 시간 20분 (이 프로젝트 실행 기록으로 학습, 기본 30분)')
    expect(screen.queryByRole('spinbutton')).toBeNull()
    expect(screen.queryByText('이 프로젝트 설정 저장')).toBeNull()
    cleanup()
    render(<ProjectSettings state={{ ...state, projectProfiles: {} } as ExecutionState} project={project} busy={false} run={vi.fn()}/>)
    expect(screen.getByRole('note').textContent).toContain('이 프로젝트만 · 아직 기본 프로필과 같아요')
  })

  it('explains a value that breaks the profile rules without sending it', () => {
    const run = vi.fn()
    render(<ProjectSettings state={state} project={project} busy={false} run={run} editable/>)
    fireEvent.change(screen.getByLabelText(/하루 계획량/), { target: { value: '15' } })
    fireEvent.click(screen.getByText('이 프로젝트 설정 저장'))
    expect(screen.getByRole('alert').textContent).toBe('한 번에 집중할 시간은 하루 계획량보다 길 수 없습니다.')
    fireEvent.change(screen.getByLabelText(/하루 계획량/), { target: { value: '800' } })
    fireEvent.click(screen.getByText('이 프로젝트 설정 저장'))
    expect(screen.getByRole('alert').textContent).toContain('1~720')
    expect(run).not.toHaveBeenCalled()
  })
})

describe('home check-in count', () => {
  const entry = (id: string, day: string, completed = false) => ({ id, kind: 'task', title: id, minutes: 30, doneWhen: '끝', dueDate: null,
    start: `${day}T19:00`, end: `${day}T19:30`, completed, projectId: 'p1' })
  const state = (startDate: string, endDate: string, entries: ReturnType<typeof entry>[]) => ({
    revision: 1, profile: null, profileDraft: null, settings: { slots: [], view: 'timeline' }, planDraft: null, llmAvailable: true, model: 'test',
    executionRecords: [], plan: { id: 'w', profileId: 'p', projectId: null, project: null, goal: '', startDate, endDate, timezone: 'Asia/Seoul',
      status: 'confirmed', slots: [], entries, pendingTasks: [] },
  }) as unknown as ExecutionState

  it('counts today separately from earlier unfinished work this week', () => {
    const week = state('2030-01-07', '2030-01-13', [entry('a', '2030-01-07'), entry('b', '2030-01-09'), entry('c', '2030-01-09'),
      entry('d', '2030-01-08', true), entry('e', '2030-01-10')])
    expect(checkInCounts(week, 'p1', '2030-01-09')).toEqual({ today: 2, late: 1 })
    expect(checkInLabel({ today: 2, late: 1 })).toBe('오늘 체크인 · 2개 · 밀린 1개')
    expect(checkInLabel({ today: 0, late: 1 })).toBe('밀린 체크인 · 1개')
    expect(checkInLabel({ today: 0, late: 0 })).toBe('')
  })

  it('does not count a week that has already ended', () => {
    const ended = state('2030-01-07', '2030-01-13', [entry('a', '2030-01-07'), entry('b', '2030-01-10')])
    expect(checkInTasks(ended, 'p1', '2030-01-20').due).toHaveLength(2)
    expect(checkInCounts(ended, 'p1', '2030-01-20')).toEqual({ today: 0, late: 0 })
  })
})


describe('weekly plan editing and one-time consent', () => {
  const plan = { id: 'w', profileId: 'p', projectId: null, project: null, goal: '', startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul',
    status: 'confirmed', slots: [], pendingTasks: [], entries: [
      { id: 't1', kind: 'task', title: '자료 조사', minutes: 30, doneWhen: '메모', dueDate: null, start: '2030-01-07T19:00', end: '2030-01-07T19:30', completed: false, projectId: 'essay' },
      { id: 'b1', kind: 'break', title: '휴식', minutes: 5, doneWhen: '', dueDate: null, start: '2030-01-07T19:30', end: '2030-01-07T19:35', completed: false }] }
  const base = { revision: 7, profile: null, profileDraft: null, settings: { slots: [], view: 'timeline' }, planDraft: null,
    llmAvailable: true, model: 'test', executionRecords: [], plan } as unknown as ExecutionState
  const essay = { id: 'essay', title: '에세이', goal: '초안', startDate: '2030-01-01', dueDate: '2030-01-31', priority: 'high', status: 'active' } as Project

  it('asks again before deleting a task and only then removes it', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...base, revision: 8 }) })
    vi.stubGlobal('fetch', fetchMock)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<ExecutionView state={base} onChange={vi.fn()} projects={[essay]} milestones={[]} events={[]} section="home"/>)
    const card = screen.getByRole('region', { name: '확정한 주간 계획' })
    expect(card.textContent).not.toContain('휴식')
    fireEvent.click(screen.getByRole('button', { name: '자료 조사 삭제' }))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '자료 조사 삭제' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/execution/task/remove', expect.objectContaining({ method: 'POST' })))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ revision: 7, planId: 'w', taskId: 't1' })
  })

  it('shows the AI consent checkbox until it is given once', () => {
    const props = { state: base, busy: false, run: vi.fn(), project: essay, onApplyPlan: vi.fn() }
    const { unmount } = render(<PlannerChat {...props}/>)
    fireEvent.click(screen.getByLabelText(/OpenAI에 전송하는 데 동의/))
    expect(screen.queryByLabelText(/OpenAI에 전송하는 데 동의/)).toBeNull()
    unmount()
    render(<PlannerChat {...props}/>)
    expect(screen.queryByLabelText(/OpenAI에 전송하는 데 동의/)).toBeNull()
  })
})

it('colors deadlines by how close they are', async () => {
  const { deadlineTone, daysUntil } = await import('../../shared/deadline')
  const now = new Date('2030-01-10T09:00:00')
  expect(daysUntil('2030-01-13', now)).toBe(3)
  expect(deadlineTone('2030-01-09', now)).toBe('danger')
  expect(deadlineTone('2030-01-13', now)).toBe('danger')
  expect(deadlineTone('2030-01-17', now)).toBe('warn')
  expect(deadlineTone('2030-01-30', now)).toBe('neutral')
})
