// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { AvailabilityGrid } from './AvailabilityGrid'
import { FixedSchedulePicker } from './FixedSchedulePicker'
import { ProfileForm } from './ProfileForm'
import { ProfileChat } from './ProfileChat'
import { ExecutionView } from './ExecutionView'
import { ExecutionLearning } from './ExecutionLearning'
import { PlannerChat } from './PlannerChat'
import { PlanReasons } from './PlanReasons'
import { ProjectSettings } from './ProjectSettings'
import { approveProposalAndReplan, planCalendarEvents, planIsStale, replansCurrentPlan } from './api'
import type { AvailabilitySlot, ExecutionPlan, ExecutionState, Project } from '../../shared/types'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
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
  fireEvent.click(screen.getByLabelText('저녁·밤'))
  fireEvent.click(screen.getByText('다음'))
  fireEvent.click(screen.getByLabelText('할 일을 줄임'))
  fireEvent.click(screen.getByLabelText('시간 지정형 · 18:30~19:00 공부'))
  fireEvent.click(screen.getByText('프로필 생성'))
  await waitFor(() => expect(generate).toHaveBeenCalledWith(expect.objectContaining({
    roles: ['student'], barriers: ['none'], focusMinutes: null,
    dailyMinutes: null, scheduleStyle: 'time_blocks',
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

describe('conversational onboarding', () => {
  const state: ExecutionState = { revision: 0, profile: null, profileDraft: null, settings: { slots: [], view: 'timeline' }, plan: null, planDraft: null, llmAvailable: false, model: 'test' }
  const session = { id: 'chat-1', ready: false, answers: {}, messages: [{ id: 'msg-1', role: 'assistant', content: '어떤 생활인가요?' }], question: { field: 'roles', text: '어떤 생활인가요?', choices: [{ label: '학생', value: 'student' }, { label: '직장인', value: 'employee' }] } }
  it('opens a checkbox survey without chat or AI requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revision: 0, session: null }) }))
    render(<ExecutionView state={state} onChange={vi.fn()} projects={[]} milestones={[]} events={[]}/>)
    expect(screen.getByText('생활의 리듬')).toBeTruthy()
    expect(screen.queryByText('설문 양식으로 입력·수정')).toBeNull()
    expect(screen.queryByRole('log')).toBeNull()
    expect(fetch).not.toHaveBeenCalled()

  })
  it('resets profile only after confirmation and returns to a fresh chat', async () => {
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
  it('restores conversation and submits an answer using current revision', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ revision: 7, session }) }).mockResolvedValue({ ok: true, json: async () => ({ ...state, revision: 8 }) })
    vi.stubGlobal('fetch', fetcher)
    const run = vi.fn(async (action: () => Promise<ExecutionState>) => { await action(); return true })
    render(<ProfileChat state={{ ...state, revision: 7 }} busy={false} run={run} onReviewed={vi.fn()}/>)
    await screen.findByText('어떤 생활인가요?')
    fireEvent.click(screen.getByText('학생'))
    fireEvent.click(screen.getByText('직장인'))
    expect(run).not.toHaveBeenCalled()
    expect(screen.getByText('학생').getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByText('선택한 답변 보내기 (2)'))
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1))
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({ revision: 7, sessionId: 'chat-1', text: '학생, 직장인', mode: 'guided', consent: false })
  })
  it('toggles multiple choices and treats none/unknown as exclusive', async () => {
    const barriers = {...session, question: {field:'barriers',text:'이유?',choices:[{label:'피곤해요',value:'fatigue'},{label:'시작이 어려워요',value:'starting'},{label:'특별히 없어요',value:'none'},{label:'잘 모르겠어요',value:'unknown'}]}}
    const run = vi.fn().mockResolvedValue(false)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:true,json:async()=>({session:barriers})}))
    render(<ProfileChat state={state} busy={false} run={run} onReviewed={vi.fn()}/>)
    await screen.findByText('피곤해요')
    fireEvent.click(screen.getByText('피곤해요')); fireEvent.click(screen.getByText('시작이 어려워요'))
    expect(screen.getByText('선택한 답변 보내기 (2)')).toBeTruthy()
    fireEvent.click(screen.getByText('특별히 없어요'))
    expect(screen.getByText('피곤해요').getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(screen.getByText('잘 모르겠어요'))
    expect(screen.getByText('특별히 없어요').getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(screen.getByText('피곤해요'))
    expect(screen.getByText('잘 모르겠어요').getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(screen.getByText('선택한 답변 보내기 (1)'))
    await waitFor(()=>expect(run).toHaveBeenCalledTimes(1))
    expect(screen.getByText('피곤해요').getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByText('피곤해요'))
    expect((screen.getByText('선택한 답변 보내기') as HTMLButtonElement).disabled).toBe(true)
  })
  it('requires consent before sending a free-form AI message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revision: 0, session }) }))
    render(<ProfileChat state={{...state,llmAvailable:true}} busy={false} run={vi.fn()} onReviewed={vi.fn()}/>)
    await screen.findByText('어떤 생활인가요?')
    fireEvent.change(screen.getByLabelText('나의 답변'), { target: { value: '직장인이에요' } })
    expect((screen.getByText('보내기') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('이 대화 내용을 AI에 전송하여 답변을 정리하는 데 동의합니다.'))
    expect((screen.getByText('보내기') as HTMLButtonElement).disabled).toBe(false)
  })
  it('offers summary review and conversational corrections when complete', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revision: 0, session: {...session,ready:true,question:null,editableQuestions:[{field:'scheduleStyle',text:'방식?'}]} }) }))
    render(<ProfileChat state={state} busy={false} run={vi.fn()} onReviewed={vi.fn()}/>)
    await screen.findByText('프로필 요약 보기')
    expect(screen.getByText('선호하는 계획 방식 수정')).toBeTruthy()
    expect(screen.queryByText('설문 양식으로 입력·수정')).toBeNull()
  })
})


