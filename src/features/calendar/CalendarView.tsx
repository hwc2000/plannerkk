import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { dateKey, now, weekdayNames } from '../../shared/constants'
import { projectColor } from '../../shared/projectColors'
import { ProjectLegend } from '../../shared/ProjectLegend'
import type { CalendarEvent, Milestone, Project } from '../../shared/types'

type CalendarViewProps = {
  projects: Project[]
  milestones: Milestone[]
  events: CalendarEvent[]
  selectedDate: string
  setSelectedDate: (date: string) => void
  onCreateEvent: (date: string) => void
  onCreateMilestone: (projectId: string) => void
  onEditEvent: (id: string) => void
  onDeleteEvent: (id: string) => void
}

export function CalendarView({
  projects,
  milestones,
  events,
  selectedDate,
  setSelectedDate,
  onCreateEvent,
  onCreateMilestone,
  onEditEvent,
  onDeleteEvent,
}: CalendarViewProps) {
  const selectedDateValue = new Date(`${selectedDate}T00:00:00`)
  const [visibleYear, setVisibleYear] = useState(selectedDateValue.getFullYear())
  const [visibleMonth, setVisibleMonth] = useState(selectedDateValue.getMonth())
  const calendarStart = new Date(visibleYear, visibleMonth, 1 - new Date(visibleYear, visibleMonth, 1).getDay())
  const calendarDays = Array.from(
    { length: 42 },
    (_, index) => new Date(calendarStart.getFullYear(), calendarStart.getMonth(), calendarStart.getDate() + index),
  )
  const monthTitle = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long' })
    .format(new Date(visibleYear, visibleMonth, 1))

  function moveMonth(offset: number) {
    const next = new Date(visibleYear, visibleMonth + offset, 1)
    setVisibleYear(next.getFullYear())
    setVisibleMonth(next.getMonth())
    setSelectedDate(dateKey(next))
  }

  const entries = (date: string) => [
    ...milestones
      .filter((item) => item.startDate === date || item.dueDate === date)
      .map((item) => ({
        id: item.id,
        label: item.title,
        color: projectColor(item.projectId),
        type: 'milestone' as const,
        suffix: item.dueDate === date ? '마감' : '시작',
      })),
    ...events
      .filter((item) => item.date === date)
      .map((item) => ({
        id: item.id,
        label: item.title,
        color: item.projectId ? projectColor(item.projectId) : undefined,
        type: 'event' as const,
        suffix: `${item.startTime}–${item.endTime}`,
      })),
  ]
  const selected = calendarDays.find((day) => dateKey(day) === selectedDate) ?? now

  return (
    <section className="calendar-workspace">
      <div className="calendar-intro">
        <div>
          <p className="eyebrow">MONTHLY VIEW</p>
          <h1>일정과 단계별 할 일을 <em>함께</em>.</h1>
          <p>일정은 여기서 추가·수정·삭제하고, 단계별 할 일은 프로젝트에서 관리합니다.</p>
        </div>
        <button className="primary-button compact" onClick={() => onCreateEvent(selectedDate)}>
          <Plus size={16} />일정 추가
        </button>
      </div>
      <ProjectLegend projects={projects} />
      <div className="calendar-layout">
        <div className="month-card">
          <div className="month-card-head">
            <button className="month-nav" onClick={() => moveMonth(-1)} aria-label="이전 달">‹</button>
            <h2>{monthTitle}</h2>
            <button className="month-nav" onClick={() => moveMonth(1)} aria-label="다음 달">›</button>
          </div>
          <div className="weekday-row">
            {weekdayNames.map((day) => <span key={day}>{day}</span>)}
          </div>
          <div className="month-grid">
            {calendarDays.map((day) => {
              const date = dateKey(day)
              const plans = entries(date)
              return (
                <button
                  className={`calendar-cell ${day.getMonth() !== visibleMonth ? 'outside' : ''} ${date === selectedDate ? 'selected' : ''}`}
                  key={date}
                  onClick={() => setSelectedDate(date)}
                >
                  <span className="calendar-date">{day.getDate()}</span>
                  <div className="calendar-pills">
                    {plans.slice(0, 2).map((plan) => (
                      <span
                        className="calendar-pill project"
                        style={{ borderLeftColor: plan.color }}
                        key={`${plan.type}-${plan.id}`}
                      >
                        {plan.label}
                      </span>
                    ))}
                    {plans.length > 2 && <small>+{plans.length - 2}개</small>}
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <aside className="day-planner">
          <p className="section-kicker">
            {new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' }).format(selected)}
          </p>
          <h2>이 날의 일정</h2>
          <div className="selected-plan-list">
            {entries(selectedDate).map((entry) => (
              <div key={`${entry.type}-${entry.id}`}>
                <i style={{ backgroundColor: entry.color }} />
                <span>{entry.label}<small>{entry.suffix}</small></span>
                {entry.type === 'event' && (
                  <span className="row-actions">
                    <button onClick={() => onEditEvent(entry.id)} aria-label="일정 수정"><Pencil size={14} /></button>
                    <button onClick={() => onDeleteEvent(entry.id)} aria-label="일정 삭제"><Trash2 size={14} /></button>
                  </span>
                )}
              </div>
            ))}
            {!entries(selectedDate).length && <span className="empty-day">등록된 항목이 없습니다.</span>}
          </div>
          <button className="primary-button full" onClick={() => onCreateEvent(selectedDate)}>
            <Plus size={16} />일정 추가
          </button>
          <button
            className="secondary-button full-spaced"
            disabled={!projects.length}
            onClick={() => projects[0] && onCreateMilestone(projects[0].id)}
          >
            <Plus size={16} />단계별 할 일 추가
          </button>
        </aside>
      </div>
    </section>
  )
}
