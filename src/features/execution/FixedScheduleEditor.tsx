import { useEffect, useState } from 'react'
import type { BlockedTime, FixedBlock } from '../../shared/types'

const weekdays = ['월', '화', '수', '목', '금', '토', '일']
const times = Array.from({ length: 48 }, (_, n) => `${String(Math.floor(n / 2)).padStart(2, '0')}:${n % 2 ? '30' : '00'}`)
// The server keeps times of one day; the end of the day is stored as 23:59 and shown as 24:00.
const ends = [...times.slice(1), '23:59']
const shown = (time: string) => time === '23:59' ? '24:00' : time
type Draft = Omit<FixedBlock, 'id'> & { id?: string }

export const describeFixed = (block: Draft) =>
  `${block.days.map(d => weekdays[d]).join('·')} ${shown(block.start)}~${shown(block.end)}`

/** Hours taken out on one date, e.g. 1/9(수) 18~21시. */
export function blockedLabel(b: Omit<BlockedTime, 'id'>) {
  const day = new Date(`${b.date}T12:00:00`)
  return `${day.getMonth() + 1}/${day.getDate()}(${weekdays[(day.getDay() + 6) % 7]}) ${b.startHour}~${b.endHour}시`
}

/** Weekly commitments the user can change any time. Saving takes them out of every plan; the server moves tasks that collide. */
export function FixedScheduleEditor({ items, disabled, onSave }: {
  items: FixedBlock[]; disabled: boolean; onSave: (items: Draft[]) => Promise<boolean>
}) {
  const saved = JSON.stringify(items)
  const [blocks, setBlocks] = useState<Draft[]>(items)
  const [days, setDays] = useState<number[]>([])
  const [start, setStart] = useState('09:00')
  const [end, setEnd] = useState('18:00')
  const [error, setError] = useState('')
  // Follow the server whenever what is saved changes.
  useEffect(() => { setBlocks(JSON.parse(saved)) }, [saved])
  const dirty = JSON.stringify(blocks) !== saved

  function add() {
    if (!days.length) { setError('요일을 선택해 주세요.'); return }
    if (start >= end) { setError('종료 시간은 시작 시간보다 늦어야 해요. 자정을 넘으면 나누어 추가해 주세요.'); return }
    if (blocks.some(b => b.days.some(d => days.includes(d)) && b.start < end && start < b.end)) { setError('같은 요일에 겹치는 일정이 있어요. 시간을 확인해 주세요.'); return }
    setBlocks(previous => [...previous, { days: [...days].sort(), start, end }]); setDays([]); setError('')
  }
  return <fieldset className="execution-fieldset" disabled={disabled}>
    <legend>고정 일정</legend>
    <p className="execution-help">수업·출근처럼 매주 반복되는 일정이에요. 저장하면 계획할 시간에서 자동으로 빠지고, 겹치는 작업은 빈 시간으로 옮겨요.</p>
    {blocks.length > 0 ? <ul className="fixed-list">{blocks.map((block, i) => <li key={block.id ?? `new-${i}`}>{describeFixed(block)}
      <button type="button" className="secondary-button" aria-label={`${describeFixed(block)} 삭제`} onClick={() => setBlocks(previous => previous.filter((_, n) => n !== i))}>삭제</button></li>)}</ul>
      : <p className="execution-help">저장한 고정 일정이 없어요.</p>}
    <div className="profile-chat-choices" role="group" aria-label="고정 일정 요일">
      {weekdays.map((day, i) => <button type="button" className="secondary-button" key={day} aria-pressed={days.includes(i)} onClick={() => setDays(previous => previous.includes(i) ? previous.filter(d => d !== i) : [...previous, i])}>{day}요일</button>)}
      <button type="button" className="secondary-button" onClick={() => setDays([0, 1, 2, 3, 4])}>평일 선택</button>
      <button type="button" className="secondary-button" onClick={() => setDays([5, 6])}>주말 선택</button>
    </div>
    <div className="execution-actions">
      <label className="execution-label">시작 시간<select value={start} onChange={e => setStart(e.target.value)}>{times.map(t => <option key={t}>{t}</option>)}</select></label>
      <label className="execution-label">종료 시간<select value={end} onChange={e => setEnd(e.target.value)}>{ends.map(t => <option key={t} value={t}>{shown(t)}</option>)}</select></label>
      <button type="button" className="secondary-button" onClick={add}>일정 추가</button>
    </div>
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="execution-actions">
      <button type="button" className="primary-button" disabled={!dirty || days.length > 0} onClick={() => { void onSave(blocks) }}>고정 일정 저장</button>
      {dirty && <button type="button" className="secondary-button" onClick={() => { setBlocks(JSON.parse(saved)); setError('') }}>되돌리기</button>}
      {days.length > 0 && <span className="execution-help">선택 중인 요일은 ‘일정 추가’를 눌러 목록에 넣어 주세요.</span>}
    </div>
  </fieldset>
}
