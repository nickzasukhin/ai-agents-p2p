// ─── Transform raw API data into viz-ready format ────────────────────────────

import * as THREE from 'three'
import type { RegistryAgent, MatchData, NegotiationData, HealthData } from './api'

export type AgentStatus = 'online' | 'searching' | 'negotiating' | 'matched' | 'brainstorming' | 'offline'

export interface AgentNode {
  id: number
  name: string
  owner: string
  url: string
  description: string
  skills: string[]
  cluster: number
  status: AgentStatus
  position: THREE.Vector3
  color: string
  isOurAgent: boolean
  matchScore?: number
  negotiationState?: string
}

export interface Connection {
  from: number
  to: number
  status: 'searching' | 'negotiating' | 'matched' | 'brainstorming'
}

export const CLUSTERS = [
  { name: 'AI & ML', center: [-8, 3, -2], color: '#00d4ff', keywords: ['ai', 'ml', 'llm', 'nlp', 'deep learning', 'pytorch', 'tensorflow', 'computer vision', 'machine learning', 'neural', 'gpt', 'agent'] },
  { name: 'Frontend', center: [7, 5, -4], color: '#ff6b9d', keywords: ['react', 'vue', 'angular', 'css', 'ui', 'ux', 'design', 'typescript', 'next.js', 'frontend', 'web'] },
  { name: 'Backend', center: [2, -6, 3], color: '#b44aff', keywords: ['python', 'go', 'rust', 'java', 'node', 'fastapi', 'graphql', 'grpc', 'api', 'backend', 'server'] },
  { name: 'DevOps', center: [-6, -4, 5], color: '#00ff88', keywords: ['kubernetes', 'docker', 'aws', 'gcp', 'terraform', 'ci/cd', 'deploy', 'infra', 'cloud', 'devops', 'sre'] },
  { name: 'Blockchain', center: [8, -2, -6], color: '#ff6b35', keywords: ['crypto', 'defi', 'blockchain', 'web3', 'token', 'swap', 'nft', 'solidity', 'ethereum', 'wallet', 'chain'] },
  { name: 'Data', center: [-3, 6, 6], color: '#ffcc00', keywords: ['data', 'etl', 'spark', 'sql', 'analytics', 'visualization', 'statistics', 'scraping', 'research'] },
  { name: 'Security', center: [5, 1, 7], color: '#ff3366', keywords: ['security', 'crypto', 'pentesting', 'iam', 'audit', 'privacy', 'verification', 'compliance', 'claim'] },
  { name: 'Other', center: [0, -1, -7], color: '#667788', keywords: [] },
]

