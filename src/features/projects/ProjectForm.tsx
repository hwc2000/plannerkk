import { useState } from 'react'
import { X } from 'lucide-react'
import { TODAY } from '../../shared/constants'
import type { Editor, Milestone, MilestoneStatus, Project, ProjectStatus } from '../../shared/types'

type ProjectFormProps = {
  editor: Exclude<Editor, null>
  projects: Project[]
  milestones: Milestone[]
  onClose: () => void
  onSave: (value: Project | Milestone) => void
}

const createId = () => crypto.randomUUID()

export function ProjectForm({ editor, projects, milestones, onClose, onSave }: ProjectFormProps) {
  const existing = editor.kind === 'project'
    ? projects.find((item) => item.id === editor.id)
    : milestones.find((item) => item.id === editor.id)
  const [title, setTitle] = useState(existing?.title ?? '')
  const [goal, setGoal] = useState(existing && 'goal' in existing ? existing.goal : '')
  const [startDate, setStartDate] = useState(existing?.startDate ?? TODAY)
  const [dueDate, setDueDate] = useState(existing?.dueDate ?? TODAY)
  const [priority, setPriority] = useState<Project['priority']>(
    existing && 'priority' in existing ? existing.priority : 'medium',
  )
  const [projectStatus, setProjectStatus] = useState<ProjectStatus>(
    existing && 'goal' in existing ? existing.status : 'active',
  )
  const [milestoneStatus, setMilestoneStatus] = useState<MilestoneStatus>(
    existing && 'estimatedHours' in existing ? existing.status : 'todo',
  )
  const [hours, setHours] = useState(existing && 'estimatedHours' in existing ? existing.estimatedHours : 2)
  const [projectId, setProjectId] = useState(
    existing && 'projectId' in existing ? existing.projectId : editor.projectId ?? projects[0]?.id ?? '',
  )
  const heading = `${existing ? '수정' : '추가'} · ${editor.kind === 'project' ? '프로젝트' : '단계별 할 일'}`

  function submit() {
    if (!title.trim()) return
    const entityId = existing?.id ?? createId()

    if (editor.kind === 'project') {
      onSave({
        id: entityId,
        title: title.trim(),
        goal: goal.trim(),
        startDate,
        dueDate,
        priority,
        status: projectStatus,
      })
    }
    if (editor.kind === 'milestone' && projectId) {
      onSave({
        id: entityId,
        projectId,
        title: title.trim(),
        startDate,
        dueDate,
        estimatedHours: hours,
        status: milestoneStatus,
      })
    }
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

        {editor.kind === 'project' && (
          <>
            <label>
              목표
              <textarea rows={3} value={goal} onChange={(event) => setGoal(event.target.value)} />
            </label>
            <div className="form-date-grid">
              <label>
                중요도
                <select value={priority} onChange={(event) => setPriority(event.target.value as Project['priority'])}>
                  <option value="high">높음</option>
                  <option value="medium">보통</option>
                  <option value="low">낮음</option>
                </select>
              </label>
              <label>
                상태
                <select value={projectStatus} onChange={(event) => setProjectStatus(event.target.value as ProjectStatus)}>
                  <option value="active">진행 중</option>
                  <option value="paused">중지</option>
                  <option value="completed">완료</option>
                </select>
              </label>
            </div>
          </>
        )}

        {editor.kind === 'milestone' && (
          <label>
            연결 프로젝트
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)} required>
              <option value="">연결 안 함</option>
              {projects.map((project) => (
                <option value={project.id} key={project.id}>{project.title}</option>
              ))}
            </select>
          </label>
        )}

        <div className="form-date-grid">
          <label>
            시작일
            <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required />
          </label>
          <label>
            마감일
            <input type="date" min={startDate} value={dueDate} onChange={(event) => setDueDate(event.target.value)} required />
          </label>
        </div>

        {editor.kind === 'milestone' && (
          <div className="form-date-grid">
            <label>
              예상 시간
              <input type="number" min="1" value={hours} onChange={(event) => setHours(Number(event.target.value))} />
            </label>
            <label>
              상태
              <select
                value={milestoneStatus}
                onChange={(event) => setMilestoneStatus(event.target.value as MilestoneStatus)}
              >
                <option value="todo">시작 전</option>
                <option value="in_progress">진행 중</option>
                <option value="done">완료</option>
                <option value="deferred">미룸</option>
              </select>
            </label>
          </div>
        )}

        <button className="primary-button full" type="submit">저장</button>
      </form>
    </div>
  )
}
