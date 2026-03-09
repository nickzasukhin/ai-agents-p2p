import { useRef, useMemo, useState, useCallback, useEffect } from 'react'
import { Canvas, useFrame, useThree, ThreeEvent } from '@react-three/fiber'
import { OrbitControls, Trail } from '@react-three/drei'
import { EffectComposer, Bloom, ChromaticAberration } from '@react-three/postprocessing'
import * as THREE from 'three'
import { motion, AnimatePresence } from 'framer-motion'
import { fetchAllAgents, fetchMatches, fetchNegotiations, fetchOurHealth } from './api'
import { buildVizData, CLUSTERS, type AgentNode, type Connection, type AgentStatus } from './dataMapper'

// ─── Constants ───────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<AgentStatus, { color: string; emissive: number; label: string }> = {
  online:        { color: '#667788', emissive: 0.3, label: 'Online' },
  searching:     { color: '#00d4ff', emissive: 0.8, label: 'Searching' },
  negotiating:   { color: '#b44aff', emissive: 1.0, label: 'Negotiating' },
  matched:       { color: '#00ff88', emissive: 1.2, label: 'Matched' },
  brainstorming: { color: '#ffcc00', emissive: 1.5, label: 'Brainstorming' },
  offline:       { color: '#222233', emissive: 0.05, label: 'Offline' },
}

const CONNECTION_COLORS: Record<Connection['status'], string> = {
  searching: '#00d4ff',
  negotiating: '#b44aff',
  matched: '#00ff88',
  brainstorming: '#ffcc00',
}

// ─── Instanced Agent Spheres ─────────────────────────────────────────────────

