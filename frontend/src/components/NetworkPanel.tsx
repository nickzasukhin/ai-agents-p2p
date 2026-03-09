import { useEffect, useState } from 'react'
import {
  fetchNetworkStatus,
  fetchDiscoveryStatus,
  fetchGossipPeers,
  fetchGossipStats,
  fetchDhtStats,
  checkNetworkReachability,
  type NetworkStatus,
  type DiscoveryStatus,
  type GossipPeer,
} from '../api'
import { Skeleton, timeAgo } from './ErrorBoundary'

type DhtStats = {
  is_running: boolean
  udp_port: number
  cached_peers: number
  node_id?: string
}

type GossipStats = {
  rounds: number
  peers_learned: number
  known_peers: number
}

export default function NetworkPanel() {
  const [network, setNetwork] = useState<NetworkStatus | null>(null)
  const [discovery, setDiscovery] = useState<DiscoveryStatus | null>(null)
  const [gossipPeers, setGossipPeers] = useState<GossipPeer[]>([])
  const [gossipStats, setGossipStats] = useState<GossipStats | null>(null)
  const [dht, setDht] = useState<DhtStats | null>(null)
  const [checking, setChecking] = useState(false)
  const [reachResult, setReachResult] = useState<{ reachable: boolean; latency_ms: number } | null>(null)
  const [loading, setLoading] = useState(true)

  const loadAll = async () => {
    try {
      const [net, disc, gPeers, gStats, dhtS] = await Promise.all([
        fetchNetworkStatus().catch(() => null),
        fetchDiscoveryStatus().catch(() => null),
        fetchGossipPeers().catch(() => []),
        fetchGossipStats().catch(() => null),
        fetchDhtStats().catch(() => null),
      ])
      if (net) setNetwork(net)
      if (disc) setDiscovery(disc)
      setGossipPeers(Array.isArray(gPeers) ? gPeers : (gPeers as any)?.peers || [])
      if (gStats && !(gStats as any).error) setGossipStats(gStats as any)
      if (dhtS && !(dhtS as any).error) setDht(dhtS as any)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
    const iv = setInterval(loadAll, 10000)
    return () => clearInterval(iv)
  }, [])

  const handleCheck = async () => {
    setChecking(true)
    setReachResult(null)
    try {
      const result = await checkNetworkReachability()
      setReachResult({ reachable: result.reachable, latency_ms: result.latency_ms })
    } catch {
      setReachResult({ reachable: false, latency_ms: 0 })
    }
    setChecking(false)
  }

  if (loading) {
    return (
      <div className="net-panel animate-in">
        <h3>Network</h3>
        <Skeleton cards={3} />
      </div>
    )
  }

  return (
    <div className="net-panel animate-in">
      {/* Network Config */}
      <div className="net-section">
        <h4>Network Configuration</h4>
        <div className="net-grid">
          <div className="net-item">
            <span className="net-label">External URL</span>
            <span className="net-value mono">{network?.external_url || 'unknown'}</span>
          </div>
          <div className="net-item">
            <span className="net-label">NAT Type</span>
            <span className="net-value">
              <span className={`net-dot ${network?.nat_type === 'none' ? 'green' : 'yellow'}`} />
              {network?.nat_type || 'unknown'}
            </span>
          </div>
          <div className="net-item">
            <span className="net-label">Relay</span>
            <span className="net-value">
              <span className={`net-dot ${network?.relay_enabled ? 'green' : 'off'}`} />
              {network?.relay_enabled ? 'enabled' : 'disabled'}
            </span>
          </div>
          {network?.relay_url && (
            <div className="net-item">
              <span className="net-label">Relay URL</span>
              <span className="net-value mono">{network.relay_url}</span>
            </div>
          )}
        </div>
        <div className="net-reach-row">
          <button className="btn-outline" onClick={handleCheck} disabled={checking}>
            {checking ? 'Checking...' : 'Check Reachability'}
          </button>
          {reachResult && (
            <span className={`net-reach-result ${reachResult.reachable ? 'reachable' : 'unreachable'}`}>
              {reachResult.reachable
                ? `Reachable (${reachResult.latency_ms}ms)`
                : 'Unreachable'}
            </span>
          )}
        </div>
      </div>

      {/* Discovery Status */}
      <div className="net-section">
        <h4>Discovery</h4>
        <div className="net-stats">
          <div className="net-stat">
            <span className="net-stat-value">{discovery?.runs_completed ?? 0}</span>
            <span className="net-stat-label">Runs</span>
          </div>
          <div className="net-stat">
            <span className="net-stat-value">{discovery?.discovered_agents ?? 0}</span>
            <span className="net-stat-label">Agents</span>
          </div>
          <div className="net-stat">
            <span className="net-stat-value">{discovery?.matches ?? 0}</span>
            <span className="net-stat-label">Matches</span>
          </div>
          <div className="net-stat">
            <span className="net-stat-value">
              <span className={`net-dot ${discovery?.is_running ? 'green' : 'off'}`} />
            </span>
            <span className="net-stat-label">{discovery?.is_running ? 'Running' : 'Idle'}</span>
          </div>
        </div>
      </div>

      {/* Gossip Protocol */}
      <div className="net-section">
        <h4>Gossip Protocol</h4>
        <div className="net-stats">
          <div className="net-stat">
            <span className="net-stat-value">{gossipStats?.known_peers ?? 0}</span>
            <span className="net-stat-label">Peers</span>
          </div>
          <div className="net-stat">
            <span className="net-stat-value">{gossipStats?.rounds ?? 0}</span>
            <span className="net-stat-label">Rounds</span>
          </div>
          <div className="net-stat">
            <span className="net-stat-value">{gossipStats?.peers_learned ?? 0}</span>
            <span className="net-stat-label">Learned</span>
          </div>
        </div>
        {gossipPeers.length > 0 && (
          <div className="net-peer-list">
            {gossipPeers.slice(0, 10).map((p, i) => (
              <div key={i} className="net-peer stagger-item">
                <span className="net-peer-name">{p.name || p.url}</span>
                <span className="net-peer-seen">{timeAgo(p.last_seen)}</span>
              </div>
            ))}
            {gossipPeers.length > 10 && (
              <div className="net-peer-more">+{gossipPeers.length - 10} more peers</div>
            )}
          </div>
        )}
      </div>

      {/* DHT Node */}
      <div className="net-section">
        <h4>DHT Node</h4>
        <div className="net-grid">
          <div className="net-item">
            <span className="net-label">Status</span>
            <span className="net-value">
              <span className={`net-dot ${dht?.is_running ? 'green' : 'off'}`} />
              {dht?.is_running ? 'Running' : 'Offline'}
            </span>
          </div>
          {dht?.udp_port && (
            <div className="net-item">
              <span className="net-label">UDP Port</span>
              <span className="net-value mono">{dht.udp_port}</span>
            </div>
          )}
          <div className="net-item">
            <span className="net-label">Cached Peers</span>
            <span className="net-value">{dht?.cached_peers ?? 0}</span>
          </div>
        </div>
      </div>

      <style>{`
        .net-panel {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .net-section {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
        }
        .net-section h4 {
          font-size: 14px;
          color: var(--text-secondary);
          margin-bottom: 14px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-weight: 600;
        }
        .net-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .net-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .net-label {
          font-size: 11px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .net-value {
          font-size: 14px;
          color: var(--text-primary);
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .net-value.mono {
          font-family: 'JetBrains Mono', monospace;
          font-size: 12px;
          word-break: break-all;
        }
        .net-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .net-dot.green {
          background: var(--success);
          box-shadow: 0 0 6px rgba(0,206,201,0.4);
        }
        .net-dot.yellow {
          background: var(--warning);
          box-shadow: 0 0 6px rgba(253,203,110,0.4);
        }
        .net-dot.off {
          background: var(--text-muted);
        }
        .net-stats {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
        }
        .net-stat {
          flex: 1;
          min-width: 60px;
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 12px 8px;
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
        }
        .net-stat-value {
          font-size: 22px;
          font-weight: 700;
          color: var(--accent-light);
          display: flex;
          align-items: center;
        }
        .net-stat-label {
          font-size: 11px;
          color: var(--text-muted);
          text-transform: uppercase;
          margin-top: 4px;
        }
        .net-reach-row {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-top: 14px;
        }
        .net-reach-result {
          font-size: 13px;
          font-weight: 500;
          padding: 4px 12px;
          border-radius: 20px;
        }
        .net-reach-result.reachable {
          color: var(--success);
          background: rgba(0,206,201,0.1);
        }
        .net-reach-result.unreachable {
          color: var(--danger);
          background: rgba(255,107,107,0.1);
        }
        .net-peer-list {
          margin-top: 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .net-peer {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px 10px;
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
          font-size: 13px;
        }
        .net-peer-name {
          color: var(--text-primary);
          font-weight: 500;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 70%;
        }
        .net-peer-seen {
          color: var(--text-muted);
          font-size: 11px;
          white-space: nowrap;
        }
        .net-peer-more {
          font-size: 12px;
          color: var(--text-muted);
          text-align: center;
          padding: 4px;
        }
        @media (max-width: 600px) {
          .net-grid { grid-template-columns: 1fr; }
          .net-stats { flex-direction: column; }
        }
      `}</style>
    </div>
  )
}
