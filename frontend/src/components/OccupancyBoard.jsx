export default function OccupancyBoard({ zones = [] }) {
  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={{ fontSize: 18 }}>OCC</span>
        <span style={styles.title}>ZONE OCCUPANCY</span>
      </div>
      {zones.map(zone => <ZoneCard key={zone.id} zone={zone} />)}
    </div>
  )
}

function ZoneCard({ zone }) {
  const pct = Math.min(100, Math.round((zone.current_count / zone.capacity) * 100))
  const color = pct >= 100 ? '#EF4444' : pct >= 85 ? '#FBBF24' : '#22C55E'
  const statusLabel = zone.status === 'full' ? 'FULL' : zone.status === 'busy' ? 'HIGH' : 'OPEN'

  return (
    <div style={{ ...styles.card, borderColor: color + '44' }}>
      <div style={styles.cardTop}>
        <div style={{ ...styles.zoneCircle, background: color }}>{zone.id}</div>
        <div style={{ flex: 1 }}>
          <div style={styles.zoneName}>{zone.name_en || zone.name_zh}</div>
          <div style={{ color: '#888', fontSize: 11 }}>{zone.name_zh}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ color, fontSize: 24, fontWeight: 800 }}>{zone.current_count}</div>
          <div style={{ color: '#888', fontSize: 11 }}>/ {zone.capacity}</div>
        </div>
      </div>
      <div style={styles.barBg}>
        <div style={{ ...styles.barFill, width: `${pct}%`, background: color }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
        <span style={{ color, fontSize: 11, fontWeight: 600 }}>{statusLabel}</span>
        <span style={{ color: '#888', fontSize: 11 }}>{pct}%</span>
      </div>
    </div>
  )
}

const styles = {
  panel: { background: '#1A1A2E', borderRadius: 12, padding: 16, border: '1px solid #2A2A3E' },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 },
  title: { fontSize: 14, fontWeight: 700, color: '#FFF', letterSpacing: 1 },
  card: { background: '#12121F', borderRadius: 10, padding: 12, marginBottom: 8, border: '1px solid' },
  cardTop: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 },
  zoneCircle: { width: 36, height: 36, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#FFF', fontWeight: 800, fontSize: 16 },
  zoneName: { fontSize: 13, fontWeight: 600, color: '#FFF' },
  barBg: { height: 8, borderRadius: 4, background: '#2A2A3E', overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: 4, transition: 'width 0.5s ease' },
}
