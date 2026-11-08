import { useState } from 'react'
import { X } from 'lucide-react'
import { TODAY } from '../../shared/constants'
import { autoProjectColor, PROJECT_COLORS } from '../../shared/projectColors'
import type { AvailabilitySlot, Editor, Milestone, MilestoneStatus, Project, ProjectStatus } from '../../shared/types'
import { hoursText } from '../execution/api'

type ProjectFormProps = {
  editor: Exclude<Editor, null>
  projects: Project[]
  milestones: Milestone[]
  /** The hours this project is done in, as saved: null when never answered, [] for "딱히 없어요". */
  projectHours?: AvailabilitySlot[] | null
  onClose: () => void
  /** ``hours``: the answer about when this project is done, when the form gave one. */
  onSave: (value: Project | Milestone, hours?: AvailabilitySlot[]) => void
}

const DAYS = '월화수목금토일'
const HOURS = Array.from({ length: 15 }, (_, i) => i + 8)  // a slot starts 8:00-22:00

const createId = () => crypto.randomUUID()

const PERIODS: Array<[string, number]> = [['1주', 7], ['2주', 14], ['1개월', 30], ['3개월', 90]]
const PRIORITIES: Array<[Project['priority'], string]> = [['high', '높음'], ['medium', '보통'], ['low', '낮음']]

function addDays(date: string, days: number) {
  const value = new Date(`${date}T12:00:00`)
  value.setDate(value.getDate() + days)
  return value.toISOString().slice(0, 10)
}

function daysBetween(from: string, to: string) {
  return Math.round((new Date(`${to}T12:00:00`).getTime() - new Date(`${from}T12:00:00`).getTime()) / 86400000)
}

