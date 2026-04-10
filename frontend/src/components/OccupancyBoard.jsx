/**
 * OccupancyBoard — left panel
 * Shows real-time people count per zone with animated fill bars.
 */
export default function OccupancyBoard({ zones }) {
  if (!zones.length) {
    return (
      <div style={s.card}>
        <div style={s.sectionTitle}>📊 即時使用情況</div>
        <div style={s.empty}>載入中…</div>
      </div>
    )
  }

  return (
    <div style={s.card}>
      <div style={s.sectionTitle}>📊 即時使用情況</div>
      <div style={s.zoneGrid}>
        {zones.map(z => <ZoneCard key={z.id} zone={z} />)}
      </div>
      <div style={s.legend}>
        <span style={{ color: '#22C55E' }}>● 空閒 &lt;70%</span>
        <span style={{ color: '#F59E0B' }}>● 繁忙 70–89%</span>
        <span style={{ color: '#EF4444' }}>● 已滿 ≥90%</span>
      </div>
    </div>
  )
}

function ZoneCard({ zone }) {
  const pct = Math.min(100, Math.round((zone.current_count / Math.max(zone.capacity, 1)) * 100))

  let barColor, statusText, statusColor
  if (pct >= 90) {
    barColor = '#EF4444'; statusText = '已滿'; statusColor = '#EF4444'
  } else if (pct >= 70) {
    barColor = '#F59E0B'; statusText = '繁忙'; statusColor = '#F59E0B'
  } else {
    barColor = '#22C55E'; statusText = '空閒'; statusColor = '#22C55E'
  }

  return (
    <div style={s.zoneCard}>
      <div style={s.zoneHeader}>
        <span style={s.zoneName}>{zone.name_zh}</span>
        <span style={{ ...s.statusBadge, background: statusColor + '22', color: statusColor }}>
          {statusText}
        </span>
      </div>

      {/* Count display */}
      <div style={s.countRow}>
        <span style={s.countBig}>{zone.current_count}</span>
        <span style={s.countSep}>/</span>
        <span style={s.countCap}>{zone.capacity}</span>
        <span style={s.countLabel}>人</span>
      </div>

      {/* Progress bar */}
      <div style={s.barBg}>
        <div style={{
          ...s.barFill,
          width: `${pct}%`,
          background: barColor,
          boxShadow: `0 0 8px ${barColor}88`,
        }} />
      </div>
      <div style={{ ...s.pctLabel, color: barColor }}>{pct}%</div>
    </div>
  )
}

const s = {
  card: {
    background: '#1E293B', borderRadius: 16, padding: 24, height: '100%',
    border: '1px solid #334155',
  },
  sectionTitle: {
    fontSize: 20, fontWeight: 700, color: '#F1F5F9', marginBottom: 20,
    paddingBottom: 12, borderBottom: '1px solid #334155',
  },
  zoneGrid: { display: 'flex', flexDirection: 'column', gap: 16 },
  zoneCard: {
    background: '#0F172A', borderRadius: 12, padding: '16px 20px',
    border: '1px solid #334155',
  },
  zoneHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  zoneName: { fontSize: 16, fontWeight: 600, color: '#E2E8F0' },
  statusBadge: {
    fontSize: 13, fontWeight: 600, padding: '3px 10px', borderRadius: 20,
  },
  countRow: { display: 'flex', alignItems: 'baseline', gap: 4, marginBottom: 10 },
  countBig: { fontSize: 42, fontWeight: 700, color: '#F1F5F9', lineHeight: 1 },
  countSep: { fontSize: 28, color: '#475569' },
  countCap: { fontSize: 24, color: '#94A3B8' },
  countLabel: { fontSize: 16, color: '#64748B', marginLeft: 4 },
  barBg: {
    background: '#1E293B', borderRadius: 8, height: 10, overflow: 'hidden',
    border: '1px solid #334155',
  },
  barFill: {
    height: '100%', borderRadius: 8,
    transition: 'width 0.8s cubic-bezier(0.4,0,0.2,1)',
  },
  pctLabel: { fontSize: 13, marginTop: 4, textAlign: 'right', fontVariantNumeric: 'tabular-nums' },
  legend: {
    display: 'flex', gap: 20, marginTop: 20, paddingTop: 16,
    borderTop: '1px solid #334155', fontSize: 13, color: '#94A3B8',
  },
  empty: { color: '#64748B', padding: 40, textAlign: 'center' },
}
