// ─── API layer for fetching real agent data ─────────────────────────────────

const isDev = import.meta.env.DEV
const OUR_REGISTRY = isDev ? '/proxy/registry' : 'https://registry.devpunks.io'
const GLOBAL_REGISTRY = isDev ? '/proxy/global' : 'https://a2aregistry.org'
const OUR_API = '/api'

export type RawSkill = {
  id: string
  name: string
  description?: string
  tags?: string[]
}

export type RegistryAgent = {
  did?: string
  url: string
  name: string
  description?: string
  status?: string
  skills?: RawSkill[]
  last_seen?: string
  author?: string
}

export type MatchData = {
  agent_url: string
  agent_name: string
  overall_score: number
  is_mutual: boolean
  description?: string
}

export type NegotiationData = {
  id: string
  their_url: string
  their_name: string
  state: string
}

export type HealthData = {
  agent: string
  skills: number
  did?: string
  discovery?: {
    discovered_agents: number
    matches: number
    peers_in_registry: number
  }
  negotiations?: {
    total: number
    active: number
    pending_approval: number
    confirmed: number
  }
}

function getToken(): string {
  return localStorage.getItem('agent_api_token') || ''
}

async function fetchJSON<T>(url: string, auth = false): Promise<T | null> {
  try {
    const headers: Record<string, string> = { 'Accept': 'application/json' }
    if (auth) {
      const token = getToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
    }
    const res = await fetch(url, { headers, signal: AbortSignal.timeout(8000) })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function fetchOurHealth(): Promise<HealthData | null> {
  return fetchJSON<HealthData>(`${OUR_API}/health`)
}

export async function fetchAllAgents(): Promise<RegistryAgent[]> {
  const [ourRegistry, globalRegistry] = await Promise.allSettled([
    fetchJSON<{ agents: RegistryAgent[] }>(`${OUR_REGISTRY}/agents`),
    fetchJSON<{ agents: any[] }>(`${GLOBAL_REGISTRY}/api/agents`),
  ])

  const agents = new Map<string, RegistryAgent>()

  // Our registry — primary source
  if (ourRegistry.status === 'fulfilled' && ourRegistry.value?.agents) {
    for (const a of ourRegistry.value.agents) {
      const url = a.url.replace(/\/+$/, '')
      agents.set(url, { ...a, url })
    }
  }

  // Global registry — add agents we don't have, merge author info
  if (globalRegistry.status === 'fulfilled' && globalRegistry.value?.agents) {
    for (const a of globalRegistry.value.agents) {
      const url = (a.url || '').replace(/\/+$/, '')
      if (!url) continue
      if (agents.has(url)) {
        // Merge author info
        const existing = agents.get(url)!
        if (a.author && !existing.author) existing.author = a.author
      } else {
        agents.set(url, {
          url,
          name: a.name || 'Unknown',
          description: a.description,
          skills: a.skills,
          status: a.is_healthy === false ? 'offline' : 'online',
          author: a.author,
        })
      }
    }
  }

  return Array.from(agents.values())
}

export async function fetchMatches(): Promise<MatchData[]> {
  const data = await fetchJSON<{ matches: MatchData[] }>(`${OUR_API}/discovery/matches`, true)
  return data?.matches || []
}

export async function fetchNegotiations(): Promise<NegotiationData[]> {
  const data = await fetchJSON<{ negotiations: NegotiationData[] }>(`${OUR_API}/negotiations`, true)
  return data?.negotiations || []
}
