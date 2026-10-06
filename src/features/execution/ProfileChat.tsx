import { useEffect, useRef, useState } from 'react'
import type { ExecutionState } from '../../shared/types'
import { answerLabels } from './profileLabels'
import { FixedSchedulePicker } from './FixedSchedulePicker'
import { executionApi } from './api'

type Session = {
  id: string; ready: boolean; answers: Record<string, unknown>
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string }>
  editableQuestions?: Array<{ field: string; text: string }>
  question: { field: string; text: string; choices: Array<{ label: string; value: string }> } | null
}
export function ProfileChat({ state, busy, run, onReviewed, onCancel }: {
  state: ExecutionState; busy: boolean
  run: (action: () => Promise<ExecutionState>, message: string) => Promise<boolean>
  onReviewed: () => void; onCancel?: () => void
}) {
  const [session, setSession] = useState<Session | null>(null)
  const [text, setText] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const multiple = session?.question?.field === 'roles' || session?.question?.field === 'barriers'
  const [mode, setMode] = useState<'guided' | 'llm'>(state.llmAvailable ? 'llm' : 'guided')
  const [consent, setConsent] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let active = true
    setLoading(true)
    fetch('/api/execution/profile/chat').then(async r => {
      if (!r.ok) throw new Error('저장된 대화를 불러오지 못했습니다.')
      const data = await r.json()
      if (active) { setSession(data.session); setError('') }
    }).catch(e => { if (active) setError(String(e)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [state.revision])
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }) }, [session?.messages.length])
  useEffect(() => { setSelected([]) }, [session?.id, session?.question?.field])
  function toggleChoice(value: string) {
    setSelected(previous => {
      if (previous.includes(value)) return previous.filter(item => item !== value)
      if (!multiple) return [value]
      if (session?.question?.field === 'barriers') {
        if (value === 'none' || value === 'unknown') return [value]
        return [...previous.filter(item => item !== 'none' && item !== 'unknown'), value]
      }
      return [...previous, value]
    })
  }
  async function send(value: string) {
    if (!session || !value.trim() || busy || loading) return false
    const ok = await run(() => executionApi('/profile/chat/message', {
      revision: state.revision, sessionId: session.id, text: value, mode, consent,
    }), '답변을 대화에 저장했습니다.')
    if (ok) { setText(''); setSelected([]) }
    return ok
  }
  return <section className="execution-card profile-chat" aria-label="프로필 설문 대화">
    <p className="section-kicker">LET’S TALK</p><h2>대화로 알아가는 나의 계획 습관</h2>
    <p className="execution-help">한 번에 하나씩 이야기해요. 대화에서 정리한 답변은 검토 후 프로필에 반영됩니다. 기존 확정 프로필은 새 초안을 확정할 때까지 유지돼요.</p>
    <label className="execution-label">대화 방식<select value={mode} disabled={busy} onChange={e => setMode(e.target.value as typeof mode)}>
      <option value="guided">안내형 대화 · 선택지와 간단한 답변</option>
      <option value="llm" disabled={!state.llmAvailable}>AI 자유 대화{!state.llmAvailable && ' · 서버 API 키 필요'}</option>
    </select></label>
    {mode === 'llm' && <label className="execution-inline"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>이 대화 내용을 AI에 전송하여 답변을 정리하는 데 동의합니다.</label>}
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="profile-chat-log" role="log" aria-live="polite" aria-label="설문 대화 기록">
      {!session && !loading && <p className="profile-chat-message assistant">안녕하세요! 생활 리듬부터 원하는 계획 방식까지 함께 정리해 볼게요.</p>}
      {session?.messages.map(m => <div key={m.id} className={`profile-chat-message ${m.role}`}><small>{m.role === 'user' ? '나' : '플래너'}</small><p>{m.content}</p></div>)}
      {(busy || loading) && <p role="status">{busy ? '답변을 정리하고 있어요…' : '대화를 불러오고 있어요…'}</p>}
      <div ref={end}/>
    </div>
    {!session ? <button className="primary-button" disabled={busy || loading || !!error} onClick={() => { void run(() => executionApi('/profile/chat/start', { revision: state.revision }), '대화를 시작했습니다.') }}>대화 시작</button> : <>
      {session.question?.field === 'constraints' && <FixedSchedulePicker disabled={busy || loading} canSend={mode !== 'llm' || consent} onSend={send}/>}
      {session.question && session.question.field !== 'constraints' && <div>
        <p className="execution-help">{multiple ? '여러 항목을 선택할 수 있어요. 선택을 마치면 아래 버튼으로 보내 주세요.' : '답변을 선택한 뒤 아래 버튼으로 보내 주세요.'}</p>
        <div className="profile-chat-choices" role="group" aria-label="답변 선택">{session.question.choices.map(c => <button type="button" className="secondary-button" aria-pressed={selected.includes(c.value)} key={c.label} disabled={busy || loading} onClick={() => toggleChoice(c.value)}>{c.label}</button>)}</div>
        <button type="button" className="primary-button" disabled={busy || loading || !selected.length || (mode === 'llm' && !consent)} onClick={() => {
          const labels = selected.map(value => session.question!.choices.find(c => c.value === value)!.label)
          void send(labels.join(', '))
        }}>선택한 답변 보내기{selected.length > 0 ? ` (${selected.length})` : ''}</button>
      </div>}
      {session.question?.field !== 'constraints' && (!session.ready || mode === 'llm') && <form onSubmit={e => { e.preventDefault(); void send(text) }}>
        <label className="execution-label">나의 답변<textarea maxLength={1500} value={text} disabled={busy || loading} onChange={e => setText(e.target.value)} placeholder={mode === 'llm' ? '예: 평일에는 회사에 다니고, 퇴근 후 공부는 30분 정도가 편해요.' : '선택지의 답변을 입력하거나 시간을 적어 주세요. 복수 선택은 쉼표로 구분해요.'}/></label>
        <button className="primary-button" disabled={busy || loading || !text.trim() || (mode === 'llm' && !consent)}>보내기</button>
      </form>}
      {session.ready && <button className="primary-button" disabled={busy || loading} onClick={() => {
        void run(() => executionApi('/profile/chat/draft', { revision: state.revision, sessionId: session.id }), '대화를 반영한 초안을 만들었습니다. 답변과 선호를 검토해 주세요.').then(ok => { if (ok) onReviewed() })
      }}>프로필 요약 보기</button>}
    </>}
    {session?.ready && <div className="profile-chat-choices" aria-label="수정할 항목">{session.editableQuestions?.map(q => <button className="secondary-button" type="button" key={q.field} disabled={busy || loading} onClick={() => { void run(() => executionApi('/profile/chat/question', { revision: state.revision, sessionId: session.id, field: q.field }), '수정할 답변을 알려 주세요.') }}>{answerLabels[q.field] ?? q.field} 수정</button>)}</div>}
    <p className="execution-help">대화는 이 컴퓨터의 DB에 저장되어 다시 이어갈 수 있습니다. AI가 정리한 답변은 대화로 수정할 수 있어요.</p>
    {onCancel && <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>프로필 요약으로 돌아가기</button>}
  </section>
}