function InstancedAgents({
  agents,
  onSelect,
}: {
  agents: AgentNode[]
  onSelect: (agent: AgentNode) => void
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const glowRef = useRef<THREE.InstancedMesh>(null!)
  const shieldRef = useRef<THREE.InstancedMesh>(null!)

  const dummy = useMemo(() => new THREE.Object3D(), [])
  const colorArr = useMemo(() => new Float32Array(agents.length * 3), [agents.length])
  const glowColorArr = useMemo(() => new Float32Array(agents.length * 3), [agents.length])

  useEffect(() => {
    if (agents.length === 0) return
    agents.forEach((agent, i) => {
      dummy.position.copy(agent.position)
      const baseScale = agent.isOurAgent ? 0.6 : (agent.status === 'offline' ? 0.2 : 0.35)
      dummy.scale.setScalar(baseScale)
      dummy.updateMatrix()
      meshRef.current.setMatrixAt(i, dummy.matrix)
      glowRef.current.setMatrixAt(i, dummy.matrix)

      dummy.scale.setScalar(agent.isOurAgent ? 1.2 : (agent.status === 'offline' ? 0.3 : 0.7))
      dummy.updateMatrix()
      shieldRef.current.setMatrixAt(i, dummy.matrix)

      // Main sphere: cluster color (our agent gets special teal)
      const c = new THREE.Color(agent.isOurAgent ? '#00ffcc' : agent.color)
      if (agent.status === 'offline') c.multiplyScalar(0.3)
      colorArr[i * 3] = c.r
      colorArr[i * 3 + 1] = c.g
      colorArr[i * 3 + 2] = c.b

      // Glow: same cluster color
      const gc = new THREE.Color(agent.isOurAgent ? '#00ffcc' : agent.color)
      if (agent.status === 'offline') gc.multiplyScalar(0.2)
      glowColorArr[i * 3] = gc.r
      glowColorArr[i * 3 + 1] = gc.g
      glowColorArr[i * 3 + 2] = gc.b
    })
    meshRef.current.instanceMatrix.needsUpdate = true
    glowRef.current.instanceMatrix.needsUpdate = true
    shieldRef.current.instanceMatrix.needsUpdate = true
  }, [agents, dummy, colorArr, glowColorArr])

  useFrame((state) => {
    if (agents.length === 0) return
    const t = state.clock.elapsedTime
    agents.forEach((agent, i) => {
      dummy.position.copy(agent.position)

      let scale = 0.35
      if (agent.isOurAgent) {
        scale = 0.6 + Math.sin(t * 2) * 0.05
      } else if (agent.status === 'offline') scale = 0.2
      else if (agent.status === 'searching') scale = 0.35 + Math.sin(t * 3 + i) * 0.03
      else if (agent.status === 'negotiating') scale = 0.38 + Math.sin(t * 4 + i * 0.5) * 0.04
      else if (agent.status === 'matched') scale = 0.4 + Math.sin(t * 2 + i) * 0.02
      else if (agent.status === 'brainstorming') scale = 0.42 + Math.sin(t * 5 + i * 0.3) * 0.05
      else scale = 0.33 + Math.sin(t * 1.5 + i * 0.7) * 0.02

      dummy.scale.setScalar(scale)
      dummy.updateMatrix()
      meshRef.current.setMatrixAt(i, dummy.matrix)

      dummy.scale.setScalar(scale * (agent.isOurAgent ? 3.0 : 2.2))
      dummy.updateMatrix()
      glowRef.current.setMatrixAt(i, dummy.matrix)

      const shieldScale = agent.isOurAgent
        ? 1.2 + Math.sin(t * 1.5) * 0.1
        : (agent.status === 'offline' ? 0.3 : 0.7 + Math.sin(t + i) * 0.05)
      dummy.scale.setScalar(shieldScale)
      dummy.rotation.set(t * 0.2 + i, t * 0.3 + i * 0.5, 0)
      dummy.updateMatrix()
      shieldRef.current.setMatrixAt(i, dummy.matrix)
    })
    meshRef.current.instanceMatrix.needsUpdate = true
    glowRef.current.instanceMatrix.needsUpdate = true
    shieldRef.current.instanceMatrix.needsUpdate = true
  })

  const handleClick = useCallback((e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    if (e.instanceId !== undefined && e.instanceId < agents.length) {
      onSelect(agents[e.instanceId])
    }
  }, [agents, onSelect])

  if (agents.length === 0) return null

  return (
    <>
      <instancedMesh ref={shieldRef} args={[undefined, undefined, agents.length]} raycast={() => {}}>
        <icosahedronGeometry args={[1, 1]} />
        <meshStandardMaterial
          wireframe
          transparent
          opacity={0.06}
          color="#4488aa"
          emissive="#4488aa"
          emissiveIntensity={0.15}
        />
      </instancedMesh>

      <instancedMesh ref={glowRef} args={[undefined, undefined, agents.length]} raycast={() => {}}>
        <sphereGeometry args={[1, 16, 16]} />
        <meshBasicMaterial vertexColors transparent opacity={0.06} />
        <instancedBufferAttribute
          attach="geometry-attributes-color"
          args={[glowColorArr, 3]}
        />
      </instancedMesh>

      <instancedMesh
        ref={meshRef}
        args={[undefined, undefined, agents.length]}
        onClick={handleClick}
      >
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial vertexColors />
        <instancedBufferAttribute
          attach="geometry-attributes-color"
          args={[colorArr, 3]}
        />
      </instancedMesh>
    </>
  )
}

// ─── "YOU" Label for our agent ───────────────────────────────────────────────

function OurAgentLabel({ position }: { position: THREE.Vector3 }) {
  const ref = useRef<THREE.Sprite>(null!)
  const textureRef = useRef<THREE.CanvasTexture | null>(null)

  useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 128
    canvas.height = 48
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, 128, 48)
    ctx.font = 'bold 28px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#00ffcc'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('YOU', 64, 24)
    textureRef.current = new THREE.CanvasTexture(canvas)
  }, [])

  return (
    <sprite ref={ref} position={[position.x, position.y + 1.5, position.z]} scale={[2, 0.75, 1]}>
      <spriteMaterial map={textureRef.current} transparent opacity={0.9} depthWrite={false} />
    </sprite>
  )
}

// ─── Connection Lines (batched) ──────────────────────────────────────────────

