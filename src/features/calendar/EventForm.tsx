import { useState } from 'react'
import { X } from 'lucide-react'
import { TODAY } from '../../shared/constants'
import type { CalendarEvent, Editor, Project } from '../../shared/types'

type EventFormProps = {
  editor: Exclude<Editor, null>
  projects: Project[]
  events: CalendarEvent[]
  onClose: () => void
  onSave: (value: CalendarEvent) => void
}

const createId = () => crypto.randomUUID()

export function EventForm({ editor, projects, events, onClose, onSave }: EventFormProps) {
  const existing = events.find((item) => item.id === editor.id)
  const [title, setTitle] = useState(existing?.title ?? '')
  const [date, setDate] = useState(existing?.date ?? editor.date ?? TODAY)
  const [projectId, setProjectId] = useState(existing?.projectId ?? editor.projectId ?? projects[0]?.id ?? '')
  const [startTime, setStartTime] = useState(existing?.startTime ?? '18:00')
  const [endTime, setEndTime] = useState(existing?.endTime ?? '19:00')
  const [isFixed, setIsFixed] = useState(existing?.isFixed ?? false)
  const [error, setError] = useState('')
  const heading = `${existing ? '수정' : '추가'} · 일정`

  function submit() {
    if (!title.trim()) return
    if (!startTime || !endTime || endTime <= startTime) {
      setError(!startTime || !endTime ? '시작 시간과 종료 시간을 모두 입력해 주세요.' : '종료 시간은 시작 시간보다 늦어야 합니다.')
      return
    }

    onSave({
      id: existing?.id ?? createId(),
      title: title.trim(),
      date,
      startTime,
      endTime,
      projectId: projectId || undefined,
      isFixed,
    })
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form
        className="data-modal"
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <button className="close-button" type="button" onClick={onClose} aria-label="닫기"><X size={18} /></button>
        <p className="section-kicker">LOCAL CRUD</p>
        <h2>{heading}</h2>
        <label>
          제목
          <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} required />
        </label>
        <label>
          연결 프로젝트
          <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
            <option value="">연결 안 함</option>
            {projects.map((project) => (
              <option value={project.id} key={project.id}>{project.title}</option>
            ))}
          </select>
        </label>
        <div className="form-date-grid">
          <label>
            날짜
            <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
          </label>
        </div>
        <div className="form-date-grid">
          <label>
            시작 시간
            <input
              type="time"
              required
              value={startTime}
              onChange={(event) => {
                setStartTime(event.target.value)
                setError('')
              }}
            />
          </label>
          <label>
            종료 시간
            <input
              type="time"
              required
              value={endTime}
              onChange={(event) => {
                setEndTime(event.target.value)
                setError('')
              }}
            />
          </label>
        </div>
        <label className="checkbox-label">
          <input type="checkbox" checked={isFixed} onChange={(event) => setIsFixed(event.target.checked)} />
          고정 일정
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button full" type="submit">저장</button>
      </form>
    </div>
  )
}
