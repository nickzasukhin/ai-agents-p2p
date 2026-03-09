const BASE = '/api'

// ── Auth Token Management (Phase 10) ────────────────────────

const TOKEN_KEY = 'a2a_api_token'

export function getApiToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setApiToken(token: string): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

export function hasApiToken(): boolean {
  return !!localStorage.getItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = getApiToken()
  if (token) {
    return { 'Authorization': `Bearer ${token}` }
  }
  return {}
}

// ── Error handling ──────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: any,
  ) {
    super(`API ${status}: ${statusText}`)
    this.name = 'ApiError'
  }
}

async function apiFetch<T = any>(
  url: string,
  opts?: RequestInit,
): Promise<T> {
  const headers = {
    ...authHeaders(),
    ...(opts?.headers || {}),
  }
  const res = await fetch(`${BASE}${url}`, { ...opts, headers })
  if (!res.ok) {
    let body: any = null
    try { body = await res.json() } catch {}
    throw new ApiError(res.status, res.statusText, body)
  }
  return res.json()
}

// ── Health & Agent ──────────────────────────────────────────

export async function fetchHealth() {
  return apiFetch('/health')
}

// ── Discovery ───────────────────────────────────────────────

export async function fetchMatches() {
  return apiFetch<{ matches: Match[] }>('/discovery/matches')
}

export async function fetchDiscoveredAgents() {
  return apiFetch('/discovery/agents')
}

export async function runDiscovery() {
  return apiFetch('/discovery/run', { method: 'POST' })
}

export async function fetchDiscoveryStatus() {
  return apiFetch<DiscoveryStatus>('/discovery/status')
}

// ── Negotiations ────────────────────────────────────────────

export async function fetchNegotiations() {
  return apiFetch<{ negotiations: Negotiation[] }>('/negotiations')
}

export async function fetchPendingApprovals() {
  return apiFetch('/negotiations/pending')
}

export async function startNegotiations() {
  return apiFetch('/negotiations/start', { method: 'POST' })
}

export async function sendNegotiation(id: string) {
  return apiFetch(`/negotiations/${id}/send`, { method: 'POST' })
}

export async function approveNegotiation(id: string) {
  return apiFetch(`/negotiations/${id}/approve`, { method: 'POST' })
}

export async function rejectNegotiation(id: string) {
  return apiFetch(`/negotiations/${id}/reject`, { method: 'POST' })
}

// ── Profile & Identity ──────────────────────────────────────

export async function fetchProfile() {
  return apiFetch('/profile')
}

export async function updateProfileFile(filename: string, content: string) {
  return apiFetch(`/profile/${filename}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export async function fetchIdentity() {
  return apiFetch('/identity')
}

// ── Network & Gossip & DHT ──────────────────────────────────

export async function fetchGossipStats() {
  return apiFetch('/gossip/stats')
}

export async function fetchGossipPeers() {
  return apiFetch<GossipPeer[]>('/gossip/peers')
}

export async function fetchDhtStats() {
  return apiFetch('/dht/stats')
}

export async function dhtLookup(did: string) {
  return apiFetch(`/dht/lookup/${encodeURIComponent(did)}`)
}

export async function fetchNetworkStatus() {
  return apiFetch<NetworkStatus>('/network/status')
}

export async function checkNetworkReachability() {
  return apiFetch<{ reachable: boolean; url: string; latency_ms: number }>('/network/check', { method: 'POST' })
}

// ── Card ────────────────────────────────────────────────────

export async function fetchCard() {
  return apiFetch('/card')
}

export async function rebuildCard() {
  return apiFetch('/card/rebuild', { method: 'POST' })
}

// ── Events ──────────────────────────────────────────────────

export async function fetchRecentEvents() {
  return apiFetch('/events/recent')
}

export function subscribeToEvents(
  onEvent: (event: any) => void,
  lastEventId = 0,
): EventSource {
  const url = `${BASE}/events/stream`
  const es = new EventSource(url)

  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      onEvent(data)
    } catch {}
  }

  const types = [
    'match_found', 'negotiation_started', 'negotiation_received',
    'negotiation_update', 'negotiation_accepted', 'negotiation_rejected',
    'negotiation_timeout', 'match_confirmed', 'match_declined',
    'agent_discovered', 'discovery_cycle',
    'project_created', 'project_recruiting', 'project_active',
    'project_stalled', 'project_completed', 'project_suggestion',
  ]
  types.forEach(type => {
    es.addEventListener(type, (e: any) => {
      try {
        const data = JSON.parse(e.data)
        onEvent(data)
      } catch {}
    })
  })

  return es
}

// ── WebSocket (Phase 6.8) ───────────────────────────────────

export type WSHandlers = {
  onEvent?: (event: AgentEvent) => void
  onMatchesUpdate?: (matches: Match[]) => void
  onNegotiationsUpdate?: (negotiations: Negotiation[]) => void
  onHealthUpdate?: (health: any) => void
  onChatUpdate?: (chats: ChatChannel[]) => void
  onConnectionChange?: (connected: boolean) => void
}

export function connectWebSocket(handlers: WSHandlers): {
  close: () => void
  send: (msg: any) => void
} {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}${BASE}/ws`

  let ws: WebSocket | null = null
  let reconnectAttempts = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let closed = false
  let sseCleanup: (() => void) | null = null

  function processMessage(msg: any) {
    if (!msg || !msg.type) return

    if (msg.type === 'event') {
      handlers.onEvent?.(msg.data)
    } else if (msg.type === 'state') {
      if (msg.channel === 'matches') handlers.onMatchesUpdate?.(msg.data)
      else if (msg.channel === 'negotiations') handlers.onNegotiationsUpdate?.(msg.data)
      else if (msg.channel === 'health') handlers.onHealthUpdate?.(msg.data)
      else if (msg.channel === 'chat') handlers.onChatUpdate?.(msg.data)
    } else if (msg.type === 'batch') {
      for (const m of msg.messages || []) processMessage(m)
    } else if (msg.type === 'ping') {
      ws?.send(JSON.stringify({ pong: true }))
    }
  }

  function connect() {
    if (closed) return

    try {
      ws = new WebSocket(wsUrl)
    } catch {
      fallbackToSSE()
      return
    }

    ws.onopen = () => {
      reconnectAttempts = 0
      handlers.onConnectionChange?.(true)
      ws!.send(JSON.stringify({
        subscribe: ['events', 'matches', 'negotiations', 'health', 'chat'],
      }))
    }

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        processMessage(msg)
      } catch {}
    }

    ws.onclose = () => {
      handlers.onConnectionChange?.(false)
      if (!closed) scheduleReconnect()
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function scheduleReconnect() {
    if (closed) return
    reconnectAttempts++

    if (reconnectAttempts > 3) {
      fallbackToSSE()
      return
    }

    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 30000)
    reconnectTimer = setTimeout(connect, delay)
  }

  function fallbackToSSE() {
    if (sseCleanup || closed) return
    const es = subscribeToEvents((event) => {
      handlers.onEvent?.(event)
    })
    handlers.onConnectionChange?.(true)
    sseCleanup = () => es.close()
  }

  connect()

  return {
    close: () => {
      closed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
      sseCleanup?.()
    },
    send: (msg: any) => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg))
      }
    },
  }
}

