import { useState } from 'react'
import type { ExecutionState, Project } from '../../shared/types'
import { executionApi } from './api'
import { options } from './profileLabels'

type Key = 'blockMinutes' | 'dailyPlannedMinutes' | 'bufferPercent' | 'starterMinutes' | 'recoveryPreference'
type Field = { key: Key; label: string; unit?: string; min?: number; max?: number }
type Values = Partial<Record<Key, number | string>>

// The keys the server lets a project override; everything else always follows the user profile.
const FIELDS: Field[] = [
  { key: 'blockMinutes', label: '한 번에 집중할 시간', unit: '분', min: 1, max: 180 },
  { key: 'dailyPlannedMinutes', label: '하루 계획량', unit: '분', min: 1, max: 720 },
  { key: 'bufferPercent', label: '비워 둘 여유분', unit: '%', min: 0, max: 90 },
  { key: 'starterMinutes', label: '첫 작업 앞 시작 행동', unit: '분', min: 1, max: 180 },
  { key: 'recoveryPreference', label: '계획이 틀어졌을 때' },
]

function show(field: Field, value: unknown) {
  if (value === null || value === undefined) return '없음'
  if (field.key === 'recoveryPreference') return options.recovery.find(([code]) => code === value)?.[1] ?? String(value)
  return `${String(value)}${field.unit}`
}

/** Values that differ for one project. Left empty, a value follows the user profile (or what this project learned). */
export function ProjectSettings({ state, project, busy, run }: {
  state: ExecutionState; project: Project; busy: boolean
  run: (action: () => Promise<ExecutionState>, message: string) => Promise<boolean>
}) {
  const base = state.profile!.planningPreferences as unknown as Record<Key, unknown>
  const overrides = state.projectProfiles?.[project.id]?.overrides ?? {}
  const [inputs, setInputs] = useState<Record<Key, string>>(() => Object.fromEntries(FIELDS.map(f => {
    const override = overrides[f.key]
    return [f.key, override?.source === 'declared' && override.value !== null ? String(override.value) : '']
  })) as Record<Key, string>)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  const learned = (key: Key) => overrides[key]?.source === 'learned'
  // What an empty input means: keep the value learned in this project, else follow the user profile.
  const fallback = (key: Key) => learned(key) ? overrides[key].value : base[key]
  const chosen: Values = Object.fromEntries(FIELDS.filter(f => inputs[f.key] !== '').map(f => [
    f.key, f.key === 'recoveryPreference' ? inputs[f.key] : Number(inputs[f.key]),
  ]))
  const summary = FIELDS.filter(f => f.key in overrides).map(f =>
    `${f.label} ${show(f, overrides[f.key].value)}${learned(f.key) ? '(기록으로 학습)' : ''}`)

  function save(next: Values) {
    // The server checks the same rules; checking here keeps the message next to the inputs.
    const outOfRange = FIELDS.find(f => f.min !== undefined && f.key in next
      && !(Number.isInteger(next[f.key]) && (next[f.key] as number) >= f.min && (next[f.key] as number) <= f.max!))
    if (outOfRange) return setError(`${outOfRange.label}은 ${outOfRange.min}~${outOfRange.max} 사이의 정수로 입력해 주세요.`)
    const after = (key: Key) => (key in next ? next[key] : fallback(key)) as number | null
    const block = after('blockMinutes') as number, daily = after('dailyPlannedMinutes'), starter = after('starterMinutes')
    if (daily !== null && block > daily) return setError('한 번에 집중할 시간은 하루 계획량보다 길 수 없습니다.')
    if (starter !== null && starter > block) return setError('시작 행동은 한 번에 집중할 시간보다 길 수 없습니다.')
    setError(''); setSaved('')
    const message = state.plan?.projectId === project.id
      ? `${project.title} 설정을 저장했습니다. 지금 계획은 이전 설정으로 만들었으니 다시 생성하면 반영됩니다.`
      : `${project.title} 설정을 저장했습니다. 이 프로젝트의 다음 계획부터 반영됩니다.`
    void run(() => executionApi(`/projects/${encodeURIComponent(project.id)}/profile`, { revision: state.revision, overrides: next }, 'PUT'), message)
      .then(ok => {
        if (!ok) return
        // The page notice is at the top; repeat it here where the user is looking.
        setSaved(message)
        if (!Object.keys(next).length) setInputs(Object.fromEntries(FIELDS.map(f => [f.key, ''])) as Record<Key, string>)
      })
  }

  // Enter in these inputs must not submit the surrounding weekly-plan form.
  return <details className="execution-project-settings" onKeyDown={e => { if (e.key === 'Enter' && e.target instanceof HTMLInputElement) e.preventDefault() }}>
    <summary>이 프로젝트만 다르게 하기 · {summary.length ? summary.join(', ') : '기본 프로필을 따름'}</summary>
    <p className="execution-help">비워 두면 기본 프로필 값을 따릅니다. 이 프로젝트의 실행 기록으로 배운 값도 여기서 바꿀 수 있어요. 다른 프로젝트에는 영향이 없습니다.</p>
    {FIELDS.map(f => {
      const override = overrides[f.key]
      const status = learned(f.key)
        ? `이 프로젝트 기록으로 학습한 값: ${show(f, override.value)} · 값을 정하면 직접 정한 값으로 바뀝니다`
        : override?.source === 'declared' ? `이 프로젝트에서 정함 · 기본 프로필은 ${show(f, base[f.key])}`
          : `기본 프로필 값(${show(f, base[f.key])})을 따름`
      const empty = learned(f.key) ? `학습한 값 유지 · ${show(f, fallback(f.key))}` : `기본 프로필 따르기 · ${show(f, base[f.key])}`
      return <label key={f.key} className="execution-label">{f.label}
        {f.key === 'recoveryPreference'
          ? <select value={inputs[f.key]} onChange={e => setInputs(v => ({ ...v, [f.key]: e.target.value }))}>
              <option value="">{empty}</option>
              {options.recovery.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
            </select>
          : <input type="number" min={f.min} max={f.max} step={1} value={inputs[f.key]} placeholder={`비우면 ${show(f, fallback(f.key))}`}
              onChange={e => setInputs(v => ({ ...v, [f.key]: e.target.value }))}/>}
        <small className="execution-help">{status}</small>
      </label>
    })}
    {error && <p className="form-error" role="alert">{error}</p>}
    {saved && <p className="execution-notice" role="status">{saved}</p>}
    <div className="execution-actions">
      <button type="button" className="secondary-button" disabled={busy} onClick={() => save(chosen)}>이 프로젝트 설정 저장</button>
      {Object.values(overrides).some(o => o.source === 'declared') && <button type="button" className="secondary-button" disabled={busy}
        onClick={() => save({})}>직접 정한 값 모두 지우기</button>}
    </div>
  </details>
}
