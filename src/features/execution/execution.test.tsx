// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { AvailabilityGrid } from './AvailabilityGrid'
import { FixedSchedulePicker } from './FixedSchedulePicker'
import { ProfileForm } from './ProfileForm'
import { ProfileChat } from './ProfileChat'
import { ExecutionView } from './ExecutionView'
import { planCalendarEvents } from './api'
import type { AvailabilitySlot, ExecutionPlan, ExecutionState } from '../../shared/types'

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
it('maps confirmed tasks once and omits breaks', () => {
  const plan={id:'week1',status:'confirmed',projectId:null,entries:[{id:'task1',kind:'task',start:'2030-01-07T18:00',end:'2030-01-07T18:25',title:'문제 풀기',completed:true},{id:'break1',kind:'break',start:'2030-01-07T18:25',end:'2030-01-07T18:30'}]} as ExecutionPlan
  const events=planCalendarEvents(plan,[])
  expect(events).toHaveLength(1)
  expect(events[0]).toMatchObject({id:'execution:week1:task1',title:'✓ 문제 풀기',date:'2030-01-07',startTime:'18:00',endTime:'18:25'})
  expect(planCalendarEvents({...plan,status:'draft'},[])).toEqual([])
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