function ConnectionLines({ connections, agents }: { connections: Connection[]; agents: AgentNode[] }) {
  const groupRef = useRef<THREE.Group>(null!)

  const geometries = useMemo(() => {
    const groups: Record<Connection['status'], THREE.Vector3[][]> = {
      searching: [],
      negotiating: [],
      matched: [],
      brainstorming: [],
    }

    connections.forEach(conn => {
      if (conn.from >= agents.length || conn.to >= agents.length) return
      const from = agents[conn.from].position
      const to = agents[conn.to].position
      const mid = new THREE.Vector3(
        (from.x + to.x) / 2,
        (from.y + to.y) / 2 + 1.5,
        (from.z + to.z) / 2
      )
      const curve = new THREE.QuadraticBezierCurve3(from, mid, to)
      groups[conn.status].push(curve.getPoints(20))
    })

    const buildGeo = (pointSets: THREE.Vector3[][]) => {
      const positions: number[] = []
      pointSets.forEach(pts => {
        for (let i = 0; i < pts.length - 1; i++) {
          positions.push(pts[i].x, pts[i].y, pts[i].z)
          positions.push(pts[i + 1].x, pts[i + 1].y, pts[i + 1].z)
        }
      })
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
      return geo
    }

    return {
      searchingGeo: buildGeo(groups.searching),
      negotiatingGeo: buildGeo(groups.negotiating),
      matchedGeo: buildGeo(groups.matched),
      brainstormingGeo: buildGeo(groups.brainstorming),
    }
  }, [connections, agents])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    if (groupRef.current) {
      groupRef.current.children.forEach(child => {
        const mat = (child as THREE.LineSegments).material as THREE.LineBasicMaterial
        if (mat.userData?.type === 'matched') {
          mat.opacity = 0.4 + Math.sin(t * 3) * 0.3
        } else if (mat.userData?.type === 'brainstorming') {
          mat.opacity = 0.3 + Math.sin(t * 5) * 0.25
        }
      })
    }
  })

  return (
    <group ref={groupRef}>
      <lineSegments geometry={geometries.searchingGeo}>
        <lineBasicMaterial color="#00d4ff" transparent opacity={0.15} userData={{ type: 'searching' }} />
      </lineSegments>
      <lineSegments geometry={geometries.negotiatingGeo}>
        <lineBasicMaterial color="#b44aff" transparent opacity={0.35} userData={{ type: 'negotiating' }} />
      </lineSegments>
      <lineSegments geometry={geometries.matchedGeo}>
        <lineBasicMaterial color="#00ff88" transparent opacity={0.5} userData={{ type: 'matched' }} />
      </lineSegments>
      <lineSegments geometry={geometries.brainstormingGeo}>
        <lineBasicMaterial color="#ffcc00" transparent opacity={0.4} userData={{ type: 'brainstorming' }} />
      </lineSegments>
    </group>
  )
}

// ─── Flying Cards ────────────────────────────────────────────────────────────