// Deterministic hash for stable positioning
function hashString(s: string): number {
  let hash = 0
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash + s.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

function seededRandom(seed: number) {
  let s = seed
  return () => {
    s = (s * 16807 + 0) % 2147483647
    return (s - 1) / 2147483646
  }
}

function assignCluster(agent: RegistryAgent): number {
  const text = [
    agent.name,
    agent.description,
    ...(agent.skills?.map(s => [s.name, s.description, ...(s.tags || [])].join(' ')) || []),
  ].join(' ').toLowerCase()

  let bestCluster = CLUSTERS.length - 1 // "Other" by default
  let bestScore = 0

  for (let i = 0; i < CLUSTERS.length - 1; i++) {
    let score = 0
    for (const kw of CLUSTERS[i].keywords) {
      if (text.includes(kw)) score++
    }
    if (score > bestScore) {
      bestScore = score
      bestCluster = i
    }
  }

  return bestCluster
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

export const OUR_URL = 'https://agents.devpunks.io'

export function buildVizData(
  rawAgents: RegistryAgent[],
  matches: MatchData[],
  negotiations: NegotiationData[],
  health: HealthData | null,
): { agents: AgentNode[]; connections: Connection[] } {
  const isSmall = rawAgents.length < 20
  const jitter = isSmall ? 3 : 6

  // Build match/negotiation lookup by URL
  const matchByUrl = new Map<string, MatchData>()
  for (const m of matches) {
    matchByUrl.set(m.agent_url.replace(/\/+$/, ''), m)
  }

  const negByUrl = new Map<string, NegotiationData>()
  for (const n of negotiations) {
    negByUrl.set(n.their_url.replace(/\/+$/, ''), n)
  }

  // Ensure our agent is included
  const ourUrl = OUR_URL.replace(/\/+$/, '')
  const hasOurAgent = rawAgents.some(a => a.url.replace(/\/+$/, '') === ourUrl)
  if (!hasOurAgent && health) {
    rawAgents.unshift({
      url: ourUrl,
      name: health.agent,
      description: 'Our agent',
      skills: [],
      status: 'online',
    })
  }

  // Build agent nodes
  const agents: AgentNode[] = []
  const urlToId = new Map<string, number>()

  // Our agent first (id=0)
  const sorted = [...rawAgents].sort((a, b) => {
    const aIsOur = a.url.replace(/\/+$/, '') === ourUrl ? 0 : 1
    const bIsOur = b.url.replace(/\/+$/, '') === ourUrl ? 0 : 1
    return aIsOur - bIsOur
  })

  for (const raw of sorted) {
    const url = raw.url.replace(/\/+$/, '')
    if (urlToId.has(url)) continue

    const id = agents.length
    urlToId.set(url, id)

    const isOurAgent = url === ourUrl
    const cluster = assignCluster(raw)
    const c = CLUSTERS[cluster]

    const match = matchByUrl.get(url)
    const neg = negByUrl.get(url)

    // Determine status
    let status: AgentStatus = 'online'
    if (isOurAgent) {
      status = 'online'
    } else if (neg) {
      const s = neg.state
      if (s === 'confirmed' || s === 'completed') status = 'matched'
      else if (s === 'proposing' || s === 'counter_proposing' || s === 'owner_review') status = 'negotiating'
      else status = 'negotiating'
    } else if (match) {
      status = 'searching'
    } else if (raw.status === 'offline') {
      status = 'offline'
    }

    // Position: our agent at center, others in clusters
    let position: THREE.Vector3
    if (isOurAgent) {
      position = new THREE.Vector3(0, 0, 0)
    } else {
      const hash = hashString(url)
      const rng = seededRandom(hash)
      position = new THREE.Vector3(
        c.center[0] + (rng() - 0.5) * jitter,
        c.center[1] + (rng() - 0.5) * jitter,
        c.center[2] + (rng() - 0.5) * jitter,
      )
    }

    const skillNames = raw.skills?.map(s => s.name).slice(0, 4) || []

    agents.push({
      id,
      name: raw.name || 'Unknown Agent',
      owner: raw.author || extractDomain(url),
      url,
      description: raw.description || '',
      skills: skillNames,
      cluster,
      status,
      position,
      color: c.color,
      isOurAgent,
      matchScore: match?.overall_score,
      negotiationState: neg?.state,
    })
  }

  // Build connections — only from our agent
  const connections: Connection[] = []
  const ourId = urlToId.get(ourUrl)
  if (ourId !== undefined) {
    for (const match of matches) {
      const peerId = urlToId.get(match.agent_url.replace(/\/+$/, ''))
      if (peerId === undefined) continue
      const neg = negByUrl.get(match.agent_url.replace(/\/+$/, ''))
      let connStatus: Connection['status'] = 'searching'
      if (neg) {
        const s = neg.state
        if (s === 'confirmed' || s === 'completed') connStatus = 'matched'
        else connStatus = 'negotiating'
      }
      connections.push({ from: ourId, to: peerId, status: connStatus })
    }

    // Negotiations without matches (rare but possible)
    for (const neg of negotiations) {
      const peerUrl = neg.their_url.replace(/\/+$/, '')
      if (matchByUrl.has(peerUrl)) continue // already handled
      const peerId = urlToId.get(peerUrl)
      if (peerId === undefined) continue
      const s = neg.state
      let connStatus: Connection['status'] = 'negotiating'
      if (s === 'confirmed' || s === 'completed') connStatus = 'matched'
      connections.push({ from: ourId, to: peerId, status: connStatus })
    }
  }

  return { agents, connections }
}
