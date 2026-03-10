/** Search screen — global agent search. */

import { useState } from 'react'
import { Input } from '../components/Input'
import { Button } from '../components/Button'
import { SearchResult as SearchResultCard } from '../components/SearchResult'
import { colors, spacing, fontSize } from '../theme/tokens'
import * as agentApi from '../api/agent'

export function SearchScreen() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<agentApi.SearchResult[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  async function handleSearch() {
    if (!query.trim()) return

    setLoading(true)
    setSearched(true)
    try {
      const resp = await agentApi.searchAgents(query.trim())
      setResults(resp.results)
      setTotal(resp.total)
    } catch {
      setResults([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: spacing.lg, overflow: 'auto', height: '100%' }}>
      <h1 style={{ fontSize: fontSize.xxl, fontWeight: 700, marginBottom: spacing.sm }}>
        Search Agents
      </h1>
      <p style={{ color: colors.textSecondary, fontSize: fontSize.md, marginBottom: spacing.lg }}>
        Find agents by skills, expertise, or description
      </p>

      {/* Search bar */}
      <div style={{ display: 'flex', gap: spacing.sm, marginBottom: spacing.xl }}>
        <Input
          value={query}
          onChange={setQuery}
          placeholder="e.g. Python developer, UI designer, Kubernetes..."
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          autoFocus
        />
        <Button onClick={handleSearch} loading={loading} disabled={!query.trim()}>
          Search
        </Button>
      </div>

      {/* Results */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: spacing.xxl, color: colors.textMuted, animation: 'pulse 1.5s infinite' }}>
          Searching the network...
        </div>
      ) : searched ? (
        <>
          <div style={{ color: colors.textSecondary, fontSize: fontSize.sm, marginBottom: spacing.md }}>
            {total} result{total !== 1 ? 's' : ''} for "{query}"
          </div>
          {results.length === 0 ? (
            <div style={{ textAlign: 'center', padding: spacing.xxl }}>
              <div style={{ fontSize: 48, marginBottom: spacing.md }}>🤔</div>
              <p style={{ color: colors.textSecondary }}>No agents found. Try a different search.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
              {results.map((r) => (
                <SearchResultCard
                  key={r.agent_url}
                  agentName={r.agent_name}
                  description={r.description}
                  skills={r.skills}
                  matchScore={r.match_score}
                  source={r.source}
                />
              ))}
            </div>
          )}
        </>
      ) : (
        <div style={{ textAlign: 'center', padding: spacing.xxl }}>
          <div style={{ fontSize: 64, marginBottom: spacing.md }}>🌐</div>
          <p style={{ color: colors.textMuted, fontSize: fontSize.md }}>
            Search across local agents and global registries
          </p>
        </div>
      )}
    </div>
  )
}
