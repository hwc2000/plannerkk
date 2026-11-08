// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { ProjectForm } from './ProjectForm'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

function open(projectHours?: Array<{ day: number; hour: number }> | null) {
  const onSave = vi.fn()
  render(<ProjectForm editor={{ kind: 'project' }} projects={[]} milestones={[]} projectHours={projectHours}
    onClose={() => {}} onSave={onSave} />)
  fireEvent.change(screen.getByPlaceholderText('예: 기말 에세이'), { target: { value: '운동' } })
  return onSave
}

it('saves the weekdays and hours a project is done in', () => {
  const onSave = open()
  fireEvent.click(screen.getByRole('button', { name: '정해져 있어요' }))
  const days = within(screen.getByRole('group', { name: '요일' }))
  for (const day of ['월', '수', '금']) fireEvent.click(days.getByRole('button', { name: day }))
  fireEvent.change(screen.getByLabelText('시작 시각'), { target: { value: '19' } })
  fireEvent.change(screen.getByLabelText('끝 시각'), { target: { value: '20' } })
  expect(screen.getByText(/월·수·금 19~20시에만/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /만들기|저장/ }))
  expect(onSave.mock.calls[0][1]).toEqual([{ day: 0, hour: 19 }, { day: 2, hour: 19 }, { day: 4, hour: 19 }])
})

it('"딱히 없어요" is an answer, and leaving it alone is not', () => {
  const onSave = open()
  fireEvent.click(screen.getByRole('button', { name: /만들기|저장/ }))
  expect(onSave.mock.calls[0][1]).toBeUndefined()
  cleanup()
  const again = open()
  fireEvent.click(screen.getByRole('button', { name: '딱히 없어요' }))
  fireEvent.click(screen.getByRole('button', { name: /만들기|저장/ }))
  expect(again.mock.calls[0][1]).toEqual([])
})

it('picking hours without a weekday cannot be saved', () => {
  const onSave = open()
  fireEvent.click(screen.getByRole('button', { name: '정해져 있어요' }))
  expect(screen.getByText(/요일을 하나 이상 고르고/)).toBeTruthy()
  expect((screen.getByRole('button', { name: /만들기|저장/ }) as HTMLButtonElement).disabled).toBe(true)
  expect(onSave).not.toHaveBeenCalled()
})
