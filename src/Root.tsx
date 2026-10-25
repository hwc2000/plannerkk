import { useCallback, useEffect, useRef, useState } from 'react'
import App from './App'
import { AuthScreen } from './features/auth/AuthScreen'
import {
  UNAUTHORIZED_EVENT,
  fetchAuthEnabled,
  fetchCurrentUser,
  fetchWorkspace,
  logout,
  saveWorkspace,
} from './features/auth/api'
import { seedEvents, seedMemories, seedMilestones, seedProjects } from './shared/constants'
import type { AuthUser, WorkspaceData } from './shared/types'
import './features/auth/auth.css'

const LEGACY_KEYS = {
  projects: 'replan-projects-v1',
  milestones: 'replan-milestones-v1',
  events: 'replan-events-v1',
  memories: 'replan-memories-v1',
} as const

function readLegacy<T>(key: string): T[] | null {
  try {
    const raw = localStorage.getItem(key)
    const parsed = raw ? JSON.parse(raw) : null
    return Array.isArray(parsed) ? parsed as T[] : null
  } catch {
    return null
  }
}

/** Data saved in this browser before login existed (or in open single-user mode). */
function legacyWorkspace(): WorkspaceData | null {
  const value = {
    projects: readLegacy(LEGACY_KEYS.projects),
    milestones: readLegacy(LEGACY_KEYS.milestones),
    events: readLegacy(LEGACY_KEYS.events),
    memories: readLegacy(LEGACY_KEYS.memories),
  }
  if (Object.values(value).every((items) => items === null)) return null
  return {
    projects: (value.projects ?? []) as WorkspaceData['projects'],
    milestones: (value.milestones ?? []) as WorkspaceData['milestones'],
    events: (value.events ?? []) as WorkspaceData['events'],
    memories: (value.memories ?? []) as WorkspaceData['memories'],
  }
}

const emptyWorkspace: WorkspaceData = { projects: [], milestones: [], events: [], memories: [] }

type Phase =
  | { kind: 'loading' }
  | { kind: 'open'; workspace: WorkspaceData }
  | { kind: 'login' }
  | { kind: 'ready'; user: AuthUser; workspace: WorkspaceData }
  | { kind: 'error'; message: string }

export function Root() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  const saveTimer = useRef<number | undefined>(undefined)
  const [saveError, setSaveError] = useState('')

  const enterAs = useCallback(async (user: AuthUser) => {
    setPhase({ kind: 'loading' })
    try {
      const stored = await fetchWorkspace()
      let workspace: WorkspaceData = stored.exists
        ? { projects: stored.projects, milestones: stored.milestones, events: stored.events, memories: stored.memories }
        : emptyWorkspace
      if (!stored.exists) {
        const legacy = legacyWorkspace()
        if (legacy && window.confirm('이 브라우저에 로그인 전에 저장한 프로젝트·일정·기억이 있습니다. 내 계정으로 가져올까요?')) {
          workspace = legacy
        }
        await saveWorkspace(workspace)
      }
      setPhase({ kind: 'ready', user, workspace })
    } catch (error) {
      setPhase({ kind: 'error', message: error instanceof Error ? error.message : '데이터를 불러오지 못했습니다.' })
    }
  }, [])

  const boot = useCallback(async () => {
    setPhase({ kind: 'loading' })
    if (!(await fetchAuthEnabled())) {
      setPhase({ kind: 'open', workspace: {
        projects: readLegacy(LEGACY_KEYS.projects) ?? seedProjects,
        milestones: readLegacy(LEGACY_KEYS.milestones) ?? seedMilestones,
        events: readLegacy(LEGACY_KEYS.events) ?? seedEvents,
        memories: readLegacy(LEGACY_KEYS.memories) ?? seedMemories,
      } })
      return
    }
    const user = await fetchCurrentUser().catch(() => null)
    if (user) await enterAs(user)
    else setPhase({ kind: 'login' })
  }, [enterAs])

  useEffect(() => { void boot() }, [boot])

  useEffect(() => {
    const expired = () => setPhase((current) => current.kind === 'ready' ? { kind: 'login' } : current)
    window.addEventListener(UNAUTHORIZED_EVENT, expired)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expired)
  }, [])

  const persist = useCallback((workspace: WorkspaceData) => {
    if (phase.kind === 'open') {
      Object.entries(LEGACY_KEYS).forEach(([field, key]) => {
        localStorage.setItem(key, JSON.stringify(workspace[field as keyof WorkspaceData]))
      })
      return
    }
    if (phase.kind !== 'ready') return
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      saveWorkspace(workspace)
        .then(() => setSaveError(''))
        .catch((error) => setSaveError(error instanceof Error ? error.message : '저장하지 못했습니다.'))
    }, 500)
  }, [phase.kind])

  async function signOut() {
    window.clearTimeout(saveTimer.current)
    await logout()
    setPhase({ kind: 'login' })
  }

  if (phase.kind === 'loading') return <div className="auth-loading" role="status">불러오는 중…</div>
  if (phase.kind === 'login') return <AuthScreen onAuthenticated={(user) => { void enterAs(user) }} />
  if (phase.kind === 'error') {
    return (
      <div className="auth-loading">
        <div style={{ display: 'grid', gap: 12, justifyItems: 'center' }}>
          <p role="alert">{phase.message}</p>
          <button className="primary-button" onClick={() => { void boot() }}>다시 시도</button>
        </div>
      </div>
    )
  }
  if (phase.kind === 'open') return <App initial={phase.workspace} onPersist={persist} />
  return (
    <App
      key={phase.user.id}
      initial={phase.workspace}
      onPersist={persist}
      user={phase.user}
      onLogout={() => { void signOut() }}
      saveError={saveError}
    />
  )
}
