import { useEffect, useState } from 'react'
import type { ClosedProject, ClosePreview, Project } from '../../shared/types'
import { closePreview } from './api'

type Outcome = ClosedProject['outcome']

/** Ending a project: what carries to the user profile and what stays, shown before the user decides. */
export function CloseProject({ project, busy, onClose, onCancel }: {
  project: Project; busy: boolean
  onClose: (outcome: Outcome) => Promise<boolean>
  onCancel: () => void
}) {
  const [preview, setPreview] = useState<ClosePreview | null>(null)
  const [error, setError] = useState('')
  const [outcome, setOutcome] = useState<Outcome>('completed')
  useEffect(() => {
    let live = true
    closePreview(project.id).then(p => { if (live) setPreview(p) }, e => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    return () => { live = false }
  }, [project.id])

  return <div className="planner-action" aria-label="프로젝트 끝내기">
    <h3>‘{project.title}’ 프로젝트를 끝낼까요?</h3>
    {error && <p className="form-error" role="alert">{error}</p>}
    {!preview && !error && <p role="status">이 프로젝트에서 배운 것을 확인하고 있어요…</p>}
    {preview && <>
      <div className="execution-options" role="radiogroup" aria-label="어떻게 끝났나요">
        <label className="execution-option"><input type="radio" name="outcome" checked={outcome === 'completed'} onChange={() => setOutcome('completed')}/>다 했어요</label>
        <label className="execution-option"><input type="radio" name="outcome" checked={outcome === 'abandoned'} onChange={() => setOutcome('abandoned')}/>여기서 그만둘게요</label>
      </div>
      <p><strong>기본 프로필로 넘길 습관</strong></p>
      {preview.carried.length > 0
        ? <ul>{preview.carried.map(c => <li key={c.key}>{c.label}: {c.from} → {c.to}<br/><small>{c.because}</small></li>)}</ul>
        : <p className="execution-help">이 프로젝트 기록으로 확인된 습관이 아직 없어서 기본 프로필은 그대로예요.</p>}
      {preview.kept.length > 0 && <details><summary>이 프로젝트에만 남는 것 {preview.kept.length}개</summary>
        <ul>{preview.kept.map(k => <li key={k.label}>{k.label} {k.value}<br/><small>{k.why}</small></li>)}</ul></details>}
      {preview.openTasks > 0 && <p className="execution-help">이번 주에 남은 이 프로젝트 작업 {preview.openTasks}개는 계획에서 빠져요. 끝낸 작업과 실행 기록은 그대로 남아요.</p>}
      <p className="execution-help">끝낸 프로젝트는 대화와 계획이 멈춰요. 필요하면 다시 열 수 있고, 기본 프로필에 넘긴 값은 그대로 둬요.</p>
      <div className="execution-actions">
        <button className="primary-button" disabled={busy} onClick={() => { void onClose(outcome) }}>
          {preview.carried.length ? '끝내고 기본 프로필에 반영' : '프로젝트 끝내기'}</button>
        <button className="secondary-button" disabled={busy} onClick={onCancel}>취소</button>
      </div>
    </>}
  </div>
}

/** An ended project's conversation: what it carried, and a way to open it again. */
export function ClosedNotice({ info, busy, onReopen }: { info: ClosedProject; busy: boolean; onReopen?: () => void }) {
  return <div className="planner-action" aria-label="끝낸 프로젝트">
    <h3>{info.outcome === 'completed' ? '다 한 프로젝트예요' : '그만둔 프로젝트예요'} · {info.closedAt.slice(0, 10)}</h3>
    {info.carried.length > 0
      ? <p>기본 프로필로 넘긴 습관: {info.carried.map(c => `${c.label} ${c.from} → ${c.to}`).join(', ')}</p>
      : <p className="execution-help">기본 프로필로 넘긴 값은 없어요.</p>}
    <p className="execution-help">대화와 계획이 멈춰 있어요. 다시 열면 이어서 계획할 수 있어요.</p>
    {onReopen && <button className="secondary-button" disabled={busy} onClick={onReopen}>다시 열기</button>}
  </div>
}
