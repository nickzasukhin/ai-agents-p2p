/** Profile screen — agent card, invite link, settings. */

import { useState, useEffect } from 'react'
import { Card } from '../components/Card'
import { Button } from '../components/Button'
import { Badge } from '../components/Badge'
import { Logo } from '../components/Logo'
import { colors, spacing, fontSize, radius } from '../theme/tokens'
import * as agentApi from '../api/agent'
import * as orchApi from '../api/orchestrator'

interface ProfileScreenProps {
  onLogout: () => void
}

export function ProfileScreen({ onLogout }: ProfileScreenProps) {
  const [inviteData, setInviteData] = useState<agentApi.InviteData | null>(null)
  const [userInfo, setUserInfo] = useState<orchApi.UserInfo | null>(null)
  const [onlineStatus, setOnlineStatus] = useState<agentApi.OnlineStatus | null>(null)
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    try {
      const [invite, user, status] = await Promise.allSettled([
        agentApi.getInviteData(),
        orchApi.getMe(),
        agentApi.getOnlineStatus(),
      ])
      if (invite.status === 'fulfilled') setInviteData(invite.value)
      if (user.status === 'fulfilled') setUserInfo(user.value)
      if (status.status === 'fulfilled') setOnlineStatus(status.value)
    } finally {
      setLoading(false)
    }
  }

  function copyInviteLink() {
    const url = inviteData?.agent_url ? `${inviteData.agent_url}/invite` : ''
    navigator.clipboard.writeText(url)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function handleLogout() {
    await orchApi.logout()
    onLogout()
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ color: colors.textMuted, animation: 'pulse 1.5s infinite' }}>Loading...</div>
      </div>
    )
  }

  return (
    <div style={{ padding: spacing.lg, overflow: 'auto', height: '100%', maxWidth: 600, margin: '0 auto' }}>
      {/* Agent Card */}
      <Card style={{ marginBottom: spacing.lg }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md, marginBottom: spacing.lg }}>
          <div style={{
            width: 56, height: 56, borderRadius: radius.lg,
            background: colors.accentMuted, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            fontSize: 24, fontWeight: 700, color: colors.accent,
          }}>
            {(inviteData?.agent_name || '?')[0]}
          </div>
          <div>
            <h2 style={{ fontSize: fontSize.xl, fontWeight: 700, margin: 0 }}>
              {inviteData?.agent_name || 'My Agent'}
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, marginTop: 4 }}>
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: onlineStatus?.is_online ? colors.success : colors.textMuted,
              }} />
              <span style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>
                {onlineStatus?.is_online ? 'Online' : 'Offline'}
              </span>
            </div>
          </div>
        </div>

        {inviteData?.description && (
          <p style={{ color: colors.textSecondary, fontSize: fontSize.md, lineHeight: 1.6, marginBottom: spacing.md }}>
            {inviteData.description}
          </p>
        )}

        {inviteData?.skills && inviteData.skills.length > 0 && (
          <div style={{ marginBottom: spacing.md }}>
            <div style={{ color: colors.textMuted, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.xs }}>Skills</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.xs }}>
              {inviteData.skills.map((s: any, i) => (
                <Badge key={i} variant="accent">{typeof s === 'string' ? s : s.name || String(s)}</Badge>
              ))}
            </div>
          </div>
        )}

        {inviteData?.did && (
          <div style={{ marginTop: spacing.md, padding: spacing.sm, background: colors.bgPrimary, borderRadius: radius.sm }}>
            <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginBottom: 2 }}>DID</div>
            <div style={{ fontSize: fontSize.xs, color: colors.textSecondary, wordBreak: 'break-all', fontFamily: 'monospace' }}>
              {inviteData.did}
            </div>
          </div>
        )}
      </Card>

      {/* Invite Link */}
      <Card style={{ marginBottom: spacing.lg }}>
        <h3 style={{ fontSize: fontSize.md, fontWeight: 600, marginBottom: spacing.sm }}>Share Invite Link</h3>
        <p style={{ color: colors.textSecondary, fontSize: fontSize.sm, marginBottom: spacing.md }}>
          Share your invite link to let others discover and connect with your agent.
        </p>
        <Button onClick={copyInviteLink} fullWidth variant="secondary">
          {copied ? '✓ Copied!' : '📋 Copy Invite Link'}
        </Button>
      </Card>

      {/* Account Info */}
      <Card style={{ marginBottom: spacing.lg }}>
        <h3 style={{ fontSize: fontSize.md, fontWeight: 600, marginBottom: spacing.md }}>Account</h3>

        <div style={{ display: 'grid', gap: spacing.sm }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: colors.textMuted, fontSize: fontSize.sm }}>Email</span>
            <span style={{ fontSize: fontSize.sm }}>{userInfo?.email}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: colors.textMuted, fontSize: fontSize.sm }}>Agent URL</span>
            {userInfo?.agent_url ? (
              <a href={userInfo.agent_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: fontSize.sm, color: colors.accent, textDecoration: 'none' }}>
                {userInfo.agent_url.replace('https://', '')}
              </a>
            ) : (
              <span style={{ fontSize: fontSize.sm, color: colors.textMuted }}>—</span>
            )}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: colors.textMuted, fontSize: fontSize.sm }}>Status</span>
            <Badge variant={userInfo?.agent_status === 'running' ? 'success' : 'warning'}>
              {userInfo?.agent_status || 'unknown'}
            </Badge>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: colors.textMuted, fontSize: fontSize.sm }}>Tunnel</span>
            <span style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>
              {onlineStatus?.tunnel_provider || 'none'}
            </span>
          </div>
        </div>
      </Card>

      {/* Logout */}
      <Button variant="danger" fullWidth onClick={handleLogout}>
        Sign Out
      </Button>
    </div>
  )
}
