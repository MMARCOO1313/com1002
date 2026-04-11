const DEVICE_ICONS = { light: '💡', hoop: '🏀', gate: '🚪' }
const STATE_COLORS = {
  on: '#22C55E', off: '#555', flash: '#FBBF24',
  deployed: '#22C55E', retracted: '#EF4444',
  open: '#22C55E', locked: '#EF4444',
  'n/a': '#333',
}

export default function DevicePanel({ devices = {} }) {
  const zones = Object.entries(devices)
  if (zones.length === 0) return null

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span>🔌</span>
        <span style={styles.title}>SMART CONTROL</span>
      </div>
      <div style={styles.grid}>
        {zones.map(([zoneId, devs]) => (
          <div key={zoneId} style={styles.zoneCard}>
            <div style={styles.zoneName}>Zone {zoneId}</div>
            <div style={styles.devices}>
              {Object.entries(devs).map(([dev, state]) => (
                <div key={dev} style={styles.device}>
                  <span>{DEVICE_ICONS[dev] || '⚙️'}</span>
                  <span style={{ fontSize: 10, color: '#999' }}>{dev}</span>
                  <span style={{
                    ...styles.state,
                    background: STATE_COLORS[state] || '#555',
                    animation: state === 'flash' ? 'pulse 0.5s infinite' : 'none',
                  }}>{state}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const styles = {
  panel: { background: '#1A1A2E', borderRadius: 12, padding: 16, border: '1px solid #2A2A3E' },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 },
  title: { fontSize: 14, fontWeight: 700, color: '#FFF', letterSpacing: 1 },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 },
  zoneCard: { background: '#12121F', borderRadius: 8, padding: 10 },
  zoneName: { fontSize: 12, fontWeight: 700, color: '#CCC', marginBottom: 6 },
  devices: { display: 'flex', gap: 8 },
  device: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, flex: 1 },
  state: { fontSize: 9, padding: '1px 6px', borderRadius: 4, color: '#FFF', fontWeight: 600 },
}
