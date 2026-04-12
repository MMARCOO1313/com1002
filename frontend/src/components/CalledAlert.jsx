export default function CalledAlert({ zone_id, queue_num, user_name, auto }) {
  return (
    <div style={styles.overlay}>
      <div style={styles.card}>
        <div style={styles.label}>
          {auto ? 'AUTOMATIC NEXT CALL' : 'MANUAL NEXT CALL'}
        </div>
        <div style={styles.number}>{zone_id}-{String(queue_num).padStart(3, '0')}</div>
        <div style={styles.name}>{user_name}</div>
        <div style={styles.instruction}>
          Please proceed to Zone {zone_id} and complete entry at SmartGate.
        </div>
        <div style={styles.timer}>Entry window: 15 minutes after the call is shown.</div>
      </div>
    </div>
  )
}

const styles = {
  overlay: { position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000, display: 'flex', justifyContent: 'center', padding: '80px 20px', pointerEvents: 'none' },
  card: { background: '#FF5722', borderRadius: 16, padding: '32px 48px', textAlign: 'center', boxShadow: '0 8px 40px rgba(255,87,34,0.5)', animation: 'slideDown 0.4s ease' },
  label: { fontSize: 14, color: 'rgba(255,255,255,0.8)', fontWeight: 600, marginBottom: 8 },
  number: { fontSize: 56, fontWeight: 900, color: '#FFF', lineHeight: 1 },
  name: { fontSize: 24, color: '#FFF', marginTop: 8, fontWeight: 600 },
  instruction: { fontSize: 14, color: 'rgba(255,255,255,0.8)', marginTop: 12 },
  timer: { fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 8 },
}