// ── Types ───────────────────────────────────────────────────

export type AgentSkill = {
  name: string
  description: string
  tags: string[]
}

export type Match = {
  agent_url: string
  agent_name: string
  overall_score: number
  is_mutual: boolean
  description: string
  top_matches: {
    our_text: string
    their_text: string
    similarity: number
    direction: string
  }[]
}

export type NegotiationMsg = {
  sender: string
  content: string
  round: number
  type: string
  timestamp: string
}

export type Negotiation = {
  id: string
  our_name: string
  their_name: string
  their_url: string
  state: string
  match_score: number
  current_round: number
  max_rounds: number
  is_terminal: boolean
  collaboration_summary: string
  owner_decision: string | null
  messages: NegotiationMsg[]
  created_at: string
  updated_at: string
}

export type AgentEvent = {
  id: number
  type: string
  data: Record<string, any>
  timestamp: string
}

// ── Network types ───────────────────────────────────────────

export type NetworkStatus = {
  external_url: string
  nat_type: string
  relay_enabled: boolean
  relay_url: string | null
  udp_port: number | null
  reachable: boolean | null
}

export type DiscoveryStatus = {
  is_running: boolean
  runs_completed: number
  discovered_agents: number
  matches: number
  last_run: string | null
}

export type GossipPeer = {
  url: string
  name: string
  last_seen: string
}

// ── Projects (Phase 6.4) ────────────────────────────────────

export type ProjectRole = {
  role_name: string
  description: string
  agent_url: string
  agent_name: string
  negotiation_id: string
  status: string
}

export type Project = {
  id: string
  name: string
  description: string
  coordinator_url: string
  coordinator_name: string
  state: string
  roles: ProjectRole[]
  progress: number
  filled_roles: number
  total_roles: number
  open_roles: number
  is_terminal: boolean
  created_at: string
  updated_at: string
}

export async function fetchProjects() {
  return apiFetch<{ projects: Project[] }>('/projects')
}

export async function createProject(name: string, description: string, roles: { role_name: string; description: string; agent_url?: string }[]) {
  return apiFetch('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description, roles }),
  })
}

export async function suggestProject() {
  return apiFetch('/projects/suggest', { method: 'POST' })
}

export async function fetchProject(id: string) {
  return apiFetch(`/projects/${id}`)
}

export async function recruitProject(id: string) {
  return apiFetch(`/projects/${id}/recruit`, { method: 'POST' })
}

export async function syncProject(id: string) {
  return apiFetch(`/projects/${id}/sync`, { method: 'POST' })
}

export async function completeProject(id: string) {
  return apiFetch(`/projects/${id}/complete`, { method: 'POST' })
}

// ── Chat (Phase 9) ──────────────────────────────────────────

export type ChatMessage = {
  id: string
  negotiation_id: string
  sender_url: string
  sender_name: string
  message: string
  message_type: 'agent' | 'owner'
  timestamp: string
}

export type ChatChannel = {
  negotiation_id: string
  their_name: string
  their_url: string
  message_count: number
  last_message: ChatMessage | null
  collaboration_summary: string
}

export async function fetchChats() {
  return apiFetch<{ chats: ChatChannel[]; chat_mode: string }>('/chats')
}

export async function fetchChatMessages(negotiationId: string) {
  return apiFetch<{ messages: ChatMessage[]; count: number }>(`/chats/${negotiationId}/messages`)
}

export async function sendOwnerMessage(negotiationId: string, message: string) {
  return apiFetch(`/chats/${negotiationId}/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
}

export async function startChat(negotiationId: string) {
  return apiFetch(`/chats/${negotiationId}/start`, { method: 'POST' })
}
