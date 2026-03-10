/** Chat screen — messaging with connected agents. */

import { useState, useEffect, useRef } from 'react'
import { Card } from '../components/Card'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { ChatBubble } from '../components/ChatBubble'
import { colors, spacing, fontSize, radius } from '../theme/tokens'
import * as agentApi from '../api/agent'

export function ChatScreen() {
  const [chats, setChats] = useState<Record<string, agentApi.ChatMessage[]>>({})
  const [selectedPeer, setSelectedPeer] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadChats()
    const interval = setInterval(loadChats, 5000) // Poll for new messages
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [selectedPeer, chats])

  async function loadChats() {
    try {
      const resp = await agentApi.getChats()
      setChats(resp.chats || {})
    } catch {} finally {
      setLoading(false)
    }
  }

  async function handleSend() {
    if (!input.trim() || !selectedPeer) return
    const text = input.trim()
    setInput('')
    try {
      await agentApi.sendChat(selectedPeer, text)
      loadChats()
    } catch {}
  }

  const peerUrls = Object.keys(chats)
  const peerName = (url: string) => {
    try { return new URL(url).hostname } catch { return url.slice(0, 30) }
  }
  const selectedMessages = selectedPeer ? (chats[selectedPeer] || []) : []

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ color: colors.textMuted, animation: 'pulse 1.5s infinite' }}>Loading chats...</div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Peer list (sidebar) */}
      <div style={{
        width: 260, borderRight: `1px solid ${colors.border}`,
        overflow: 'auto', flexShrink: 0,
        display: peerUrls.length > 0 ? 'block' : 'none',
      }}>
        <div style={{ padding: spacing.md }}>
          <h2 style={{ fontSize: fontSize.md, fontWeight: 600, marginBottom: spacing.md }}>Chats</h2>
        </div>
        {peerUrls.map((url) => {
          const msgs = chats[url]
          const lastMsg = msgs[msgs.length - 1]
          const isSelected = url === selectedPeer
          return (
            <div
              key={url}
              onClick={() => setSelectedPeer(url)}
              style={{
                padding: `${spacing.sm}px ${spacing.md}px`,
                cursor: 'pointer',
                background: isSelected ? colors.bgCard : 'transparent',
                borderLeft: isSelected ? `2px solid ${colors.accent}` : '2px solid transparent',
                transition: 'all 0.1s',
              }}
            >
              <div style={{ fontSize: fontSize.sm, fontWeight: 600, marginBottom: 2 }}>
                {peerName(url)}
              </div>
              {lastMsg && (
                <div style={{ fontSize: fontSize.xs, color: colors.textMuted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {lastMsg.content.slice(0, 50)}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Chat area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {selectedPeer ? (
          <>
            {/* Chat header */}
            <div style={{
              padding: `${spacing.sm}px ${spacing.lg}px`,
              borderBottom: `1px solid ${colors.border}`,
              display: 'flex', alignItems: 'center',
            }}>
              <h3 style={{ fontSize: fontSize.md, fontWeight: 600 }}>{peerName(selectedPeer)}</h3>
            </div>

            {/* Messages */}
            <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', padding: spacing.md }}>
              {selectedMessages.map((m) => (
                <ChatBubble
                  key={m.id}
                  content={m.content}
                  isOwn={m.direction === 'outbound'}
                  timestamp={m.timestamp}
                />
              ))}
            </div>

            {/* Input */}
            <div style={{
              padding: spacing.md, borderTop: `1px solid ${colors.border}`,
              display: 'flex', gap: spacing.sm,
            }}>
              <Input
                value={input}
                onChange={setInput}
                placeholder="Type a message..."
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                autoFocus
              />
              <Button onClick={handleSend} small disabled={!input.trim()}>Send</Button>
            </div>
          </>
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 64, marginBottom: spacing.md }}>💬</div>
              <h3 style={{ fontSize: fontSize.lg, marginBottom: spacing.sm }}>
                {peerUrls.length > 0 ? 'Select a conversation' : 'No chats yet'}
              </h3>
              <p style={{ color: colors.textSecondary, fontSize: fontSize.sm }}>
                {peerUrls.length > 0
                  ? 'Choose a peer from the sidebar'
                  : 'Negotiate with matches to start chatting'}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
