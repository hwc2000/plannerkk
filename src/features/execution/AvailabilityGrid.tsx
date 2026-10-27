import type { AvailabilitySlot, BlockedTime } from '../../shared/types'

const days = ['월', '화', '수', '목', '금', '토', '일']

/** One blocked time of this week, e.g. 10/30(금) 19~22시. */
export function blockedLabel(b: Omit<BlockedTime, 'id'>) {
  const day = new Date(`${b.date}T12:00:00`)
  return `${day.getMonth() + 1}/${day.getDate()}(${days[(day.getDay() + 6) % 7]}) ${b.startHour}~${b.endHour}시`
}

export function AvailabilityGrid({ slots, onChange, disabled = false }: {
  slots: AvailabilitySlot[]; onChange: (slots: AvailabilitySlot[]) => void; disabled?: boolean
}) {
  function toggle(day: number, hour: number) {
    const exists = slots.some(s => s.day === day && s.hour === hour)
    onChange(exists ? slots.filter(s => s.day !== day || s.hour !== hour) : [...slots, { day, hour }].sort((a,b) => a.day-b.day || a.hour-b.hour))
  }
  return <fieldset disabled={disabled} className="execution-fieldset">
    <legend>요일별 가용 시간</legend>
    <p className="execution-help">월~일, 08~23시 중 이번 주에 계획을 넣어도 되는 시간을 고르세요. 캘린더 일정과 겹치는 시간은 자동으로 빠집니다.</p>
    <div className="execution-actions">
      <button type="button" className="secondary-button" onClick={() => onChange(Array.from({ length: 15 }, (_, i) => ({ day: Math.floor(i / 3), hour: 18 + i % 3 })))}>평일 18~21시 선택</button>
      <button type="button" className="secondary-button" onClick={() => onChange([])}>선택 해제</button>
      <span role="status">주 {slots.length}시간 선택</span>
    </div>
    <div className="availability-scroll"><table className="availability-table"><caption className="sr-only">주간 가용 시간 선택</caption><thead><tr><th scope="col">시간</th>{days.map(d => <th key={d} scope="col">{d}</th>)}</tr></thead>
      <tbody>{Array.from({ length: 15 }, (_, i) => i+8).map(hour => <tr key={hour}>
        <th scope="row">{String(hour).padStart(2,'0')}~{String(hour+1).padStart(2,'0')}</th>
        {days.map((name, day) => <td key={day}><label className="availability-cell">
          <input type="checkbox" aria-label={`${name}요일 ${hour}시부터 ${hour+1}시`} checked={slots.some(s => s.day===day && s.hour===hour)} onChange={() => toggle(day,hour)} /><span aria-hidden="true" />
        </label></td>)}
      </tr>)}</tbody></table></div>
  </fieldset>
}