it('collects fixed weekly schedules without typing or sending on selection', async () => {
  const send = vi.fn().mockResolvedValue(true)
  render(<FixedSchedulePicker disabled={false} canSend={true} onSend={send}/>)
  expect(screen.queryByRole('textbox')).toBeNull()
  fireEvent.click(screen.getByText('평일 선택'))
  fireEvent.change(screen.getByLabelText('시작 시간'), {target:{value:'09:00'}})
  fireEvent.change(screen.getByLabelText('종료 시간'), {target:{value:'18:00'}})
  expect(send).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('일정 추가'))
  fireEvent.click(screen.getByText('토요일'))
  fireEvent.change(screen.getByLabelText('시작 시간'), {target:{value:'18:30'}})
  fireEvent.change(screen.getByLabelText('종료 시간'), {target:{value:'19:00'}})
  fireEvent.click(screen.getByText('일정 추가'))
  fireEvent.click(screen.getByText('고정 일정 보내기 (2)'))
  expect(send).toHaveBeenCalledWith('월요일·화요일·수요일·목요일·금요일 09:00~18:00; 토요일 18:30~19:00')
})
it('rejects invalid/overlapping fixed schedules and supports removal', () => {
  render(<FixedSchedulePicker disabled={false} canSend={true} onSend={vi.fn()}/>)
  fireEvent.click(screen.getByText('일정 추가'))
  expect(screen.getByRole('alert').textContent).toContain('요일')
  fireEvent.click(screen.getByText('월요일'))
  fireEvent.change(screen.getByLabelText('종료 시간'), {target:{value:'08:00'}})
  fireEvent.click(screen.getByText('일정 추가'))
  expect(screen.getByRole('alert').textContent).toContain('종료 시간')
  fireEvent.change(screen.getByLabelText('종료 시간'), {target:{value:'18:00'}})
  fireEvent.click(screen.getByText('일정 추가'))
  fireEvent.click(screen.getByText('월요일'))
  fireEvent.click(screen.getByText('일정 추가'))
  expect(screen.getByRole('alert').textContent).toContain('겹치는')
  fireEvent.click(screen.getByLabelText('월요일 09:00~18:00 삭제'))
  expect(screen.queryByText('고정 일정 보내기 (1)')).toBeNull()
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
  fireEvent.click(screen.getByLabelText('오전'))
  fireEvent.click(screen.getByText('다음'))
  fireEvent.click(screen.getByLabelText('할 일을 줄임'))
  fireEvent.click(screen.getByLabelText('작업량 지정형 · 공부 1시간, 운동 30분'))
  fireEvent.click(screen.getByText('프로필 생성'))
  await waitFor(()=>expect(submit).toHaveBeenCalledWith(expect.objectContaining({roles:['student','employee'],focusMinutes:25,dailyMinutes:null,scheduleStyle:'flexible_queue'}),'demo',false))
  expect(screen.queryByRole('textbox')).toBeNull()
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
      id: 'week1', profileId: 'profile1', projectId: 'project-b', project: null, goal: '졸업작품',
      startDate: '2030-01-07', endDate: '2030-01-13', timezone: 'Asia/Seoul', status: 'confirmed',
      slots: settings.slots, entries: [], pendingTasks: [],
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

  it('treats a plan as stale once its project settings change', () => {
    const plan = { id: 'week1', profileId: 'profile1', projectId: 'project-a', projectProfileId: null } as unknown as ExecutionPlan
    const state = { profile: { id: 'profile1' }, projectProfiles: {} } as unknown as ExecutionState
    expect(planIsStale(state, plan)).toBe(false)
    expect(planIsStale({ ...state, projectProfiles: { 'project-a': { id: 'project-a-v1' } } } as unknown as ExecutionState, plan)).toBe(true)
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
  it('opens the most recent project conversation and switches threads per project', () => {
    render(<PlannerChat state={{ ...base, plannerThreads: threads }} busy={false} run={run} projects={[essay, app]} onApplyPlan={vi.fn()}/>)
    expect(screen.getByRole('heading', { name: '앱 개발' })).toBeTruthy()
    expect(screen.getByRole('log').textContent).toContain('로그인 화면')
    fireEvent.click(screen.getByRole('button', { name: /에세이/ }))
    expect(screen.getByRole('heading', { name: '에세이' })).toBeTruthy()
    expect(screen.getByRole('log').textContent).toContain('에세이 초안 쓰기')
    expect(screen.getByRole('log').textContent).not.toContain('로그인 화면')
    fireEvent.click(screen.getByRole('button', { name: /자유 계획/ }))
    expect(screen.getByRole('log').textContent).toContain('프로젝트와 상관없는 할 일')
  })
  it('sends the selected project with the message after consent', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...base, revision: 5 }) })
    vi.stubGlobal('fetch', fetchMock)
    render(<PlannerChat state={base} busy={false} run={run} projects={[essay]} onApplyPlan={vi.fn()}/>)
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
    const { rerender } = render(<PlannerChat state={state} busy={false} run={run} projects={[essay, app]} onApplyPlan={apply}/>)
    fireEvent.click(screen.getByLabelText(/OpenAI에 전송하는 데 동의/))
    fireEvent.click(screen.getByText('확인하고 계획 초안 만들기'))
    expect(apply).toHaveBeenCalledWith('로그인 화면', '2030-01-07', app, true)
    rerender(<PlannerChat state={{ ...state, revision: 5 }} busy={false} run={run} projects={[essay, app]} onApplyPlan={apply}/>)
    expect(screen.queryByText('확인하고 계획 초안 만들기')).toBeNull()
  })
  it('opens a fresh conversation for a newly created project', () => {
    const { rerender } = render(<PlannerChat state={{ ...base, plannerThreads: threads }} busy={false} run={run} projects={[essay, app]} onApplyPlan={vi.fn()}/>)
    const fresh = { ...essay, id: 'new', title: '새 공부' }
    rerender(<PlannerChat state={{ ...base, plannerThreads: threads }} busy={false} run={run} projects={[essay, app, fresh]} onApplyPlan={vi.fn()}/>)
    expect(screen.getByRole('heading', { name: '새 공부' })).toBeTruthy()
    expect(screen.getByRole('log').textContent).toContain('‘새 공부’에서 이번 주에 하고 싶은 일')
  })
})