function FlyingCard({ from, to, color, speed = 1 }: {
  from: THREE.Vector3; to: THREE.Vector3; color: string; speed?: number
}) {
  const ref = useRef<THREE.Group>(null!)
  const progress = useRef(Math.random())

  useFrame((_, delta) => {
    progress.current = (progress.current + delta * speed * 0.25) % 1
    const t = progress.current
    const mid = new THREE.Vector3(
      (from.x + to.x) / 2 + Math.sin(t * Math.PI) * 2,
      (from.y + to.y) / 2 + Math.sin(t * Math.PI) * 3,
      (from.z + to.z) / 2 + Math.cos(t * Math.PI) * 2,
    )
    const x = (1 - t) * (1 - t) * from.x + 2 * (1 - t) * t * mid.x + t * t * to.x
    const y = (1 - t) * (1 - t) * from.y + 2 * (1 - t) * t * mid.y + t * t * to.y
    const z = (1 - t) * (1 - t) * from.z + 2 * (1 - t) * t * mid.z + t * t * to.z
    ref.current.position.set(x, y, z)
    ref.current.rotation.y += delta * 3
  })

  return (
    <group ref={ref}>
      <Trail width={0.2} length={5} color={color} attenuation={(t) => t * t}>
        <mesh>
          <boxGeometry args={[0.12, 0.16, 0.02]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={4} transparent opacity={0.9} />
        </mesh>
      </Trail>
    </group>
  )
}

function FlyingCards({ connections, agents }: { connections: Connection[]; agents: AgentNode[] }) {
  const activeConns = useMemo(() => {
    const important = connections.filter(c => c.status === 'matched' || c.status === 'brainstorming')
    const negotiating = connections.filter(c => c.status === 'negotiating').slice(0, 8)
    return [...important, ...negotiating].slice(0, 20)
  }, [connections])

  return (
    <>
      {activeConns.map((conn, i) => {
        if (conn.from >= agents.length || conn.to >= agents.length) return null
        return (
          <FlyingCard
            key={i}
            from={agents[conn.from].position}
            to={agents[conn.to].position}
            color={CONNECTION_COLORS[conn.status]}
            speed={conn.status === 'brainstorming' ? 1.8 : conn.status === 'matched' ? 1.4 : 1}
          />
        )
      })}
    </>
  )
}

// ─── Cluster Labels ──────────────────────────────────────────────────────────

function ClusterLabel({ name, position, color }: { name: string; position: [number, number, number]; color: string }) {
  const ref = useRef<THREE.Sprite>(null!)
  const textureRef = useRef<THREE.CanvasTexture | null>(null)

  useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 256
    canvas.height = 64
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, 256, 64)
    ctx.font = 'bold 24px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = color
    ctx.globalAlpha = 0.5
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(name, 128, 32)
    textureRef.current = new THREE.CanvasTexture(canvas)
  }, [name, color])

  return (
    <sprite ref={ref} position={position} scale={[5, 1.25, 1]}>
      <spriteMaterial map={textureRef.current} transparent opacity={0.6} depthWrite={false} />
    </sprite>
  )
}

// ─── Pulse Rings ─────────────────────────────────────────────────────────────

function PulseRings({ connections, agents }: { connections: Connection[]; agents: AgentNode[] }) {
  const important = useMemo(
    () => connections.filter(c =>
      (c.status === 'matched' || c.status === 'brainstorming') &&
      c.from < agents.length && c.to < agents.length
    ),
    [connections, agents]
  )
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const dummy = useMemo(() => new THREE.Object3D(), [])

  useFrame((state) => {
    if (important.length === 0) return
    const t = state.clock.elapsedTime
    important.forEach((conn, i) => {
      const from = agents[conn.from].position
      const to = agents[conn.to].position
      dummy.position.set(
        (from.x + to.x) / 2,
        (from.y + to.y) / 2 + 1.5,
        (from.z + to.z) / 2,
      )
      const scale = 0.2 + Math.sin(t * 3 + i * 2) * 0.15
      dummy.scale.setScalar(scale)
      dummy.rotation.set(t * 0.5 + i, t * 0.3, 0)
      dummy.updateMatrix()
      meshRef.current.setMatrixAt(i, dummy.matrix)
    })
    meshRef.current.instanceMatrix.needsUpdate = true
  })

  if (important.length === 0) return null

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, important.length]}>
      <octahedronGeometry args={[1, 0]} />
      <meshStandardMaterial
        color="#00ff88"
        emissive="#00ff88"
        emissiveIntensity={2}
        transparent
        opacity={0.35}
        wireframe
      />
    </instancedMesh>
  )
}

// ─── Background Particles ────────────────────────────────────────────────────

function BackgroundParticles({ count = 800 }: { count?: number }) {
  const ref = useRef<THREE.Points>(null!)

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 60
      arr[i * 3 + 1] = (Math.random() - 0.5) * 60
      arr[i * 3 + 2] = (Math.random() - 0.5) * 60
    }
    return arr
  }, [count])

  useFrame((state) => {
    ref.current.rotation.y = state.clock.elapsedTime * 0.008
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.04} color="#223344" transparent opacity={0.5} sizeAttenuation />
    </points>
  )
}

