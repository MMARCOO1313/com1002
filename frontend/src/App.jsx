import { useEffect, useRef, useState } from 'react'
import OccupancyBoard from './components/OccupancyBoard.jsx'
import QueueBoard from './components/QueueBoard.jsx'
import SessionPanel from './components/SessionPanel.jsx'
import DevicePanel from './components/DevicePanel.jsx'
import AlertBanner from './components/AlertBanner.jsx'
import CalledAlert from './components/CalledAlert.jsx'

const WS_URL = import.meta.env.VITE_API_WS || 'ws://localhost:8000/ws'
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const RECONNECT_MS = 3000

export default function App() {
  const [zones, setZones] = useState([])
  const [queue, setQueue] = useState([])
  const [sessions, setSessions] = useState([])
  const [devices, setDevices] = useState({})
  const [alerts, setAlerts] = useState([])
  const [calledAlert, setCalled] = useState(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    fetch(`${API_URL}/zones`).then(r => r.json()).then(setZones).catch(() => {})
  }, [])

  useEffect(() => {
    let timeout

    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        if (msg.type === 'init') {
          setZones(msg.zones || [])
          setQueue(msg.queue || [])
          setSessions(msg.sessions || [])
          setDevices(msg.devices || {})
        } else if (msg.type === 'occupancy') {
          setZones(msg.zones || [])
        } else if (msg.type === 'queue') {
          setQueue(msg.data || [])
        } else if (msg.type === 'called') {
          setQueue(msg.queue || [])
          setCalled({
            zone_id: msg.zone_id,
            queue_num: msg.queue_num,
            user_name: msg.user_name,
            auto: msg.auto,
          })
          setTimeout(() => setCalled(null), 10000)
        } else if (msg.type === 'sessions') {
          setSessions(msg.data || [])
        } else if (msg.type === 'devices') {
          setDevices(msg.state || {})
        } else if (msg.type === 'alert') {
          setAlerts(prev => [msg, ...prev].slice(0, 10))
        }
      }
      ws.onclose = () => {
        setConnected(false)
        timeout = setTimeout(connect, RECONNECT_MS)
      }
      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      clearTimeout(timeout)
      wsRef.current?.close()
    }
  }, [])

  useEffect(() => {
    const intervalId = setInterval(() => {
      setSessions(prev =>
        prev.map(session => ({
          ...session,
          remaining_seconds: Math.max(0, (session.remaining_seconds || 0) - 1),
        }))
      )
    }, 1000)
    return () => clearInterval(intervalId)
  }, [])

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.logo}>BS</span>
          <div>
            <div style={styles.title}>BridgeSpace</div>
            <div style={styles.subtitle}>AI-Powered Community Sports Hub</div>
            <div style={styles.subsubtitle}>Autonomous Operations Dashboard</div>
          </div>
        </div>
        <div style={styles.headerRight}>
          <LiveClock />
          <div style={{ ...styles.dot, background: connected ? '#22C55E' : '#EF4444' }} />
          <span style={{ color: connected ? '#22C55E' : '#EF4444', fontSize: 12 }}>
            {connected ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
      </header>

      {calledAlert && <CalledAlert {...calledAlert} />}

      <AlertBanner alerts={alerts} />

      <div style={styles.grid}>
        <div style={styles.leftCol}>
          <OccupancyBoard zones={zones} />
          <DevicePanel devices={devices} />
        </div>
        <div style={styles.rightCol}>
          <SessionPanel sessions={sessions} />
          <QueueBoard queue={queue} />
        </div>
      </div>

      <footer style={styles.footer}>
        <span>BridgeSpace Autonomous System v2.0</span>
        <span>COM1002 Group 5 | HSUHK | {new Date().getFullYear()}</span>
      </footer>
    </div>
  )
}

function LiveClock() {
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const intervalId = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(intervalId)
  }, [])

  return (
    <span style={{ color: '#FFF', fontFamily: 'monospace', fontSize: 18 }}>
      {time.toLocaleTimeString('en-GB')}
    </span>
  )
}

const styles = {
  root: { minHeight: '100vh', background: '#0F0F1A', color: '#FFF', fontFamily: "'Segoe UI', system-ui, sans-serif" },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 24px', background: '#1A1A2E', borderBottom: '2px solid #FF5722' },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 12 },
  headerRight: { display: 'flex', alignItems: 'center', gap: 10 },
  logo: { fontSize: 24, fontWeight: 900, color: '#FFB17A', letterSpacing: 1 },
  title: { fontSize: 24, fontWeight: 800, color: '#FFF' },
  subtitle: { fontSize: 12, color: '#999' },
  subsubtitle: { fontSize: 11, color: '#777' },
  dot: { width: 10, height: 10, borderRadius: '50%' },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, padding: '16px 24px' },
  leftCol: { display: 'flex', flexDirection: 'column', gap: 16 },
  rightCol: { display: 'flex', flexDirection: 'column', gap: 16 },
  footer: { display: 'flex', justifyContent: 'space-between', padding: '8px 24px', color: '#666', fontSize: 11, borderTop: '1px solid #222' },
}
