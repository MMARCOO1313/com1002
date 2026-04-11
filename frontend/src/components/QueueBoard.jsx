export default function QueueBoard({ queue = [] }) {
  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={{ fontSize: 18 }}>ð</span>
        <span style={styles.title}>QUEUE STATUS</span>
        <span style={styles.badge}>{queue.filter(q => q.status === 'waiting').length} waiting</span>
      </div>
      {queue.length === 0 ? (
        <div style={styles.empty}>æéçºç©º â å¯ç´æ¥å¥å ´</div>
      ) : (
        <div>
          <div style={styles.tableHeader}>
            <span style={{ width: 70 }}>èç¢¼</span>
            <span style={{ width: 60 }}>åå</span>
            <span style={{ flex: 1 }}>ç¨æ¶</span>
            <span style={{ width: 80 }}>çæ</span>
          </div>
          {queue.map((q, i) => (
            <div key={i} style={{ ...styles.row, background: i % 2 === 0 ? '#12121F' : '#16162A' }}>
              <span style={{ width: 70, fontWeight: 700, color: '#FFF' }}>
                {q.zone_id}-{String(q.queue_num).padStart(3, '0')}
              </span>
              <span style={{ width: 60, color: '#999' }}>Zone {q.zone_id}</span>
              <span style={{ flex: 1, color: '#CCC' }}>{q.name || 'â'}</span>
              <span style={{
                width: 80,
                textAlign: 'center',
                padding: '2px 0',
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 600,
                color: '#FFF',
                background: q.status === 'called' ? '#FF5722' : '#3B82F6',
              }}>
                {q.status === 'called' ? 'å«èä¸­' : 'ç­åä¸­'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  
 "fOA RE : C? XíPcKD SwLù:000 â"â'(a0è¬¼O"ç¨æ¶?¼þ©J
