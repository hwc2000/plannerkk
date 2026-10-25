import type { AuthUser, WorkspaceData } from '../../shared/types'

export const UNAUTHORIZED_EVENT = 'replan:unauthorized'

async function request<T>(url: string, init?: RequestInit): Promise<{ ok: boolean; status: number; data: T }> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
  })
  const data = await response.json().catch(() => ({}))
  return { ok: response.ok, status: response.status, data: data as T }
}

function errorMessage(data: unknown, fallback: string) {
  const detail = (data as { detail?: unknown })?.detail
  return typeof detail === 'string' ? detail : fallback
}

/** Whether the server requires login. Older servers without the endpoint run in open mode. */
export async function fetchAuthEnabled(): Promise<boolean> {
  try {
    const { ok, data } = await request<{ enabled?: boolean }>('/api/auth/config')
    return ok && data.enabled === true
  } catch {
    return false
  }
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const { ok, data } = await request<{ user?: AuthUser }>('/api/auth/me')
  return ok && data.user ? data.user : null
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const { ok, data } = await request<{ user: AuthUser }>('/api/auth/login', {
    method: 'POST', body: JSON.stringify({ email, password }),
  })
  if (!ok) throw new Error(errorMessage(data, '로그인하지 못했습니다.'))
  return data.user
}

export async function signup(email: string, password: string, displayName: string): Promise<AuthUser> {
  const { ok, data } = await request<{ user: AuthUser }>('/api/auth/signup', {
    method: 'POST', body: JSON.stringify({ email, password, displayName }),
  })
  if (!ok) throw new Error(errorMessage(data, '회원가입하지 못했습니다.'))
  return data.user
}

export async function logout(): Promise<void> {
  await request('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
}

export async function fetchWorkspace(): Promise<WorkspaceData & { exists: boolean }> {
  const { ok, status, data } = await request<WorkspaceData & { exists: boolean; detail?: string }>('/api/workspace')
  if (status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  if (!ok) throw new Error(errorMessage(data, '내 플래너 데이터를 불러오지 못했습니다.'))
  return data
}

export async function saveWorkspace(workspace: WorkspaceData): Promise<void> {
  const { ok, status, data } = await request('/api/workspace', { method: 'PUT', body: JSON.stringify(workspace) })
  if (status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  if (!ok) throw new Error(errorMessage(data, '변경 내용을 저장하지 못했습니다.'))
}
