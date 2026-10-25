import { useState, type FormEvent } from 'react'
import { Sparkles } from 'lucide-react'
import type { AuthUser } from '../../shared/types'
import { login, signup } from './api'
import './auth.css'

type Mode = 'login' | 'signup'

export function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function switchMode(next: Mode) {
    setMode(next)
    setError('')
    setPassword('')
    setPasswordConfirm('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (mode === 'signup') {
      if (password.length < 8) return setError('비밀번호는 8자 이상이어야 합니다.')
      if (password !== passwordConfirm) return setError('비밀번호 확인이 일치하지 않습니다.')
    }
    setBusy(true)
    try {
      const user = mode === 'login'
        ? await login(email, password)
        : await signup(email, password, displayName.trim())
      onAuthenticated(user)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '요청을 처리하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="brand auth-brand">
          <span className="brand-mark"><Sparkles size={15} /></span>
          <span>re:plan</span>
        </div>
        <p className="eyebrow">PERSONAL PLANNER</p>
        <h1 id="auth-title">{mode === 'login' ? '다시 오신 걸 환영해요' : '나만의 플래너 만들기'}</h1>
        <p className="auth-copy">
          {mode === 'login'
            ? '로그인하면 내 실행 프로필과 생활 패턴에 맞춘 계획을 이어서 볼 수 있습니다.'
            : '계정마다 프로젝트·일정·기억·실행 프로필이 따로 저장되고, AI 계획도 내 프로필을 기준으로 만들어집니다.'}
        </p>

        <div className="auth-tabs" role="tablist" aria-label="로그인 또는 회원가입">
          <button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'active' : ''} onClick={() => switchMode('login')}>로그인</button>
          <button type="button" role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'active' : ''} onClick={() => switchMode('signup')}>회원가입</button>
        </div>

        <form className="auth-form" onSubmit={submit} noValidate>
          {mode === 'signup' && (
            <label className="plan-field">이름(표시 이름)
              <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={40} required autoComplete="nickname" placeholder="예: 현우" />
            </label>
          )}
          <label className="plan-field">이메일
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" placeholder="you@example.com" />
          </label>
          <label className="plan-field">비밀번호
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === 'signup' ? 8 : 1}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder={mode === 'signup' ? '8자 이상' : ''} />
          </label>
          {mode === 'signup' && (
            <label className="plan-field">비밀번호 확인
              <input type="password" value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)} required autoComplete="new-password" />
            </label>
          )}
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="primary-button full" type="submit" disabled={busy || !email || !password || (mode === 'signup' && !displayName.trim())}>
            {busy ? '처리 중…' : mode === 'login' ? '로그인' : '가입하고 시작하기'}
          </button>
        </form>
      </section>
    </div>
  )
}
