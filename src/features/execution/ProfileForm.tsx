import { useState } from 'react'
import type { ExecutionAnswers } from '../../shared/types'

export const answerLabels: Record<string, string> = { roles: '생활 형태', regularity: '생활 규칙성', barriers: '계획이 무너지는 이유', focusMinutes: '한 번의 집중 시간', dailyMinutes: '하루 여유 시간', energy: '집중이 잘되는 시간', recovery: '계획이 틀어졌을 때', constraints: '고정 일정', context: '추가 설명' }
const options: Record<string, Array<[string,string]>> = {
  roles: [['student','학생'],['employee','직장인'],['job_seeker','취업 준비생'],['freelancer','프리랜서'],['other','그 외']],
  regularity: [['regular','대체로 규칙적'],['mixed','요일마다 다름'],['irregular','예측하기 어려움'],['unknown','잘 모르겠어요']],
  barriers: [['starting','시작이 어려움'],['overplanning','과도한 계획'],['distraction','집중력 저하'],['fatigue','피로'],['interruptions','갑작스러운 일'],['unclear','무엇부터 할지 모름'],['none','특별한 어려움 없음'],['unknown','잘 모르겠어요']],
  energy: [['morning','오전'],['afternoon','오후'],['evening','저녁·밤'],['variable','그때그때 다름'],['unknown','잘 모르겠어요']],
  recovery: [['replan','시간을 다시 배치'],['reduce','할 일을 줄임'],['continue','밀린 일을 건너뛰고 계속'],['abandon','그날 계획을 포기'],['unknown','잘 모르겠어요']],
}
const emptyAnswers: ExecutionAnswers = { roles: [], regularity: '', barriers: [], focusMinutes: null, dailyMinutes: null, energy: '', recovery: '', constraints: '', context: '' }

export function ProfileForm({ initial, busy, llmAvailable, onGenerate, onCancel, requestError }: {
  initial?: ExecutionAnswers; busy: boolean; llmAvailable: boolean; requestError?: string
  onGenerate: (answers: ExecutionAnswers, mode: 'demo' | 'llm', consent: boolean) => Promise<void>
  onCancel?: () => void
}) {
  const [answers, setAnswers] = useState(initial ?? emptyAnswers)
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<'demo'|'llm'>('demo')
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState('')
  const stepNames = ['생활의 리듬', '막히는 순간', '집중과 여유', '다시 시작하는 방법']
  function choose(key: keyof ExecutionAnswers, value: string, multiple: boolean) {
    if (!multiple) { setAnswers(a => ({ ...a, [key]: value })); return }
    const selected = answers[key] as string[]
    let next = selected.includes(value) ? selected.filter(s => s!==value) : [...selected, value]
    if (key==='barriers' && !selected.includes(value)) next = ['none','unknown'].includes(value) ? [value] : next.filter(v => !['none','unknown'].includes(v))
    setAnswers(a => ({ ...a, [key]: next }))
  }
  function choice(key: keyof ExecutionAnswers, multiple=false) {
    return <fieldset className="execution-fieldset"><legend>{answerLabels[key]}{multiple && ' · 복수 선택'}</legend><div className="execution-options">
      {options[key].map(([value,label]) => <label key={value} className="execution-option"><input type={multiple?'checkbox':'radio'} name={key} checked={multiple?(answers[key] as string[]).includes(value):answers[key]===value} onChange={() => choose(key,value,multiple)} />{label}</label>)}
    </div></fieldset>
  }
  function notes(key: 'constraints'|'context', hint: string) {
    return <label className="execution-label">{answerLabels[key]} · 선택 사항<textarea maxLength={1500} value={answers[key]} placeholder={hint} onChange={e => setAnswers(a => ({ ...a, [key]: e.target.value }))} /></label>
  }
  function minutes(key: 'focusMinutes'|'dailyMinutes', max: number) {
    return <div className="execution-minutes"><label className="execution-label">{answerLabels[key]} (분)<input type="number" min={5} max={max} step={1} required disabled={answers[key]===null} value={answers[key]??''} onChange={e => setAnswers(a => ({ ...a, [key]: e.target.value===''?0:Number(e.target.value) }))}/></label>
      <label className="execution-inline"><input type="checkbox" checked={answers[key]===null} onChange={e => setAnswers(a => ({ ...a,[key]: e.target.checked?null:25 }))} />아직 모르겠어요</label></div>
  }
  async function submit() {
    const fields: Array<Array<keyof ExecutionAnswers>> = [['roles','regularity'],['barriers'],['energy'],['recovery']]
    if (fields[step].some(k => !answers[k] || (Array.isArray(answers[k]) && !(answers[k] as string[]).length))) { setError('항목을 선택해 주세요. 확실하지 않다면 모름을 선택해 주세요.'); return }
    setError('')
    if (step<3) { setStep(step+1); return }
    await onGenerate(answers,mode,consent)
  }
  return <form className="execution-card" onSubmit={e => { e.preventDefault(); void submit() }}><fieldset disabled={busy} className="execution-fieldset">
    <div className="execution-step">STEP {step+1} / 4 · {stepNames[step]}</div><progress max={4} value={step+1} />
    <h2>{stepNames[step]}</h2><p className="execution-help">최근 2주를 떠올려 답해 주세요. 모르는 시간은 추정하지 않고 비워 둘 수 있어요.</p>
    {step===0 && <>{choice('roles',true)}{choice('regularity')}{notes('constraints','예: 평일 9~18시 근무. 실제 차단 일정은 캘린더에도 등록해 주세요.')}</>}
    {step===1 && <>{choice('barriers',true)}{notes('context','최근 계획이 무너졌던 상황이나 추가 질문의 답을 적어 주세요.')}</>}
    {step===2 && <>{minutes('focusMinutes',180)}{minutes('dailyMinutes',720)}{choice('energy')}</>}
    {step===3 && <>{choice('recovery')}<label className="execution-label">프로필 생성 방식<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="demo">규칙 기반 미리보기</option><option value="llm" disabled={!llmAvailable}>LLM 분석{!llmAvailable?' · 서버 API 키 필요':''}</option></select></label>{mode==='llm' && <label className="execution-inline"><input type="checkbox" required checked={consent} onChange={e => setConsent(e.target.checked)}/>답변을 OpenAI에 전송해 분석하는 데 동의합니다.</label>}</>}
    {(error || requestError) && <p role="alert" className="form-error">{error || requestError}</p>}
    <p className="execution-help">초안과 확정 프로필은 이 컴퓨터의 DB에 저장됩니다. 언제든 초기화할 수 있어요.</p>
    <div className="execution-actions">{onCancel && <button type="button" className="secondary-button" onClick={onCancel}>취소</button>}<button type="button" className="secondary-button" disabled={step===0} onClick={() => setStep(step-1)}>이전</button><button type="submit" className="primary-button">{busy?'생성 중…':step===3?'프로필 생성':'다음'}</button></div>
  </fieldset></form>
}
