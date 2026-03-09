import { useEffect, useState, useRef } from 'react'
import {
  fetchChats,
  fetchChatMessages,
  sendOwnerMessage,
  startChat,
  type ChatChannel,
  type ChatMessage,
} from '../api'
import { timeAgo } from './ErrorBoundary'

type Props = {
  wsChats?: ChatChannel[] | null
  initialChatId?: string | null
}

export default function ChatPanel({ wsChats, initialChatId }: Props) {
  const [chats, setChats] = useState<ChatChannel[]>([])
  const [chatMode, setChatMode] = useState('auto')
  const [selectedChat, setSelectedChat] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [showInput, setShowInput] = useState(false)
  const [inputText, setInputText] = useState('')
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevMsgCountRef = useRef(0)

  // Load chats
  useEffect(() => {
    fetchChats()
      .then(d => {
        setChats(d.chats || [])
        setChatMode(d.chat_mode || 'auto')
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // WS updates
  useEffect(() => {
    if (wsChats) {
      setChats(wsChats)
      setLoading(false)
    }
  }, [wsChats])

  // Auto-select chat from prop
  useEffect(() => {
    if (initialChatId && chats.some(c => c.negotiation_id === initialChatId)) {
      setSelectedChat(initialChatId)
    }
  }, [initialChatId, chats])

  // Load messages when chat selected
  useEffect(() => {
    if (!selectedChat) {
      setMessages([])
      return
    }
    prevMsgCountRef.current = 0  // reset so first load scrolls to bottom
    loadMessages(selectedChat)

    // Poll for new messages every 3s
    pollRef.current = setInterval(() => {
      loadMessages(selectedChat)
    }, 3000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [selectedChat])

  // Auto-scroll only when new messages arrive AND user is near the bottom
  useEffect(() => {
    const el = messagesContainerRef.current
    if (!el) return
    const newCount = messages.length
    const isNewMessages = newCount > prevMsgCountRef.current
    prevMsgCountRef.current = newCount
    if (!isNewMessages) return
    // Only scroll if user is near the bottom (within 100px)
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
    if (nearBottom) el.scrollTop = el.scrollHeight
  }, [messages])

  const loadMessages = (negId: string) => {
    fetchChatMessages(negId)
      .then(d => setMessages(d.messages || []))
      .catch(() => {})
  }

  const handleSend = async () => {
    if (!selectedChat || !inputText.trim()) return
    setSending(true)
    try {
      await sendOwnerMessage(selectedChat, inputText.trim())
      setInputText('')
      loadMessages(selectedChat)
    } catch {}
    setSending(false)
  }

  const handleStartChat = async (negId: string) => {
    try {
      await startChat(negId)
      setSelectedChat(negId)
      loadMessages(negId)
    } catch {}
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const selectedInfo = chats.find(c => c.negotiation_id === selectedChat)

  if (loading) {
    return (
      <div className="chat-panel animate-in">
        <div className="panel-header"><h3>Chat</h3></div>
        <div className="empty-state"><p>Loading chats...</p></div>
      </div>
    )
  }

  if (chats.length === 0) {
    return (
      <div className="chat-panel animate-in">
        <div className="panel-header"><h3>Chat</h3></div>
        <div className="empty-state">
          <p>No confirmed collaborations yet.</p>
          <p style={{ fontSize: 12, marginTop: 8 }}>
            Chats become available after negotiations are confirmed.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-panel animate-in">
      <div className="panel-header">
        <h3>Chat <span className="chat-mode-badge">{chatMode}</span></h3>
      </div>

      <div className="chat-layout">
        {/* Chat list sidebar */}
        <div className="chat-list">
          {chats.map(ch => (
            <div
              key={ch.negotiation_id}
              className={`chat-item ${selectedChat === ch.negotiation_id ? 'active' : ''}`}
              onClick={() => setSelectedChat(ch.negotiation_id)}
            >
              <div className="chat-item-name">{ch.their_name}</div>
              <div className="chat-item-preview">
                {ch.message_count > 0
                  ? (ch.last_message?.message.slice(0, 50) + (ch.last_message && ch.last_message.message.length > 50 ? '...' : ''))
                  : 'No messages yet'}
              </div>
              <div className="chat-item-meta">
                <span>{ch.message_count} msgs</span>
                {ch.last_message && <span>{timeAgo(ch.last_message.timestamp)}</span>}
              </div>
            </div>
          ))}
        </div>

        {/* Message area */}
        <div className="chat-messages-area">
          {!selectedChat ? (
            <div className="empty-state">
              <p>Select a conversation</p>
            </div>
          ) : (
            <>
              {/* Chat header */}
              <div className="chat-msg-header">
                <span className="chat-partner-name">{selectedInfo?.their_name}</span>
                {selectedInfo?.collaboration_summary && (
                  <span className="chat-summary">{selectedInfo.collaboration_summary.slice(0, 80)}</span>
                )}
              </div>

              {/* Messages */}
              <div className="chat-messages" ref={messagesContainerRef}>
                {messages.length === 0 ? (
                  <div className="empty-state">
                    <p>No messages yet.</p>
                    {chatMode === 'manual' && (
                      <button className="btn-primary" onClick={() => handleStartChat(selectedChat)}>
                        Start Conversation
                      </button>
                    )}
                  </div>
                ) : (
                  messages.map(msg => {
                    const isOurs = msg.sender_url !== selectedInfo?.their_url
                    return (
                      <div key={msg.id} className={`chat-msg ${isOurs ? 'chat-msg-ours' : 'chat-msg-theirs'}`}>
                        <div className="chat-msg-meta">
                          <span className="chat-msg-sender">
                            {isOurs ? 'You' : msg.sender_name}
                            {msg.message_type === 'agent' && <span className="chat-ai-badge">AI</span>}
                            {msg.message_type === 'owner' && <span className="chat-owner-badge">Owner</span>}
                          </span>
                          <span className="chat-msg-time">{timeAgo(msg.timestamp)}</span>
                        </div>
                        <p className="chat-msg-text">{msg.message}</p>
                      </div>
                    )
                  })
                )}
              </div>

              {/* Input area */}
              {chatMode === 'manual' ? (
                <div className="chat-input-area">
                  <textarea
                    className="chat-input"
                    placeholder="Type a message..."
                    value={inputText}
                    onChange={e => setInputText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    rows={2}
                  />
                  <button
                    className="btn-primary"
                    onClick={handleSend}
                    disabled={sending || !inputText.trim()}
                  >
                    {sending ? 'Sending...' : 'Send'}
                  </button>
                </div>
              ) : (
                /* Auto mode: subtle "Join" option */
                !showInput ? (
                  messages.length > 0 && (
                    <div className="chat-join">
                      <button className="chat-join-btn" onClick={() => setShowInput(true)}>
                        Join conversation
                      </button>
                    </div>
                  )
                ) : (
                  <div className="chat-input-area">
                    <textarea
                      className="chat-input"
                      placeholder="Ask a question..."
                      value={inputText}
                      onChange={e => setInputText(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={2}
                      autoFocus
                    />
                    <div className="chat-input-actions">
                      <button
                        className="btn-primary"
                        onClick={handleSend}
                        disabled={sending || !inputText.trim()}
                      >
                        {sending ? 'Sending...' : 'Send'}
                      </button>
                      <button className="btn-outline" onClick={() => { setShowInput(false); setInputText('') }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )
              )}
            </>
          )}
        </div>
      </div>

      <style>{`
        .chat-panel {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
        }
        .chat-mode-badge {
          font-size: 11px;
          color: var(--text-muted);
          background: var(--bg-secondary);
          padding: 2px 8px;
          border-radius: 10px;
          margin-left: 8px;
          font-weight: 400;
          text-transform: uppercase;
        }
        .chat-layout {
          display: grid;
          grid-template-columns: 200px 1fr;
          gap: 16px;
          min-height: 400px;
          margin-top: 12px;
        }
        /* Chat list */
        .chat-list {
          border-right: 1px solid var(--border);
          padding-right: 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          overflow-y: auto;
          max-height: 500px;
        }
        .chat-item {
          padding: 10px 12px;
          border-radius: var(--radius-sm);
          cursor: pointer;
          transition: background 0.15s;
        }
        .chat-item:hover { background: var(--bg-secondary); }
        .chat-item.active {
          background: rgba(108,92,231,0.1);
          border-left: 3px solid var(--accent);
        }
        .chat-item-name {
          font-weight: 600;
          font-size: 13px;
          margin-bottom: 2px;
        }
        .chat-item-preview {
          font-size: 11px;
          color: var(--text-muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .chat-item-meta {
          font-size: 10px;
          color: var(--text-muted);
          display: flex;
          justify-content: space-between;
          margin-top: 4px;
        }
        /* Messages area */
        .chat-messages-area {
          display: flex;
          flex-direction: column;
          min-height: 0;
        }
        .chat-msg-header {
          padding-bottom: 10px;
          border-bottom: 1px solid var(--border);
          margin-bottom: 12px;
        }
        .chat-partner-name {
          font-weight: 700;
          font-size: 15px;
        }
        .chat-summary {
          display: block;
          font-size: 12px;
          color: var(--success);
          margin-top: 4px;
        }
        .chat-messages {
          flex: 1;
          overflow-y: auto;
          max-height: 360px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding-right: 4px;
        }
        .chat-msg {
          padding: 10px 14px;
          border-radius: var(--radius-sm);
          font-size: 13px;
          max-width: 85%;
        }
        .chat-msg-ours {
          background: rgba(108,92,231,0.08);
          border-left: 3px solid var(--accent);
          align-self: flex-end;
        }
        .chat-msg-theirs {
          background: rgba(0,206,201,0.05);
          border-left: 3px solid var(--success);
          align-self: flex-start;
        }
        .chat-msg-meta {
          display: flex;
          justify-content: space-between;
          margin-bottom: 4px;
        }
        .chat-msg-sender {
          font-weight: 600;
          font-size: 11px;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .chat-ai-badge {
          font-size: 9px;
          background: var(--bg-secondary);
          color: var(--text-muted);
          padding: 1px 5px;
          border-radius: 6px;
          font-weight: 400;
        }
        .chat-owner-badge {
          font-size: 9px;
          background: rgba(108,92,231,0.15);
          color: var(--accent-light);
          padding: 1px 5px;
          border-radius: 6px;
          font-weight: 400;
        }
        .chat-msg-time {
          font-size: 10px;
          color: var(--text-muted);
        }
        .chat-msg-text {
          color: var(--text-secondary);
          line-height: 1.5;
          white-space: pre-wrap;
        }
        /* Join button */
        .chat-join {
          text-align: center;
          padding: 8px 0;
          border-top: 1px solid var(--border);
          margin-top: 8px;
        }
        .chat-join-btn {
          background: none;
          border: none;
          color: var(--text-muted);
          font-size: 12px;
          cursor: pointer;
          opacity: 0.7;
          transition: opacity 0.2s;
        }
        .chat-join-btn:hover {
          opacity: 1;
          color: var(--accent-light);
        }
        /* Input */
        .chat-input-area {
          border-top: 1px solid var(--border);
          padding-top: 12px;
          margin-top: 8px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .chat-input {
          width: 100%;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          padding: 10px 12px;
          color: var(--text-primary);
          font-size: 13px;
          resize: none;
          font-family: inherit;
        }
        .chat-input:focus {
          outline: none;
          border-color: var(--accent);
        }
        .chat-input-actions {
          display: flex;
          gap: 8px;
        }
        .empty-state {
          text-align: center;
          padding: 32px;
          color: var(--text-muted);
        }
        @media (max-width: 700px) {
          .chat-layout {
            grid-template-columns: 1fr;
          }
          .chat-list {
            border-right: none;
            border-bottom: 1px solid var(--border);
            padding-right: 0;
            padding-bottom: 12px;
            max-height: 150px;
          }
        }
      `}</style>
    </div>
  )
}
