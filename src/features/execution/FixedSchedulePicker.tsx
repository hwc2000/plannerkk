import { useState } from 'react'

const weekdays = ['월', '화', '수', '목', '금', '토', '일']
const times = Array.from({ length: 48 }, (_, n) => `${String(Math.floor(n / 2)).padStart(2, '0')}:${n % 2 ? '30' : '00'}`)
type FixedSlot = { days: number[]; start: string; end: string }
export function FixedSchedulePicker({ disabled, canSend, onSend }: {
  disabled: boolean; canSend: boolean; onSend: (text: string) => Promise<boolean>
}) {
  const [days, setDays] = useState<number[]>([])
  const [start, setStart] = useState('09:00')
  const [end, setEnd] = useState('18:00')
  const [slots, setSlots] = useState<FixedSlot[]>([])
  const [error, setError] = useState('')
  const describe = (slot: FixedSlot) => `${slot.days.map(d => weekdays[d] + '요일').join('·')} ${slot.start}~${slot.end}`
  function add() {
    if (!days.length) { setError('요일을 선택해 주세요.'); return }
    if (start >= end) { setError('종료 시간은 시작 시간보다 늦어야 해요. 자정을 넘으면 일정을 나누어 추가해 주세요.'); return }
    if (slots.some(s => s.days.some(d => days.includes(d)) && s.start < end && start < s.end)) { setError('같은 요일에 겹치는 일정이 있어요. 시간을 확인해 주세요.'); return }
    setSlots(previous => [...previous, { days: [...days].sort(), start, end }]); setDays([]); setError('')
  }
  return <fieldset className="execution-fieldset" disabled={disabled}>
    <legend>고정 일정 선택</legend>
    <p className="execution-help">매주 반복되는 시간을 골라 주세요. 여러 일정을 추가한 뒤 한 번에 보낼 수 있어요.</p>
    <div className="profile-chat-choices" role="group" aria-label="고정 일정 요일">
      {weekdays.map((day, i) => <button type="button" className="secondary-button" key={day} aria-pressed={days.includes(i)} onClick={() => setDays(previous => previous.includes(i) ? previous.filter(d => d !== i) : [...previous, i])}>{day}요일</button>)}
      <button type="button" className="secondary-button" onClick={() => setDays([0,1,2,3,4])}>평일 선택</button>
      <button type="button" className="secondary-button" onClick={() => setDays([5,6])}>주말 선택</button>
    </div>
    <div className="execution-actions">
      <label className="execution-label">시작 시간<select value={start} onChange={e => setStart(e.target.value)}>{times.map(t => <option key={t}>{t}</option>)}</select></label>
      <label className="execution-label">종료 시간<select value={end} onChange={e => setEnd(e.target.value)}>{[...times,'24:00'].map(t => <option key={t}>{t}</option>)}</select></label>
      <button type="button" className="secondary-button" onClick={add}>일정 추가</button>
    </div>
    {error && <p role="alert" className="form-error">{error}</p>}
    <ul>{slots.map((slot, i) => <li key={i}>{describe(slot)} <button type="button" className="secondary-button" aria-label={`${describe(slot)} 삭제`} onClick={() => setSlots(previous => previous.filter((_, n) => n !== i))}>삭제</button></li>)}</ul>
    <div className="execution-actions">
      <button type="button" className="primary-button" disabled={!canSend || !slots.length || !!days.length} onClick={() => { void onSend(slots.map(describe).join('; ')) }}>고정 일정 보내기{slots.length ? ` (${slots.length})` : ''}</button>
      <button type="button" className="secondary-button" disabled={!canSend || !!slots.length || !!days.length} onClick={() => { void onSend('없음') }}>고정 일정 없음</button>
      {days.length > 0 && <><span className="execution-help">선택 중인 시간은 ‘일정 추가’를 눌러 목록에 넣어 주세요.</span><button type="button" className="secondary-button" onClick={() => setDays([])}>요일 선택 해제</button></>}
    </div>
  </fieldset>
}
