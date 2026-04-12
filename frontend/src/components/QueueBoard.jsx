export default function QueueBoard({ queue = [] }) {
  const waitingCount = queue.filter((item) => item.status === 'waiting').length

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={styles.icon}>Q</span>
        <span style={styles.title}>QUEUE STATUS</span>
        <span style={styles.badge}>{waitingCount} waiting</span>
      </div>

      {queue.length === 0 ? (
        <div style={styles.empty}>Queue is empty. Walk-in is available.</div>
      ) : (
        <div>
          <div style={styles.tableHeader}>
            <span style={{ width: 70 }}>Ticket</span>
            <span style={{ width: 60 }}>Zone</span>
            <span style={{ flex: 1 }}>User</span>
            <span style={{ width: 80 }}>Status</span>
          </div>

          {queue.map((item, index) => (
            <div
              key={`${item.zone_id}-${item.queue_num}-${index}`}
              style={{
                ...styles.row,
                background: index % 2 === 0 ? '#12121F' : '#16162A',
              }}
            >
              <span style={{ width: 70, fontWeight: 700, color: '#FFF' }}>
                {item.zone_id}-{String(item.queue_num).padStart(3, '0')}
              </span>
              <span style={{ width: 60, color: '#999' }}>Zone {item.zone_id}</span>
              <span style={{ flex: 1, color: '#CCC' }}>{item.name || '-'}</span>
              <span
                style={{
                  width: 80,
                  textAlign: 'center',
                  padding: '2px 0',
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 600,
                  color: '#FFF',
                  background: item.status === 'called' ? '#FF5722' : '#3B82F6',
                }}
              >
                {item.status === 'called' ? 'CALLED' : 'WAITING'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  panel: {
    background: '#0C0C14',
    border: '1px solid #1F1F33',
    borderRadius: 16,
    padding: 16,
    boxShadow: '0 6px 24px rgba(0,0,0,0.25)',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginBottom: 14,
  },
  icon: {
    width: 24,
    height: 24,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 999,
    background: '#1F2937',
    color: '#E5E7EB',
    fontSize: 12,
    fontWeight: 700,
  },
  title: {
    fontSize: 15,
    fontWeight: 800,
    color: '#FFF',
    letterSpacing: '0.04em',
  },
  badge: {
    marginLeft: 'auto',
    fontSize: 12,
    color: '#94A3B8',
  },
  empty: {
    padding: '18px 12px',
    borderRadius: 12,
    background: '#12121F',
    color: '#94A3B8',
    fontSize: 14,
  },
  tableHeader: {
    display: 'flex',
    gap: 8,
    padding: '0 0 10px',
    marginBottom: 8,
    color: '#64748B',
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 12px',
    borderRadius: 10,
    marginBottom: 8,
    fontSize: 13,
  },
}
