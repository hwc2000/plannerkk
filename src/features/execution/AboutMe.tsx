import { useEffect, useState } from 'react'
import type { InsightPattern, InsightSlot } from '../../shared/types'
import { fetchInsights } from './api'

/** What check-ins taught the planner about the user, field by field; empty ones are asked in a check-in. */
export function AboutMe({ revision }: { revision: number }) {
  const [slots, setSlots] = useState<InsightSlot[] | null>(null)
  const [patterns, setPatterns] = useState<InsightPattern[]>([])
  useEffect(() => {
    let active = true
    fetchInsights().then(data => { if (active) { setSlots(data.slots); setPatterns(data.candidatePatterns ?? []) } }).catch(() => { if (active) setSlots(null) })
    return () => { active = false }
  }, [revision])
  if (!slots) return null
  const known = slots.filter(s => s.value).length
  return <section className="execution-card" aria-label="나에 대해 알게 된 것">
    <p className="section-kicker">ABOUT ME · 기록된 항목 {known}개</p><h2>나에 대해 알게 된 것</h2>
    <p className="execution-help">직접 말한 선호와 실행에서 관찰한 내용은 달라요. 관찰·후보 패턴은 아직 가설이며, 항목이 채워져도 나를 모두 이해했다는 뜻은 아니에요. 추가 질문은 선택이고 건너뛰어도 괜찮아요.</p>
    <ul className="about-me">{slots.map(s => <li key={s.key} className={s.value ? '' : 'empty'}>
      <strong>{s.label}</strong>
      <small>{s.kind === 'declared' || s.source === 'declared' || s.source === 'user' ? (s.status === 'confirmed' ? '확인한 직접 진술·선호' : '직접 말한 선호') : s.status === 'candidate' || s.status === 'pending' ? '후보 패턴 · 확인 전' : s.source === 'learned' || s.source === 'observed' ? '실행 기록에서 관찰한 패턴' : '대화에서 정리한 내용 · 관찰·선호 후보'}</small>
      <span>{s.value ? ((s.history?.length ?? 0) > 1 ? s.history.join(', ') : s.value) : '아직 기록 없음 · 답변은 선택이에요'}</span>
      {s.evidence && <small>{s.kind === 'declared' ? '직접 진술 근거' : '기록 근거'}: {s.evidence.confirmations ?? 0}회 · {s.evidence.distinctDays ?? 0}일{s.evidence.windowDays ? ` · 최근 ${s.evidence.windowDays}일` : ''}. 실행 성공을 뜻하지 않아요.</small>}
    </li>)}</ul>
    {patterns.length > 0 && <div aria-label="관찰 후보의 근거"><h3>실행에서 관찰한 후보 패턴</h3><ul>{patterns.map(p => <li key={`${p.field}-${p.value}`}>
      <strong>{p.value}</strong> · {p.status === 'supported' ? '최근 관찰 근거 있음 · 가설' : p.status === 'mixed' ? '관찰 결과가 엇갈림' : '근거 부족'}
      <small> · 체크인 {p.samples}회 · {p.distinctDays}일{p.windowDays ? ` · 최근 ${p.windowDays}일` : ''}{p.unknownFocus != null ? ` · 집중 미응답 ${p.unknownFocus}회` : ''}</small>
    </li>)}</ul><p className="execution-help">연관성이지 원인은 아니에요. 다른 프로젝트에 자동 적용하거나 기본 프로필을 바꾸지 않아요.</p></div>}
  </section>
}
