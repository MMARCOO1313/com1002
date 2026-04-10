/**
 * CalledAlert — full-screen flash overlay
 * Shown for 8 seconds when a queue number is called.
 */
export default function CalledAlert({ data }) {
  const ZONE_NAMES = { A: '羽毛球 / 籃球區', B: '匹克球 / 乒乓球區', C: '社區休閒區', D: '新興運動區' }

  return (
    <div style={s.overlay}>
      <div style={s.box}>
        <div style={s.bell}>🔔</div>
        <div style={s.headline}>請注意！</div>
        <div style={s.zone}>{ZONE_NAMES[data.zone_id] || data.zone_id}</div>
        <div style={s.numLabel}>號碼</div>
        <div style={s.num}>{data.queue_num}</div>
        <div style={s.name}>{data.user_name} 請入場</div>
        <div style={s.warn}>⚠️ 請於 5 分鐘內入場，逾時取消</div>
      </div>
    </div>
  )
}

const s = {
  overlay: {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.82)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 999, animation: 'fadeIn 0.3s ease',
  },
  box: {
    background: '#1E293B', borderRadius: 24, padding: '48px 64px',
    textAlign: 'center', border: '3px solid #3B82F6',
    boxShadow: '0 0 60px #3B82F688',
    minWidth: 420,
  },
  bell: { fontSize: 64, marginBottom: 16 },
  headline: { fontSize: 28, fontWeight: 700, color: '#94A3B8', marginBottom: 8 },
  zone: { fontSize: 22, color: '#CBD5E1', marginBottom: 16 },
  numLabel: { fontSize: 16, color: '#64748B' },
  num: { fontSize: 100, fontWeight: 900, color: '#3B82F6', lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' },
  name: { fontSize: 24, fontWeight: 600, color: '#22C55E', marginTop: 12, marginBottom: 20 },
  warn: { fontSize: 15, color: '#F59E0B' },
}
