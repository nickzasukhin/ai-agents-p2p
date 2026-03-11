/** Orchestrator API client — auth, agent management. */

const BASE = '/orch'

function getSession(): string | null {
  return localStorage.getItem('session_token')
}

function setSession(token: string) {
  localStorage.setItem('session_token', token)
}

function clearSession() {
  localStorage.removeItem('session_token')
  localStorage.removeItem('agent_url')
  localStorage.removeItem('agent_token')
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getSession()
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...opts,
    credentials: 'include',
    headers: { ...headers(), ...(opts.headers as Record<string, string> || {}) },
  })
  if (resp.status === 401) {
    clearSession()
    window.location.hash = '#/auth'
    throw new Error('Session expired')
  }
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.detail || data.message || `Error ${resp.status}`)
  return data
}

// ── Auth ──────────────────────────────────────────────────

export async function requestMagicLink(email: string) {
  return request<{ ok: boolean; message: string }>('/auth/request-magic-link', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export interface VerifyResult {
  ok: boolean
  session_token: string
  user_id: string
  email: string
  subdomain: string | null
  is_new_user: boolean
  has_agent: boolean
  agent_url: string | null
}

export async function verifyMagicLink(token: string): Promise<VerifyResult> {
  const data = await request<VerifyResult>(`/auth/verify?token=${encodeURIComponent(token)}`, {
    method: 'GET',
    headers: {},  // No auth needed for verify
  })
  setSession(data.session_token)
  if (data.agent_url) {
    localStorage.setItem('agent_url', data.agent_url)
  }
  return data
}

export interface UserInfo {
  user_id: string
  email: string
  subdomain?: string
  created_at: string
  has_agent: boolean
  agent_url?: string
  agent_status?: string
}

export async function getMe(): Promise<UserInfo> {
  return request<UserInfo>('/auth/me')
}

export async function logout() {
  try { await request('/auth/logout', { method: 'POST' }) } catch {}
  clearSession()
}

// ── Agent Management ─────────────────────────────────────

export interface CreateAgentResult {
  ok: boolean
  agent_url: string
  api_token: string
  status: string
  instance_id: string
}

export async function createAgent(agentName: string = 'My Agent'): Promise<CreateAgentResult> {
  const data = await request<CreateAgentResult>('/agents/create', {
    method: 'POST',
    body: JSON.stringify({ agent_name: agentName }),
  })
  if (data.agent_url) localStorage.setItem('agent_url', data.agent_url)
  if (data.api_token) localStorage.setItem('agent_token', data.api_token)
  return data
}

export interface AgentInfo {
  has_agent: boolean
  agent_url?: string
  api_token?: string
  status?: string
  port?: number
  container_health?: { status: string; running: boolean }
  created_at?: string
}

export async function getMyAgent(): Promise<AgentInfo> {
  return request<AgentInfo>('/agents/mine')
}

export async function deleteMyAgent() {
  return request<{ ok: boolean }>('/agents/mine', { method: 'DELETE' })
}

// ── Session helpers ──────────────────────────────────────

export function isAuthenticated(): boolean {
  return !!getSession()
}

export { getSession, setSession, clearSession }
