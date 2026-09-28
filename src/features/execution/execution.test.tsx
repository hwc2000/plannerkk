// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { AvailabilityGrid } from './AvailabilityGrid'
import { ProfileForm } from './ProfileForm'
import { planCalendarEvents } from './api'
import type { AvailabilitySlot, ExecutionPlan } from '../../shared/types'

afterEach(cleanup)
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
