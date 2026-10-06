// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { AvailabilityGrid } from './AvailabilityGrid'
import { ProfileForm } from './ProfileForm'
import { approveProposalAndReplan, planCalendarEvents } from './api'
import type { AvailabilitySlot, ExecutionPlan, ExecutionState } from '../../shared/types'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
describe('execution onboarding and availability',()=>{
  it('selects and deselects weekly hours without duplicates',()=>{
    function Harness(){const [slots,setSlots]=useState<AvailabilitySlot[]>([]);return <AvailabilityGrid slots={slots} onChange={setSlots}/>}
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
  it('preserves unknown duration and exclusive no-barrier answer',async()=>{
    const generate=vi.fn().mockResolvedValue(undefined)
    render(<ProfileForm busy={false} llmAvailable={false} onGenerate={generate}/>)
    fireEvent.click(screen.getByLabelText('학생'));fireEvent.click(screen.getByLabelText('대체로 규칙적'));fireEvent.click(screen.getByText('다음'))
    fireEvent.click(screen.getByLabelText('시작이 어려움'));fireEvent.click(screen.getByLabelText('특별한 어려움 없음'))
    expect((screen.getByLabelText('시작이 어려움') as HTMLInputElement).checked).toBe(false)
    fireEvent.click(screen.getByText('다음'));fireEvent.click(screen.getByLabelText('저녁·밤'));fireEvent.click(screen.getByText('다음'))
    fireEvent.click(screen.getByLabelText('할 일을 줄임'));fireEvent.click(screen.getByText('프로필 생성'))
    expect(generate).toHaveBeenCalledWith(expect.objectContaining({roles:['student'],barriers:['none'],focusMinutes:null,dailyMinutes:null}), 'demo', false)
  })
})
describe('calendar bridge',()=>{
  const plan={id:'week1',status:'confirmed',projectId:null,entries:[{id:'task1',kind:'task',start:'2030-01-07T18:00',end:'2030-01-07T18:25',title:'문제 풀기',completed:true},{id:'break1',kind:'break',start:'2030-01-07T18:25',end:'2030-01-07T18:30'}]} as ExecutionPlan
  it('maps confirmed tasks once, keeps times and completion, and omits breaks',()=>{
    const events=planCalendarEvents(plan,[])
    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({id:'execution:week1:task1',title:'✓ 문제 풀기',date:'2030-01-07',startTime:'18:00',endTime:'18:25'})
    expect(planCalendarEvents({...plan,status:'draft'},[])).toEqual([])
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