// ─── Scene ───────────────────────────────────────────────────────────────────

function Scene({
  agents,
  connections,
  onSelectAgent,
}: {
  agents: AgentNode[]
  connections: Connection[]
  onSelectAgent: (a: AgentNode) => void
}) {
  const isSmall = agents.length < 20
  const ourAgent = agents.find(a => a.isOurAgent)

  // Only show labels for clusters that have at least one non-our agent
  const activeClusters = useMemo(() => {
    const populated = new Set<number>()
    agents.forEach(a => { if (!a.isOurAgent) populated.add(a.cluster) })
    return CLUSTERS.map((c, i) => ({ ...c, index: i })).filter(c => populated.has(c.index))
  }, [agents])

  return (
    <>
      <ambientLight intensity={0.12} />
      <pointLight position={[20, 20, 20]} intensity={1.2} color="#00d4ff" distance={60} />
      <pointLight position={[-20, -15, -10]} intensity={0.8} color="#b44aff" distance={50} />
      <pointLight position={[0, -20, 15]} intensity={0.6} color="#00ff88" distance={50} />
      <pointLight position={[15, 5, -20]} intensity={0.5} color="#ffcc00" distance={40} />

      <color attach="background" args={['#030308']} />
      <fog attach="fog" args={['#030308', isSmall ? 18 : 25, isSmall ? 40 : 55]} />
      <BackgroundParticles count={isSmall ? 300 : 800} />

      {activeClusters.map(c => (
        <ClusterLabel
          key={c.index}
          name={c.name}
          position={[c.center[0], c.center[1] + (isSmall ? 4 : 5.5), c.center[2]]}
          color={c.color}
        />
      ))}

      <ConnectionLines connections={connections} agents={agents} />
      <PulseRings connections={connections} agents={agents} />
      <FlyingCards connections={connections} agents={agents} />
      <InstancedAgents agents={agents} onSelect={onSelectAgent} />

      {ourAgent && <OurAgentLabel position={ourAgent.position} />}

      <OrbitControls
        enablePan
        minDistance={isSmall ? 5 : 8}
        maxDistance={isSmall ? 35 : 50}
        autoRotate
        autoRotateSpeed={0.15}
        panSpeed={0.5}
      />

      <EffectComposer>
        <Bloom luminanceThreshold={0.15} luminanceSmoothing={0.9} intensity={1.2} mipmapBlur />
        <ChromaticAberration
          offset={new THREE.Vector2(0.0003, 0.0003)}
          radialModulation={false}
          modulationOffset={0}
        />
      </EffectComposer>
    </>
  )
}

// ─── Info Panel ──────────────────────────────────────────────────────────────

