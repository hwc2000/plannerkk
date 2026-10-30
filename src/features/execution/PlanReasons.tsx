import { Sparkles } from 'lucide-react'
import type { PlanReason } from '../../shared/types'
import { answerLabels } from './profileLabels'

const sourceLabels: Record<PlanReason['source'], string> = {
  declared: '설문 답변', learned: '실행 기록으로 학습', default: '아직 모르는 값의 시작값', profile: '확정한 프로필', memory: '저장한 기억',
  project: '이 프로젝트 설정',
}

const sourceTones: Record<PlanReason['source'], string> = {
  declared: 'info', learned: 'ok', default: 'neutral', profile: 'neutral', memory: 'warn', project: 'project',
}

export function PlanReasons({ reasons, open }: { reasons: PlanReason[]; open: boolean }) {
  if (!reasons.length) return null
  return <details className="plan-reasons" open={open}>
    <summary><span className="plan-reasons-icon" aria-hidden="true"><Sparkles size={14}/></span><span>이 계획에 반영한 나의 특성 {reasons.length}가지</span></summary>
    <ul>
      {reasons.map(r => {
        const fields = r.source === 'declared' || r.source === 'default' ? r.fields.map(f => answerLabels[f] ?? f).join(', ') : ''
        return <li key={r.key}>
          <div><strong>{r.applied}</strong><small>{r.because}</small></div>
          <span className={`badge reason-source ${sourceTones[r.source]}`}>{sourceLabels[r.source]}{fields && ` · ${fields}`}</span>
        </li>
      })}
    </ul>
  </details>
}
