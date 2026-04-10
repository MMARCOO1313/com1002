import { useState, useEffect, useRef } from 'react'
import OccupancyBoard from './components/OccupancyBoard.jsx'
import QueueBoard from './components/QueueBoard.jsx'
import CalledAlert from './components/CalledAlert.jsx'

// ── Config ─────────────────────────────────────────────────────────────────
// In production: set VITE_API_WS=wss://your-railway-app.railway.app/ws
const WS_URL = import.meta.env.VITE_API_WS || 'ws://localhost:8000/ws'
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const RECONNECT_MS = 3000

// ── App ────────────────────────────────────────────────────────────────────
export default function App() {
  const [zones, setZones]       = useState([])
  const [queue, setQueue]       = useState([])
  const [calledAlert, setCalled] = useState(null)   // {zone_id, queue_num, user_name}
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

  // Fetch initial data via REST as fallback
  useEffect(() => {
    fetch(`${API_URL}/zones`)
      .then(r => r.json())
      .then(setZones)
      .catch(() => {})
  }, [])

  // WebSocket live updates
  useEffect(() => {
    let timeout
    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => { setConnected(true) }

      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        if (msg.type === 'init') {
          setZones(msg.zones)
          setQueue(msg.queue)
        } else if (msg.type === 'occupancy') {
          setZones(msg.zones)
        } else if (msg.type === 'queue') {
          setQueue(msg.data)
        } else if (msg.type === 'called') {
          setQueue(msg.queue)
          setCalled({ zone_id: msg.zone_id, queue_num: msg.queue_num, user_name: msg.user_name })
          setTimeout(() => setCalled(null), 8000)
        }
      }

      ws.onclose = () => {
        setConnected(false)
        timeout = setTimeout(connect, RECONNECT_MS)
      }
      ws.onerror = () => ws.close()
    }
    connect()
    return () => { clearTimeout(timeout); wsRef.current?.close() }
  }, [])

  return (
    <div style={styles.root}>
      {/* Header */}
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.logo}>🏃</span>
          <div>
            <div style={styles.title}>BridgeSpace</div>
            <div style={styles.subtitle}>橋底智能社區運動中心</div>
          </div>
        </div>
        <div style={styles.headerRight}>
          <LiveClock />
          <div style={{
            ...styles.dot,
            background: connected ? '#22C55E' : '#EF4444'
          }} />
          <span style={styles.connLabel}>{connected ? '實時更新' : '連接中…'}</span>
        </div>
      </header>

      {/* Main grid */}
      <main style={styles.main}>
        <div style={styles.left}>
          <OccupancyBoard zones={zones} />
        </div>
        <div style={styles.right}>
          <QueueBoard zones={zones} queue={queue} apiUrl={API_URL} />
        </div>
      </main>

      {/* Called alert overlay */}
      {calledAlert && <CalledAlert data={calledAlert} />}

      {/* Footer */}
      <footer style={styles.footer}>
        <span>請到自助登記機排隊 ·  現場排隊，防止炒場</span>
        <span>⚠️ 無預約功能 · 親身到場方可排隊</span>
      </footer>
    </div>
  )
}

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return (
    <span style={styles.clock}>
      {time.toLocaleTimeString('zh-Hant', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
    </span>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────
const styles = {
  root: {
    minHeight: '100vh', background: '#0F172A', color: '#F1F5F9',
    display: 'flex', flexDirection: 'column',
  },
  header: {
    background: '#1E293B', padding: '16px 32px',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    borderBottom: '2px solid #3B82F6',
  },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 16 },
  logo: { fontSize: 40 },
  title: { fontSize: 28, fontWeight: 700, color: '#F1F5F9' },
  subtitle: { fontSize: 16, color: '#94A3B8' },
  headerRight: { display: 'flex', alignItems: 'center', gap: 12 },
  clock: { fontSize: 22, fontWeight: 600, color: '#F1F5F9', fontVariantNumeric: 'tabular-nums' },
  dot: { width: 12, height: 12, borderRadius: '50%' },
  connLabel: { fontSize: 14, color: '#94A3B8' },
  main: {
    flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr',
    gap: 24, padding: 24,
  },
  left: {},
  right: {},
  footer: {
    background: '#1E293B', padding: '12px 32px',
    display: 'flex', justifyContent: 'space-between',
    fontSize: 14, color: '#64748B',
    borderTop: '1px solid #334155',
  },
}