function InfoPanel({ agent, onClose }: { agent: AgentNode | null; onClose: () => void }) {
  return (
    <AnimatePresence>
      {agent && (
        <motion.div
          initial={{ opacity: 0, x: 50, scale: 0.95 }}
          animate={{ opacity: 1, x: 0, scale: 1 }}
          exit={{ opacity: 0, x: 50, scale: 0.95 }}
          transition={{ duration: 0.25 }}
          onClick={onClose}
          style={{
            position: 'absolute', top: 80, right: 20,
            background: 'rgba(8, 8, 20, 0.92)',
            border: `1px solid ${agent.isOurAgent ? '#00ffcc55' : STATUS_CONFIG[agent.status].color + '55'}`,
            borderRadius: 14, padding: '20px', minWidth: 280, maxWidth: 340,
            backdropFilter: 'blur(20px)', color: '#fff',
            fontFamily: 'system-ui, -apple-system, sans-serif', zIndex: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <div style={{
              width: 36, height: 36, borderRadius: '50%',
              background: `${agent.color}33`, border: `2px solid ${agent.isOurAgent ? '#00ffcc' : agent.color}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16,
            }}>{agent.isOurAgent ? '\u{2B50}' : '\u{1F464}'}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {agent.isOurAgent ? `${agent.name} (YOU)` : agent.name}
              </div>
              <div style={{ opacity: 0.5, fontSize: 12 }}>{agent.owner}</div>
            </div>
          </div>

          {/* Status */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '3px 10px', borderRadius: 20, marginBottom: 12,
            background: `${STATUS_CONFIG[agent.status].color}18`,
            border: `1px solid ${STATUS_CONFIG[agent.status].color}44`,
            fontSize: 11, color: STATUS_CONFIG[agent.status].color,
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: STATUS_CONFIG[agent.status].color,
              boxShadow: `0 0 6px ${STATUS_CONFIG[agent.status].color}`,
            }} />
            {STATUS_CONFIG[agent.status].label}
            {agent.negotiationState && <span style={{ opacity: 0.6 }}> ({agent.negotiationState})</span>}
          </div>

          {/* Match Score */}
          {agent.matchScore !== undefined && (
            <div style={{
              marginBottom: 8, padding: '4px 10px',
              background: 'rgba(0,212,255,0.08)', border: '1px solid rgba(0,212,255,0.2)',
              borderRadius: 6, fontSize: 12,
            }}>
              Match: <strong>{(agent.matchScore * 100).toFixed(0)}%</strong>
            </div>
          )}

          {/* Description */}
          {agent.description && (
            <p style={{
              fontSize: 12, color: '#888', marginBottom: 8, lineHeight: 1.4,
              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
            }}>{agent.description}</p>
          )}

          {/* Cluster */}
          <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, opacity: 0.4, marginBottom: 6 }}>
            Cluster: {CLUSTERS[agent.cluster].name}
          </div>

          {/* Skills */}
          {agent.skills.length > 0 && (
            <>
              <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, opacity: 0.4, marginBottom: 6 }}>Skills</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {agent.skills.map(s => (
                  <span key={s} style={{
                    padding: '3px 8px', borderRadius: 12,
                    background: `${agent.color}15`, border: `1px solid ${agent.color}33`,
                    fontSize: 11, color: agent.color,
                  }}>{s}</span>
                ))}
              </div>
            </>
          )}

          {/* URL */}
          {!agent.isOurAgent && (
            <div style={{
              marginTop: 10, fontSize: 11, opacity: 0.4,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{agent.url}</div>
          )}

          <div style={{ marginTop: 6, fontSize: 10, opacity: 0.3, textAlign: 'center' }}>Click to close</div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ─── HUD ─────────────────────────────────────────────────────────────────────

function HUD({ agents, connections }: { agents: AgentNode[]; connections: Connection[] }) {
  const stats = useMemo(() => {
    const counts: Record<AgentStatus, number> = { online: 0, searching: 0, negotiating: 0, matched: 0, brainstorming: 0, offline: 0 }
    agents.forEach(a => counts[a.status]++)
    return counts
  }, [agents])

  return (
    <div style={{
      position: 'absolute', top: 0, left: 0, right: 0,
      padding: '16px 24px',
      display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
      pointerEvents: 'none', fontFamily: 'system-ui, -apple-system, sans-serif', zIndex: 5,
    }}>
      <div>
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          style={{ color: '#fff', fontSize: 20, fontWeight: 700, letterSpacing: -0.5 }}
        >
          Agent Social Network
        </motion.div>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.4 }}
          transition={{ delay: 0.4 }}
          style={{ color: '#fff', fontSize: 12, marginTop: 2 }}
        >
          {agents.length} Agents &bull; {connections.length} Connections &bull; Live Data
        </motion.div>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {stats.searching > 0 && <StatBadge label="Matched" value={stats.searching} color="#00d4ff" />}
        {stats.negotiating > 0 && <StatBadge label="Negotiating" value={stats.negotiating} color="#b44aff" />}
        {stats.matched > 0 && <StatBadge label="Confirmed" value={stats.matched} color="#00ff88" />}
        <StatBadge label="Online" value={stats.online} color="#667788" />
        {stats.offline > 0 && <StatBadge label="Offline" value={stats.offline} color="#333344" />}
      </div>
    </div>
  )
}

function StatBadge({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: 0.6 }}
      style={{
        background: 'rgba(8,8,20,0.75)', border: `1px solid ${color}33`,
        borderRadius: 8, padding: '5px 10px', textAlign: 'center',
        backdropFilter: 'blur(8px)', minWidth: 60,
      }}
    >
      <div style={{ color, fontSize: 17, fontWeight: 700 }}>{value}</div>
      <div style={{ color: '#fff', opacity: 0.45, fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.8 }}>{label}</div>
    </motion.div>
  )
}

// ─── Legend ───────────────────────────────────────────────────────────────────

function Legend() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.8 }}
      style={{
        position: 'absolute', bottom: 16, left: 24,
        display: 'flex', gap: 16, flexWrap: 'wrap',
        fontFamily: 'system-ui, sans-serif', fontSize: 10, color: '#ffffff66',
        pointerEvents: 'none', zIndex: 5,
      }}
    >
      <LI color="#00ffcc" label="You" />
      <LI color="#00ff88" label="Confirmed" />
      <LI color="#b44aff" label="Negotiating" />
      <LI color="#00d4ff" label="Matched" />
      <LI color="#667788" label="Online" />
      <LI color="#222233" label="Offline" />
      <span style={{ opacity: 0.4, marginLeft: 8 }}>Scroll to zoom &bull; Drag to rotate &bull; Click agent for details</span>
    </motion.div>
  )
}

function LI({ color, label }: { color: string; label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, boxShadow: `0 0 4px ${color}88` }} />
      {label}
    </div>
  )
}

// ─── Loading Screen ──────────────────────────────────────────────────────────

function LoadingScreen() {
  return (
    <div style={{
      width: '100vw', height: '100vh', background: '#030308',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'system-ui, -apple-system, sans-serif', color: '#fff',
    }}>
      <motion.div
        animate={{ opacity: [0.3, 1, 0.3] }}
        transition={{ duration: 2, repeat: Infinity }}
        style={{ fontSize: 40, marginBottom: 16 }}
      >&#x1F310;</motion.div>
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Loading Agent Network</div>
      <div style={{ fontSize: 12, opacity: 0.4 }}>Fetching data from registries...</div>
    </div>
  )
}

// ─── Main ────────────────────────────────────────────────────────────────────

export function AgentNetworkVisualization() {
  const [agents, setAgents] = useState<AgentNode[]>([])
  const [connections, setConnections] = useState<Connection[]>([])
  const [selectedAgent, setSelectedAgent] = useState<AgentNode | null>(null)
  const [loading, setLoading] = useState(true)

  const loadData = useCallback(async () => {
    const [rawAgents, matches, negotiations, health] = await Promise.all([
      fetchAllAgents(),
      fetchMatches(),
      fetchNegotiations(),
      fetchOurHealth(),
    ])

    const { agents: newAgents, connections: newConns } = buildVizData(
      rawAgents, matches, negotiations, health
    )

    setAgents(newAgents)
    setConnections(newConns)
    setLoading(false)
  }, [])

  // Initial load
  useEffect(() => {
    loadData()
  }, [loadData])

  // Auto-refresh every 60s
  useEffect(() => {
    const iv = setInterval(loadData, 60000)
    return () => clearInterval(iv)
  }, [loadData])

  const handleSelect = useCallback((agent: AgentNode) => {
    setSelectedAgent(prev => prev?.id === agent.id ? null : agent)
  }, [])

  if (loading) return <LoadingScreen />

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative', background: '#030308' }}>
      <Canvas
        camera={{ position: [0, 5, agents.length < 20 ? 20 : 30], fov: 55 }}
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      >
        <Scene agents={agents} connections={connections} onSelectAgent={handleSelect} />
      </Canvas>
      <HUD agents={agents} connections={connections} />
      <Legend />
      <InfoPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </div>
  )
}