export function ProjectForm({ editor, projects, milestones, projectHours, onClose, onSave }: ProjectFormProps) {
  const existing = editor.kind === 'project'
    ? projects.find((item) => item.id === editor.id)
    : milestones.find((item) => item.id === editor.id)
  const [newId] = useState(createId)
  const entityId = existing?.id ?? newId
  const [title, setTitle] = useState(existing?.title ?? '')
  const [goal, setGoal] = useState(existing && 'goal' in existing ? existing.goal : '')
  const [startDate, setStartDate] = useState(existing?.startDate ?? TODAY)
  const [dueDate, setDueDate] = useState(existing?.dueDate ?? (editor.kind === 'project' ? addDays(TODAY, 13) : TODAY))
  const [color, setColor] = useState(existing && 'color' in existing ? existing.color ?? '' : '')
  const shownColor = color || autoProjectColor(entityId)
  const [priority, setPriority] = useState<Project['priority']>(
    existing && 'priority' in existing ? existing.priority : 'medium',
  )
  // Ending a project happens in its planner conversation, where its habits move to the user profile.
  const projectStatus: ProjectStatus = existing && 'goal' in existing ? existing.status : 'active'
  const [milestoneStatus, setMilestoneStatus] = useState<MilestoneStatus>(
    existing && 'estimatedHours' in existing ? existing.status : 'todo',
  )
  const [hours, setHours] = useState(existing && 'estimatedHours' in existing ? existing.estimatedHours : 2)
  const [projectId, setProjectId] = useState(
    existing && 'projectId' in existing ? existing.projectId : editor.projectId ?? projects[0]?.id ?? '',
  )
  const isProject = editor.kind === 'project'
  // When this project is done: set hours, "딱히 없어요", or not answered (asked later in its conversation).
  const [hoursChoice, setHoursChoice] = useState<'unset' | 'none' | 'set'>(
    projectHours == null ? 'unset' : projectHours.length ? 'set' : 'none')
  const [days, setDays] = useState<number[]>(() => [...new Set((projectHours ?? []).map(s => s.day))].sort())
  const [fromHour, setFromHour] = useState(() => projectHours?.length ? Math.min(...projectHours.map(s => s.hour)) : 19)
  const [toHour, setToHour] = useState(() => projectHours?.length ? Math.max(...projectHours.map(s => s.hour)) + 1 : 20)
  const [hoursTouched, setHoursTouched] = useState(false)
  const chosenHours: AvailabilitySlot[] = days.flatMap(day => HOURS.filter(h => h >= fromHour && h < toHour).map(hour => ({ day, hour })))
  const hoursValid = hoursChoice !== 'set' || (days.length > 0 && toHour > fromHour)
  const span = daysBetween(startDate, dueDate) + 1
  const left = daysBetween(TODAY, dueDate)
  const datesValid = dueDate >= startDate
  const canSave = !!title.trim() && datesValid && (isProject || !!projectId) && (!isProject || hoursValid)

  function touchHours(apply: () => void) {
    apply()
    setHoursTouched(true)
  }

  function submit() {
    if (!canSave) return
    if (isProject) {
      const hours = !hoursTouched ? undefined : hoursChoice === 'set' ? chosenHours : hoursChoice === 'none' ? [] : undefined
      onSave({ id: entityId, title: title.trim(), goal: goal.trim(), startDate, dueDate, priority, status: projectStatus, ...(color ? { color } : {}) }, hours)
    } else {
      onSave({ id: entityId, projectId, title: title.trim(), startDate, dueDate, estimatedHours: hours, status: milestoneStatus })
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form
        className="data-modal entity-modal"
        aria-label={isProject ? (existing ? '프로젝트 수정' : '새 프로젝트') : '단계별 할 일'}
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <header className="entity-modal-head">
          <div>
            <h2>{isProject ? (existing ? '프로젝트 수정' : '새 프로젝트') : (existing ? '할 일 수정' : '단계별 할 일 추가')}</h2>
            <p>{isProject
              ? (existing ? '이름·목표·기간을 바꿔도 대화와 계획은 그대로 이어져요.' : '만들면 전용 대화방이 생기고, 대화로 이번 주 계획을 세울 수 있어요.')
              : '프로젝트를 이루는 큰 단계를 적어 두면 계획을 짤 때 참고해요.'}</p>
          </div>
          <button className="close-button" type="button" onClick={onClose} aria-label="닫기"><X size={18} /></button>
        </header>

        <label className="field">
          <span className="field-label">{isProject ? '프로젝트 이름' : '할 일'}</span>
          <span className="field-name">
            {isProject && <i className="project-dot" style={{ background: shownColor }} aria-hidden="true" />}
            <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={120}
              placeholder={isProject ? '예: 기말 에세이' : '예: 자료 조사 정리'} />
          </span>
        </label>

        {isProject && (
          <label className="field">
            <span className="field-label">목표 <small>무엇을 끝내면 완료인가요?</small></span>
            <textarea rows={3} value={goal} onChange={(event) => setGoal(event.target.value)} maxLength={1000}
              placeholder="예: 11월 10일까지 3,000자 에세이를 완성해서 제출해요." />
          </label>
        )}

        {!isProject && (
          <label className="field">
            <span className="field-label">연결 프로젝트</span>
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)} required>
              <option value="">프로젝트 선택</option>
              {projects.map((project) => (
                <option value={project.id} key={project.id}>{project.title}</option>
              ))}
            </select>
          </label>
        )}

        <fieldset className="field">
          <legend className="field-label">기간</legend>
          <div className="form-date-grid">
            <label className="field-sub">시작
              <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required />
            </label>
            <label className="field-sub">마감
              <input type="date" min={startDate} value={dueDate} onChange={(event) => setDueDate(event.target.value)} required />
            </label>
          </div>
          {isProject && (
            <div className="chip-row" role="group" aria-label="기간 빠르게 정하기">
              {PERIODS.map(([label, days]) => (
                <button type="button" key={label} className="chip" aria-pressed={span === days} onClick={() => setDueDate(addDays(startDate, days - 1))}>{label}</button>
              ))}
            </div>
          )}
          <p className={datesValid ? 'field-hint' : 'field-hint error'}>
            {datesValid ? `${span}일 동안 · ${left > 0 ? `마감까지 ${left}일` : left === 0 ? '오늘 마감' : `마감 ${-left}일 지남`}` : '마감일은 시작일보다 같거나 늦어야 해요.'}
          </p>
        </fieldset>

        {isProject && (
          <fieldset className="field">
            <legend className="field-label">이 일을 하는 요일·시간 <small>정해진 때가 있으면 그때만 계획해요</small></legend>
            <div className="segmented" role="group" aria-label="정해진 요일·시간">
              <button type="button" aria-pressed={hoursChoice === 'set'} onClick={() => touchHours(() => setHoursChoice('set'))}>정해져 있어요</button>
              <button type="button" aria-pressed={hoursChoice === 'none'} onClick={() => touchHours(() => setHoursChoice('none'))}>딱히 없어요</button>
            </div>
            {hoursChoice === 'set' && <>
              <div className="segmented" role="group" aria-label="요일">
                {DAYS.split('').map((name, day) => (
                  <button type="button" key={name} aria-pressed={days.includes(day)}
                    onClick={() => touchHours(() => setDays(items => items.includes(day) ? items.filter(d => d !== day) : [...items, day].sort()))}>{name}</button>
                ))}
              </div>
              <div className="form-date-grid">
                <label className="field">
                  <span className="field-label">시작 시각</span>
                  <select value={fromHour} onChange={(event) => touchHours(() => setFromHour(Number(event.target.value)))}>
                    {HOURS.map(hour => <option value={hour} key={hour}>{hour}시</option>)}
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">끝 시각</span>
                  <select value={toHour} onChange={(event) => touchHours(() => setToHour(Number(event.target.value)))}>
                    {HOURS.map(hour => <option value={hour + 1} key={hour}>{hour + 1}시</option>)}
                  </select>
                </label>
              </div>
            </>}
            <p className={hoursValid ? 'field-hint' : 'field-hint error'}>
              {hoursChoice === 'set'
                ? (hoursValid ? `${hoursText(chosenHours)}에만 이 프로젝트를 계획해요. 이번 주 시간에 없어도 이 시간은 써요.` : '요일을 하나 이상 고르고, 끝 시각은 시작보다 늦게 해 주세요.')
                : hoursChoice === 'none' ? '이번 주 계획할 시간 안에서 다른 프로젝트와 나눠 계획해요.'
                : '고르지 않으면 대화방에서 첫 계획 전에 한 번 물어봐요.'}
            </p>
          </fieldset>
        )}

        {isProject && (
          <fieldset className="field">
            <legend className="field-label">색</legend>
            <div className="color-swatches" role="radiogroup" aria-label="프로젝트 색">
              <button type="button" role="radio" aria-checked={!color} className="color-swatch auto" style={{ background: autoProjectColor(entityId) }}
                onClick={() => setColor('')} title="자동">자동</button>
              {PROJECT_COLORS.map(value => (
                <button type="button" role="radio" key={value} aria-checked={color === value} aria-label={value} className="color-swatch"
                  style={{ background: value }} onClick={() => setColor(value)} />
              ))}
            </div>
          </fieldset>
        )}

        {isProject ? (
          <fieldset className="field">
            <legend className="field-label">중요도</legend>
            <div className="segmented" role="group" aria-label="중요도">
              {PRIORITIES.map(([value, label]) => (
                <button type="button" key={value} aria-pressed={priority === value} onClick={() => setPriority(value)}>{label}</button>
              ))}
            </div>
          </fieldset>
        ) : (
          <div className="form-date-grid">
            <label className="field">
              <span className="field-label">예상 시간</span>
              <input type="number" min="1" value={hours} onChange={(event) => setHours(Number(event.target.value))} />
            </label>
            <label className="field">
              <span className="field-label">상태</span>
              <select value={milestoneStatus} onChange={(event) => setMilestoneStatus(event.target.value as MilestoneStatus)}>
                <option value="todo">시작 전</option>
                <option value="in_progress">진행 중</option>
                <option value="done">완료</option>
                <option value="deferred">미룸</option>
              </select>
            </label>
          </div>
        )}

        {isProject && existing && <p className="field-hint">프로젝트를 끝낼 때는 프로젝트 대화에서 ‘프로젝트 끝내기’를 눌러 주세요. 배운 습관이 기본 프로필로 넘어가요.</p>}

        <footer className="entity-modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>취소</button>
          <button className="primary-button" type="submit" disabled={!canSave}>{existing ? '저장' : isProject ? '프로젝트 만들기' : '추가'}</button>
        </footer>
      </form>
    </div>
  )
}
