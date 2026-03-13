/** Agent API client — proxy to user's personal agent.
 *
 * In dev, calls go through /agent proxy (vite.config.ts).
 * In prod, calls go directly to agent_url with agent_token.
 */

function getAgentBase(): string {
  // On user subdomain (e.g. yennefer.agents.devpunks.io) — agent is same origin
  const host = typeof window !== 'undefined' ? window.location.hostname : ''
  if (host.endsWith('.agents.devpunks.io')) return ''
  // In production (same origin as agent) — empty string = same origin
  if (host && !host.includes('localhost')) return ''
  // In production with orchestrator, use the assigned agent URL
  const agentUrl = localStorage.getItem('agent_url')
  if (agentUrl && !agentUrl.includes('localhost')) return agentUrl
  // In dev, use the vite proxy
  return '/agent'
}

function getAgentToken(): string | null {
  // Try localStorage first, then cookie (set by orchestrator across subdomains)
  const stored = localStorage.getItem('agent_token')
  if (stored) return stored
  const match = document.cookie.match(/(?:^|;\s*)agent_token=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : null
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getAgentToken()
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

async function agentRequest<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const base = getAgentBase()
  const resp = await fetch(`${base}${path}`, {
    ...opts,
    headers: { ...headers(), ...(opts.headers as Record<string, string> || {}) },
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.detail || `Agent error ${resp.status}`)
  return data
}

// ── Health ────────────────────────────────────────────────

export async function getHealth() {
  return agentRequest<{ status: string }>('/health')
}

/** Poll agent /health until it responds 200 or timeout (default 30s). */
export async function waitForReady(timeoutMs = 30000): Promise<boolean> {
  const base = getAgentBase()
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(`${base}/health`, { headers: headers() })
      if (resp.ok) return true
    } catch {
      // Container not ready yet
    }
    await new Promise((r) => setTimeout(r, 2000))
  }
  return false
}

// ── Onboarding ───────────────────────────────────────────

export interface OnboardingStatus {
  has_profile: boolean
  has_skills: boolean
  onboarding_complete: boolean
}

export async function getOnboardingStatus() {
  return agentRequest<OnboardingStatus>('/onboarding/status')
}

export interface OnboardingResponse {
  session_id: string
  state: string
  response: string
  progress: number
  card_preview?: {
    agent_name: string
    skills: string[]
    needs: string[]
  }
  files_preview?: Record<string, string>
}

export async function startOnboarding() {
  return agentRequest<OnboardingResponse>('/onboarding/start', { method: 'POST' })
}

export async function chatOnboarding(sessionId: string, message: string) {
  return agentRequest<OnboardingResponse>('/onboarding/chat', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message }),
  })
}

export async function confirmOnboarding(sessionId: string) {
  return agentRequest<OnboardingResponse>('/onboarding/confirm', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  })
}

// ── Network ──────────────────────────────────────────────

export interface GoOnlineResult {
  status: string
  public_url: string
  tunnel_provider: string | null
  tunnel_started: boolean
  registered_registries: string[]
  discovery_triggered: boolean
}

export async function goOnline() {
  return agentRequest<GoOnlineResult>('/network/go-online', { method: 'POST' })
}

export interface OnlineStatus {
  is_online: boolean
  public_url: string
  tunnel_active: boolean
  tunnel_provider: string | null
}

export async function getOnlineStatus() {
  return agentRequest<OnlineStatus>('/network/go-online/status')
}

// ── Search ───────────────────────────────────────────────

export interface SearchResult {
  agent_url: string
  agent_name: string
  description: string
  skills: { name: string; description: string; tags: string[] }[]
  match_score: number
  source: string
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  total: number
}

export async function searchAgents(query: string, limit: number = 20) {
  return agentRequest<SearchResponse>(`/search?q=${encodeURIComponent(query)}&limit=${limit}`)
}

// ── Agent Detail ─────────────────────────────────────────

export interface AgentSkillDetail {
  id: string
  name: string
  description: string
  tags: string[]
}

export interface SkillMatch {
  our_text: string
  their_text: string
  similarity: number
  direction: string
}

export interface AgentMatchDetail {
  overall_score: number
  is_mutual: boolean
  score_breakdown: Record<string, number> | null
  skill_matches: SkillMatch[]
}

export interface AgentDetail {
  agent_url: string
  agent_name: string
  description: string
  skills: AgentSkillDetail[]
  did: string
  verified: boolean
  version: string
  provider: { organization: string; url: string } | null
  match: AgentMatchDetail | null
}

export async function getAgentDetail(url: string) {
  return agentRequest<AgentDetail>(`/discovery/agent?url=${encodeURIComponent(url)}`)
}

// ── Discovery/Matches ────────────────────────────────────

export interface Match {
  agent_url: string
  agent_name: string
  overall_score: number
  their_skills_text: string
  their_description: string
  is_mutual: boolean
  skill_matches: {
    our_text: string
    their_text: string
    similarity: number
    direction: string
  }[]
}

export async function getMatches() {
  return agentRequest<{ matches: Match[] }>('/discovery/matches')
}

// ── Chat ─────────────────────────────────────────────────

export interface ChatMessage {
  id: string
  peer_url: string
  direction: string
  content: string
  timestamp: string
}

export async function getChats() {
  return agentRequest<{ chats: Record<string, ChatMessage[]> }>('/chats')
}

export async function sendChat(peerUrl: string, message: string) {
  return agentRequest<{ ok: boolean }>('/chats/send', {
    method: 'POST',
    body: JSON.stringify({ peer_url: peerUrl, message }),
  })
}

// ── Invite ───────────────────────────────────────────────

export interface InviteData {
  agent_name: string
  description: string
  skills: string[]
  agent_url: string
  did: string
}

export async function getInviteData() {
  return agentRequest<InviteData>('/invite/data')
}

// ── Negotiate ────────────────────────────────────────────

export async function startNegotiation(peerUrl: string) {
  return agentRequest<{ ok: boolean; negotiation_id?: string }>('/negotiations/start-one', {
    method: 'POST',
    body: JSON.stringify({ peer_url: peerUrl }),
  })
}
