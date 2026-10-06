import { LoaderCircle, Sparkles } from 'lucide-react'
import { useRef, useState } from 'react'
import type { Milestone, Project, Memory } from '../../shared/types'
import { requestPlanDraft, type AiPlanDraft } from './aiPlan'

type AiPlanningViewProps = {
  memories?: Memory[]
  projects: Project[]
  milestones: Milestone[]
  selectedProjectId: string
  onSelectProject: (projectId: string) => void
  onApply: (projectId: string, draft: AiPlanDraft) => void
  requestDraft?: typeof requestPlanDraft
}

export function AiPlanningView({
  projects,
  memories = [],
  milestones,
  selectedProjectId,
  onSelectProject,
  onApply,
  requestDraft = requestPlanDraft,
}: AiPlanningViewProps) {
  const [instruction, setInstruction] = useState('')
  const [draft, setDraft] = useState<AiPlanDraft | null>(null)
  const [draftProjectId, setDraftProjectId] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? projects[0]
  const currentContext = useRef({ projects, selectedProjectId })
  currentContext.current = { projects, selectedProjectId }

  async function createDraft() {
    const goal = instruction.trim()
    if (!goal) {
      setError('요청 내용을 입력해주세요.')
      return
    }
    if (!selectedProject) {
      setError('먼저 프로젝트를 만들어주세요.')
      return
    }

    setError('')
    setDraft(null)
    setDraftProjectId('')
    setIsLoading(true)
    const requestProjectId = selectedProject.id
    const requestStartDate = selectedProject.startDate
    const requestDueDate = selectedProject.dueDate
    try {
      const nextDraft = await requestDraft({
        goal,
        memories,
        project: selectedProject,
        existingTasks: milestones
          .filter((item) => item.projectId === selectedProject.id)
          .map(({ title, startDate, dueDate, estimatedHours, status }) => ({
            title,
            startDate,
            dueDate,
            estimatedHours,
            status,
          })),
      })
      const latestProject = currentContext.current.projects.find(
        (project) => project.id === requestProjectId,
      )
      if (currentContext.current.selectedProjectId !== requestProjectId
        || !latestProject
        || latestProject.startDate !== requestStartDate
        || latestProject.dueDate !== requestDueDate) {
        setError('프로젝트가 변경되었습니다. 계획 초안을 다시 요청해주세요.')
        setDraft(null)
        setDraftProjectId('')
        return
      }
      setDraft(nextDraft)
      setDraftProjectId(requestProjectId)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AI 계획을 만들지 못했습니다.')
    } finally {
      setIsLoading(false)
    }
  }

  function applyDraft() {
    if (!draft || !draftProjectId) return
    onApply(draftProjectId, draft)
    setDraft(null)
    setDraftProjectId('')
    setInstruction('')
  }

  return (
    <section className="ai-planning-workspace">
      <header className="ai-planning-intro">
        <div>
          <p className="eyebrow">AI PLAN DRAFT</p>
          <h1>계획을 먼저 <em>초안</em>으로 검토하세요.</h1>
          <p>AI가 프로젝트 맥락과 기존 할 일을 참고해 단계를 제안합니다. 검토 후 반영하기 전까지는 저장되지 않습니다.</p>
        </div>
        <span className="ai-draft-badge"><Sparkles size={15} /> gpt-4o-mini</span>
      </header>

      <div className="ai-planning-grid">
        <form className="ai-request-card" onSubmit={(event) => { event.preventDefault(); void createDraft() }}>
          <div className="list-heading">
            <div>
              <p className="section-kicker">REQUEST</p>
              <h2>어떤 계획이 필요한가요?</h2>
            </div>
          </div>

          <label>
            프로젝트
            <select
              value={selectedProject?.id ?? ''}
              onChange={(event) => { onSelectProject(event.target.value); setDraft(null); setDraftProjectId('') }}
              disabled={isLoading || projects.length === 0}
            >
              {projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}
            </select>
          </label>

          <label>
            AI에게 요청할 내용
            <textarea
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              placeholder="예: 이 프로젝트를 이번 주부터 시작할 수 있게 단계별로 나눠줘"
              rows={6}
              maxLength={2000}
            />
          </label>

          {selectedProject && (
            <div className="ai-context-note">
              <strong>{selectedProject.title}</strong>
              <span>{selectedProject.startDate} → {selectedProject.dueDate}</span>
              <small>기존 단계별 할 일 {milestones.filter((item) => item.projectId === selectedProject.id).length}개를 함께 참고합니다.</small>
            </div>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button full" type="submit" disabled={isLoading || !selectedProject}>
            {isLoading ? <><LoaderCircle className="spin" size={16} /> 초안 만드는 중</> : <><Sparkles size={16} /> 계획 초안 만들기</>}
          </button>
        </form>

        <section className="ai-draft-card" aria-live="polite">
          <div className="list-heading">
            <div>
              <p className="section-kicker">REVIEW</p>
              <h2>AI 제안 초안</h2>
            </div>
            {draft && <span className="draft-count">{draft.tasks.length}개 단계</span>}
          </div>

          {!draft && !isLoading && (
            <div className="ai-empty-state">
              <Sparkles size={25} />
              <strong>아직 생성한 초안이 없습니다.</strong>
              <p>왼쪽에서 요청하면 이곳에 검토 가능한 할 일 목록이 나타납니다.</p>
            </div>
          )}
          {isLoading && (
            <div className="ai-empty-state">
              <LoaderCircle className="spin" size={25} />
              <strong>프로젝트 맥락을 읽고 있습니다.</strong>
              <p>기존 할 일과 겹치지 않도록 초안을 구성하는 중입니다.</p>
            </div>
          )}
          {draft && (
            <>
              <p className="ai-draft-summary">{draft.summary}</p>
              <ol className="ai-draft-list">
                {draft.tasks.map((task, index) => (
                  <li key={`${task.title}-${task.startDate}-${index}`}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{task.title}</strong>
                      <small>{task.startDate} → {task.dueDate} · {task.estimatedHours}시간</small>
                    </div>
                  </li>
                ))}
              </ol>
              <div className="ai-review-actions">
                <button className="secondary-button" type="button" onClick={() => { setDraft(null); setDraftProjectId('') }}>초안 버리기</button>
                <button className="primary-button" type="button" onClick={applyDraft}>검토 후 단계별 할 일에 반영</button>
              </div>
              <p className="ai-review-note">반영을 누르면 위 항목만 프로젝트의 단계별 할 일로 저장됩니다.</p>
            </>
          )}
        </section>
      </div>
    </section>
  )
}
