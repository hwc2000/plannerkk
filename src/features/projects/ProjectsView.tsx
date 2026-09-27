import { Pencil, Plus, Trash2 } from 'lucide-react'
import { milestoneLabel, priorityLabel, statusLabel } from '../../shared/constants'
import { projectColor } from '../../shared/projectColors'
import { ProjectLegend } from '../../shared/ProjectLegend'
import type { Milestone, Project } from '../../shared/types'

type ProjectsViewProps = {
  projects: Project[]
  milestones: Milestone[]
  selectedProject?: Project
  setSelectedProjectId: (id: string) => void
  onCreateProject: () => void
  onEditProject: (id: string) => void
  onDeleteProject: (id: string) => void
  onCreateMilestone: (id: string) => void
  onEditMilestone: (id: string) => void
  onDeleteMilestone: (id: string) => void
}

export function ProjectsView({
  projects,
  milestones,
  selectedProject,
  setSelectedProjectId,
  onCreateProject,
  onEditProject,
  onDeleteProject,
  onCreateMilestone,
  onEditMilestone,
  onDeleteMilestone,
}: ProjectsViewProps) {
  return (
    <section className="portfolio-workspace">
      <div className="portfolio-intro">
        <div>
          <p className="eyebrow">PROJECTS</p>
          <h1>프로젝트와 단계별 할 일을 <em>관리</em>.</h1>
          <p>달성률·위험도 계산 없이 프로젝트 원본 데이터만 관리합니다.</p>
        </div>
        <button className="primary-button compact" onClick={onCreateProject}>
          <Plus size={16} />새 프로젝트
        </button>
      </div>
      <ProjectLegend projects={projects} />
      <div className="portfolio-layout">
        <div className="project-list-panel">
          <div className="project-card-list">
            {projects.map((project) => (
              <button
                className={`project-progress-card ${selectedProject?.id === project.id ? 'selected' : ''}`}
                key={project.id}
                onClick={() => setSelectedProjectId(project.id)}
              >
                <div className="project-name-row">
                  <h3>
                    <span className="project-color-dot" style={{ backgroundColor: projectColor(project.id) }} />
                    {project.title}
                  </h3>
                  <span className="status-chip planned">{statusLabel[project.status]}</span>
                </div>
                <p className="project-insight">{project.startDate} ~ {project.dueDate}</p>
              </button>
            ))}
            {!projects.length && <div className="empty-state">프로젝트를 추가해 주세요.</div>}
          </div>
        </div>

        {selectedProject && (
          <aside className="project-detail-panel">
            <div className="detail-heading">
              <div>
                <span className="status-chip planned">중요도 {priorityLabel[selectedProject.priority]}</span>
                <h2>{selectedProject.title}</h2>
              </div>
              <span className="row-actions">
                <button onClick={() => onEditProject(selectedProject.id)} aria-label="프로젝트 수정">
                  <Pencil size={16} />
                </button>
                <button onClick={() => onDeleteProject(selectedProject.id)} aria-label="프로젝트 삭제">
                  <Trash2 size={16} />
                </button>
              </span>
            </div>
            <p className="detail-date">{selectedProject.startDate} ~ {selectedProject.dueDate}</p>
            <p className="detail-goal">{selectedProject.goal || '등록된 목표가 없습니다.'}</p>
            <div className="milestone-list">
              <div className="list-heading">
                <h3>단계별 할 일</h3>
                <button className="text-button" onClick={() => onCreateMilestone(selectedProject.id)}>
                  <Plus size={14} />추가
                </button>
              </div>
              {milestones.filter((item) => item.projectId === selectedProject.id).map((item) => (
                <div className="milestone-row" key={item.id}>
                  <span className={`milestone-status ${item.status}`} />
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.startDate} ~ {item.dueDate} · {item.estimatedHours}시간 · {milestoneLabel[item.status]}</small>
                  </span>
                  <span className="row-actions">
                    <button onClick={() => onEditMilestone(item.id)} aria-label="할 일 수정"><Pencil size={14} /></button>
                    <button onClick={() => onDeleteMilestone(item.id)} aria-label="할 일 삭제"><Trash2 size={14} /></button>
                  </span>
                </div>
              ))}
              {!milestones.some((item) => item.projectId === selectedProject.id) && (
                <div className="empty-state">단계별 할 일이 없습니다.</div>
              )}
            </div>
            <button className="primary-button full" onClick={() => onCreateMilestone(selectedProject.id)}>
              <Plus size={16} />단계별 할 일 추가
            </button>
          </aside>
        )}
      </div>
    </section>
  )
}