it('shows why the plan fits this user, with where each value came from', () => {
  render(<PlanReasons open reasons={[
    { key: 'taskLength', applied: '작업은 한 번에 20분 이하로 나눴습니다.', because: '확정한 집중 가능 시간 20분에 맞췄습니다.', source: 'declared', fields: ['focusMinutes'] },
    { key: 'buffer', applied: '선택한 가용 시간의 40% 이상을 여유분으로 비워 두었습니다.', because: '일정이 불규칙하다고 답했습니다.', source: 'declared', fields: ['regularity'] },
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

describe('project settings', () => {
  const project = { id: 'project-a', title: '토익', goal: '800점', startDate: '2030-01-01', dueDate: '2030-03-31', priority: 'high', status: 'active' } as Project
  const state = {
    revision: 3, settings: { slots: [], view: 'timeline' }, plan: null,
    profile: { planningPreferences: { blockMinutes: 30, dailyPlannedMinutes: 90, bufferPercent: 25, starterMinutes: null, recoveryPreference: 'reduce' } },
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
    expect(screen.getByRole('note').textContent).toBe(
      '이 프로젝트에 맞춰 적용 중: 한 번에 집중할 시간 20분 (이 프로젝트 실행 기록으로 학습, 기본 30분)')
    expect(screen.queryByRole('spinbutton')).toBeNull()
    expect(screen.queryByText('이 프로젝트 설정 저장')).toBeNull()
    cleanup()
    render(<ProjectSettings state={{ ...state, projectProfiles: {} } as ExecutionState} project={project} busy={false} run={vi.fn()}/>)
    expect(screen.getByRole('note').textContent).toContain('아직 기본 프로필대로 계획해요')
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
