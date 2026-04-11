import { useMemo } from 'react'

const STATUS_MAP = {
  active:  { label: '使用中',  color: '#22C55E', bg: '#0F2E1A' },
  warning: { label: '即將到期', color: '#FBBF24', bg: '#2E2A0F' },
  expired: { label: '已到期',  color: '#EF4444', bg: '#2E0F0F' },
  overstay:{ label: '超時滯留', color: '#FF0000', bg: '#3D0000' },
}

function formatTime(secs) {
  if (!secs || secs <= 0) return '00:00'
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
}

export default function SessionPanel({ sessions = [] }) {
  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={styles.icon}>⏱️</span>
        <span style={styles.title}>SESSION TIMERS</span>
        <span style={styles.badge}>{sessions.length} active</span>
      </div>
      {sessions.length === 0 ? (
        <div style={styles.empty}>所有場地空閒 — 等待用戶入場</div>
      ) : (
        sessions.map(s => <SessionCard key={s.id} session={s} />)
      )}
    </div>
  )
}

function SessionCard({ session }) {
  const s = session
  const info = STATUS_MAP[s.status] || STATUS_MAP.active
  const remaining = s.remaining_seconds || 0
  const isUrgent = remaining <= 300 && remaining > 0
  const isOver = s.status === 'expired' || s.status === 'overstay'

  return (
    <div style={{ ...styles.card, borderColor: info.color, background: info.bg }}>
      <div style={styles.cardTop}>
        <span style={{ ...styles.zone, background: info.color }}>Zone {s.zone_id}</span>
        <span style={{ ...styles.status, color: info.color }}>{info.label}</span>
      </div>
      <div style={styles.cardBody}>
        <div style={styles.userName}>{s.name || '用戶'}</div>
        <div style={{
          ...styles.timer,
          color: isOver ? '#FF0000' : isUrgent ? '#FBBF24' : '#FFF',
          animation: isUrgent ? 'pulse 1s infinite' : 'none',
        }}>
          {isOver ? `+${formatTime(Math.abs(remaining))}` : formatTime(remaining)}
        </div>
      </div>
      <div style={styles.cardBottom}>
        <span style={{ color: '#888', fontSize: 11 }}>
          延時: {s.extended || 0}/2
        </span>
        {s.status === 'expired' && (
          <span style={{ color: '#FF6B6B', fontSize: 11, fontWeight: 600 }}>
            🔴 燈光已關閉 · 設備已收起
          </span>
        )}
        {s.status === 'overstay' && (
          <span style={{ color: '#FF0000', fontSize: 11, fontWeight: 600 }}>
            🚨 已通知管理員
          </span>
        )}
      </div>
    </div>
  )
}

const styles = {
  panel: { background: '#1A1A2E', borderRadius: 12, padding: 16, border: '1px solid #2A2A3E' },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 },
  icon: { fontSize: 18 },
  title: { fontSize: 14, fontWeight: 700, color: '#FFF', letterSpacing: 1 },
  badge: { marginLeft: 'auto', background: '#333', padding: '2px 10px', borderRadius: 10, fontSize: 11, color: '#AAA' },
  empty: { color: '#555', textAlign: 'center', padding: 24, fontSize: 13 },
  card: { border: '1px solid', borderRadius: 10, padding: 12, marginBottom: 8 },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  zone: { padding: '2px 12px', borderRadius: 6, color: '#FFF', fontSize: 12, fontWeight: 700 },
  status: { fontSize: 12, fontWeight: 600 },
  cardBody: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  userName: { fontSize: 16, fontWeight: 600, color: '#FFF' },
  timer: { fontSize: 32, fontWeight: 800, fontFamily: 'monospace' },
  cardBottom: { display: 'flex', justifyContent: 'space-between', marginTop: 6 },
}
