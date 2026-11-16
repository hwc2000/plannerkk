import { useEffect, useState } from 'react'
import type { AttentionItem, ClosedProject, ExecutionState, Project } from '../../shared/types'
import { useStoredState } from '../../shared/storage'
import { dateKey } from '../../shared/constants'
import { CloseProject } from './CloseProject'
import { executionApi, fetchAttention } from './api'

type Run = (action: () => Promise<ExecutionState>, message: string | ((next: ExecutionState) => string)) => Promise<boolean>
type LateResult = 'completed' | 'partial' | 'not_started' | 'incomplete'

const LATE_RESULTS: ReadonlyArray<readonly [LateResult, string]> = [
  ['completed', '끝냈어요'], ['partial', '조금 했어요'], ['not_started', '못 했어요'], ['incomplete', '기억 안 나요'],
]
const SNOOZE_DAYS = 7

function addDays(day: string, days: number) {
  const next = new Date(`${day}T00:00:00`)
  next.setDate(next.getDate() + days)
  return dateKey(next)
}

/**
 * The home screen asks about projects people left: past the deadline, or several planned tasks
 * in a row without a check-in.  Nothing changes until the user picks: record what happened,
 * plan again, take a break from the project, or end it.
 */
export function ProjectAttention({ state, projects, busy, run, onOpenProject, onEditProject, onPause, onCloseProject }: {
  state: ExecutionState; projects: Project[]; busy: boolean; run: Run
  onOpenProject?: (projectId: string) => void
  onEditProject?: (projectId: string) => void
  onPause?: (projectId: string) => void
  onCloseProject: (project: Project, outcome: ClosedProject['outcome']) => Promise<boolean>
}) {
  const [items, setItems] = useState<AttentionItem[]>([])
  const [snoozed, setSnoozed] = useStoredState<Record<string, string>>('replan:attention-snoozed', {})
  const [open, setOpen] = useState<{ projectId: string; what: 'late' | 'close' } | null>(null)
  const [results, setResults] = useState<Record<string, LateResult>>({})
  const today = dateKey(new Date())
  const asked = projects.filter(p => p.status !== 'paused' && !state.closedProjects?.[p.id])
  const askedKey = asked.map(p => `${p.id}:${p.dueDate}`).join(',')

  useEffect(() => {
    let live = true
    fetchAttention(projects, state.closedProjects).then(next => { if (live) setItems(next) }, () => { if (live) setItems([]) })
    return () => { live = false }
    // The answer changes with saved records (revision) and with which projects are asked about.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.revision, askedKey])

  const shown = items.filter(item => !(snoozed[item.projectId] && snoozed[item.projectId] > today))
  if (!shown.length) return null

  async function saveLate(item: AttentionItem) {
    const plan = state.plan
    if (!plan) return
    const ok = await run(() => executionApi('/records/late', {
      revision: state.revision, planId: plan.id,
      items: item.tasks.map(t => ({ taskId: t.taskId, result: results[t.taskId] ?? 'incomplete' })),
    }), `‘${item.title}’ 지난 작업을 기록했어요. 끝낸 일은 다시 계획하지 않고, 나머지는 남은 일로 둘게요.`)
    if (ok) { setOpen(null); setResults({}) }
  }

  return <section className="execution-card home-attention" aria-label="확인할 프로젝트">
    <h2>이 프로젝트들은 어떻게 되고 있나요?</h2>
    {shown.map(item => {
      const project = projects.find(p => p.id === item.projectId)
      const isOpen = open?.projectId === item.projectId
      return <div key={item.projectId} className="attention-item">
        <p className="attention-title"><b>{item.title}</b> · {item.kind === 'overdue'
          ? `마감일(${item.dueDate})이 지났어요.`
          : `최근 계획한 작업 ${item.silentInRow}개에 기록이 없어요.`}</p>
        <p className="execution-help">{item.kind === 'overdue'
          ? '어떻게 됐는지 남기고, 마무리하거나 기간을 늘려 주세요.'
          : '바빴다면 다시 계획하거나 잠시 쉬어 가도 괜찮아요.'}</p>
        <div className="execution-actions">
          {item.tasks.length > 0 && <button type="button" className="primary-button" disabled={busy}
            onClick={() => setOpen(isOpen && open?.what === 'late' ? null : { projectId: item.projectId, what: 'late' })}>
            밀린 기록 남기기 · {item.tasks.length}개</button>}
          {item.kind === 'idle' && <button type="button" className="secondary-button" disabled={busy} onClick={() => onOpenProject?.(item.projectId)}>다시 계획하기</button>}
          {item.kind === 'idle' && onPause && <button type="button" className="secondary-button" disabled={busy} onClick={() => onPause(item.projectId)}>잠시 쉬기</button>}
          {item.kind === 'overdue' && onEditProject && <button type="button" className="secondary-button" disabled={busy} onClick={() => onEditProject(item.projectId)}>기간 늘리기</button>}
          {project && <button type="button" className="secondary-button" disabled={busy} onClick={() => setOpen({ projectId: item.projectId, what: 'close' })}>프로젝트 끝내기</button>}
          <button type="button" className="secondary-button" disabled={busy}
            onClick={() => setSnoozed({ ...snoozed, [item.projectId]: addDays(today, SNOOZE_DAYS) })}>나중에</button>
        </div>
        {isOpen && open?.what === 'late' && <div className="attention-late">
          <ul className="checkin-tasks">{item.tasks.map(t => <li key={t.taskId}>
            <span><b>{t.title}</b><small>{t.start.slice(5, 10).replace('-', '/')} {t.start.slice(11)} · {t.minutes}분</small></span>
            <span className="checkin-choices">{LATE_RESULTS.map(([value, label]) => <button type="button" key={value}
              aria-pressed={(results[t.taskId] ?? 'incomplete') === value} className={(results[t.taskId] ?? 'incomplete') === value ? 'chosen' : ''}
              disabled={busy} onClick={() => setResults({ ...results, [t.taskId]: value })}>{label}</button>)}</span>
          </li>)}</ul>
          <p className="execution-help">몇 분 했는지는 묻지 않아요. 나중에 남긴 기록은 다음 계획에서 끝낸 일과 남은 일을 가리는 데만 쓰고, 성향 학습에는 쓰지 않아요.</p>
          <button type="button" className="primary-button" disabled={busy} onClick={() => { void saveLate(item) }}>기록 저장</button>
        </div>}
        {isOpen && open?.what === 'close' && project && <CloseProject project={project} busy={busy}
          onClose={async outcome => { const ok = await onCloseProject(project, outcome); if (ok) setOpen(null); return ok }}
          onCancel={() => setOpen(null)}/>}
      </div>
    })}
  </section>
}
