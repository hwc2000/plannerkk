import type { AvailabilitySlot, FixedBlock } from '../../shared/types'

const days = ['월', '화', '수', '목', '금', '토', '일']
const minutesOf = (time: string) => Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5))

/** Minutes of this weekday hour that the fixed schedule takes (blocks never overlap on one day). */
export function fixedMinutes(fixed: FixedBlock[], day: number, hour: number) {
  return fixed.filter(b => b.days.includes(day)).reduce((sum, b) =>
    sum + Math.max(0, Math.min(minutesOf(b.end), (hour + 1) * 60) - Math.max(minutesOf(b.start), hour * 60)), 0)
}

export function AvailabilityGrid({ slots, onChange, fixed = [], disabled = false }: {
  slots: AvailabilitySlot[]; onChange: (slots: AvailabilitySlot[]) => void; fixed?: FixedBlock[]; disabled?: boolean
}) {
  function toggle(day: number, hour: number) {
    const exists = slots.some(s => s.day === day && s.hour === hour)
    onChange(exists ? slots.filter(s => s.day !== day || s.hour !== hour) : [...slots, { day, hour }].sort((a,b) => a.day-b.day || a.hour-b.hour))
  }
  const takenHours = slots.filter(s => fixedMinutes(fixed, s.day, s.hour) >= 60).length
  return <fieldset disabled={disabled} className="execution-fieldset">
    <legend>요일별 가용 시간</legend>
    <p className="execution-help">월~일, 08~23시 중 계획에 쓸 시간을 선택하세요. 고정 일정과 기존 캘린더 일정은 자동으로 제외합니다.</p>
    <div className="execution-actions">
      <button type="button" className="secondary-button" onClick={() => onChange(Array.from({ length: 15 }, (_, i) => ({ day: Math.floor(i / 3), hour: 18 + i % 3 })))}>평일 18~21시 선택</button>
      <button type="button" className="secondary-button" onClick={() => onChange([])}>선택 해제</button>
      <span role="status">주 {slots.length}시간 선택{takenHours > 0 && ` · 고정 일정 ${takenHours}시간 제외`}</span>
    </div>
    <div className="availability-scroll"><table className="availability-table"><caption className="sr-only">주간 가용 시간 선택</caption><thead><tr><th scope="col">시간</th>{days.map(d => <th key={d} scope="col">{d}</th>)}</tr></thead>
      <tbody>{Array.from({ length: 15 }, (_, i) => i+8).map(hour => <tr key={hour}>
        <th scope="row">{String(hour).padStart(2,'0')}~{String(hour+1).padStart(2,'0')}</th>
        {days.map((name, day) => {
          const taken = fixedMinutes(fixed, day, hour)
          const label = `${name}요일 ${hour}시부터 ${hour+1}시`
          // A fully fixed hour is never planned in, so it is shown as taken instead of as a choice.
          if (taken >= 60) return <td key={day}><span className="availability-cell fixed" title="고정 일정" aria-label={`${label} 고정 일정`}/></td>
          return <td key={day}><label className={`availability-cell ${taken ? 'partly-fixed' : ''}`} title={taken ? `고정 일정 ${taken}분 제외` : undefined}>
            <input type="checkbox" aria-label={label} checked={slots.some(s => s.day===day && s.hour===hour)} onChange={() => toggle(day,hour)} /><span aria-hidden="true" />
          </label></td>
        })}
      </tr>)}</tbody></table></div>
  </fieldset>
}
