import type { PlanReason } from '../../shared/types'
import { answerLabels } from './profileLabels'

const sourceLabels: Record<PlanReason['source'], string> = {
  declared: '설문 답변', learned: '실행 기록으로 학습', default: '아직 모르는 값의 시작값', profile: '확정한 프로필', memory: '저장한 기억',
}

export function PlanReasons({ reasons, open }: { reasons: PlanReason[]; open: boolean }) {
  if (!reasons.length) return null
  return <details className="execution-reasons" open={open}><summary>이 계획에 반영한 나의 특성 {reasons.length}가지</summary><ul>
    {reasons.map(r => {
      const fields = r.source === 'declared' || r.source === 'default' ? r.fields.map(f => answerLabels[f] ?? f).join(', ') : ''
      return <li key={r.key}><strong>{r.applied}</strong><small>{r.because}</small><span>{sourceLabels[r.source]}{fields && ` · ${fields}`}</span></li>
    })}
  </ul></details>
}
