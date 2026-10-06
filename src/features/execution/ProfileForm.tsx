import { useState } from 'react'
import type { ExecutionAnswers } from '../../shared/types'

import { answerLabels, options } from './profileLabels'

const emptyAnswers: ExecutionAnswers = { roles: [], regularity: '', barriers: [], focusMinutes: null, dailyMinutes: null, energy: '', recovery: '', constraints: '', context: '', scheduleStyle: 'unknown' }

export function ProfileForm({ initial, busy, onGenerate, onCancel, requestError }: {
  initial?: ExecutionAnswers; busy: boolean; requestError?: string
  onGenerate: (answers: ExecutionAnswers, mode: 'demo' | 'llm', consent: boolean) => Promise<void>
  onCancel?: () => void
}) {
  const [answers, setAnswers] = useState(initial ?? emptyAnswers)
  const [step, setStep] = useState(0)
  const [error, setError] = useState('')
  const stepNames = ['생활의 리듬', '막히는 순간', '집중 습관', '다시 시작하는 방법']
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
  async function submit() {
    const fields: Array<Array<keyof ExecutionAnswers>> = [['roles','regularity'],['barriers'],['energy'],['recovery','scheduleStyle']]
    if (fields[step].some(k => !answers[k] || (Array.isArray(answers[k]) && !(answers[k] as string[]).length))) { setError('항목을 선택해 주세요. 확실하지 않다면 모름을 선택해 주세요.'); return }
    setError('')
    if (step<3) { setStep(step+1); return }
    await onGenerate({ ...answers, dailyMinutes: null },'demo',false)
  }
  return <form className="execution-card" onSubmit={e => { e.preventDefault(); void submit() }}><fieldset disabled={busy} className="execution-fieldset">
    <div className="execution-step">STEP {step+1} / 4 · {stepNames[step]}</div><progress max={4} value={step+1} />
    <h2>{stepNames[step]}</h2><p className="execution-help">최근 2주를 떠올리며 선택해 줘. 가용시간은 프로필을 확정한 다음 고를 수 있어.</p>
    {step===0 && <>{choice('roles',true)}{choice('regularity')}</>}
    {step===1 && <>{choice('barriers',true)}</>}
    {step===2 && <><fieldset className="execution-fieldset"><legend>쉬지 않고 한 번에 집중하기 편한 시간은?</legend><div className="execution-options">{[15,25,30,45,50,60,90,null].map(value => <label className="execution-option" key={String(value)}><input type="radio" name="focusMinutes" checked={answers.focusMinutes===value} onChange={()=>setAnswers(a=>({...a,focusMinutes:value}))}/>{value===null?'아직 모르겠어요':`${value}분`}</label>)}</div></fieldset>{choice('energy')}</>}
    {step===3 && <>{choice('recovery')}{choice('scheduleStyle')}</>}
    {(error || requestError) && <p role="alert" className="form-error">{error || requestError}</p>}
    <p className="execution-help">초안과 확정 프로필은 이 컴퓨터의 DB에 저장됩니다. 언제든 초기화할 수 있어요.</p>
    <div className="execution-actions">{onCancel && <button type="button" className="secondary-button" onClick={onCancel}>취소</button>}<button type="button" className="secondary-button" disabled={step===0} onClick={() => setStep(step-1)}>이전</button><button type="submit" className="primary-button">{busy?'생성 중…':step===3?'프로필 생성':'다음'}</button></div>
  </fieldset></form>
}
