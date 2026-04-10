/**
 * QueueBoard — right panel
 * Shows the live queue per zone + staff "Call Next" button.
 */
import { useState } from 'react'

const ZONE_ICONS = { A: '🏸', B: '🏓', C: '🌿', D: '🛹' }

export default function QueueBoard({ zones, queue, apiUrl }) {
  const [calling, setCalling] = useState({})

  async function callNext(zoneId) {
    setCalling(prev => ({ ...prev, [zoneId]: true }))
    try {
      await fetch(`${apiUrl}/queue/call-next/${zoneId}`, { method: 'POST' })
    } catch (e) {
      console.error(e)
    } finally {
      setTimeout(() => setCalling(prev => ({ ...prev, [zoneId]: false })), 1500)
    }
  }

  // Group queue by zone
  const qByZone = {}
  queue.forEach(q => {
    if (!qByZone[q.zone_id]) qByZone[q.zone_id] = []
    qByZone[q.zone_id].push(q)
  })

  return (
    <div style={s.card}>
      <div style={s.sectionTitle}>🎫 排隊號碼板</div>

      {zones.map(z => {
        const zq = qByZone[z.id] || []
        const waiting  = zq.filter(q => q.status === 'waiting')
        const called   = zq.filter(q => q.status === 'called')
        const nowNum   = called[0]?.queue_num ?? '—'
        const nextNums = waiting.slice(0, 5).map(q => q.queue_num)

        return (
          <div key={z.id} style={s.zoneBlock}>
            {/* Zone header */}
            <div style={s.zoneHead}>
              <span style={s.zoneIcon}>{ZONE_ICONS[z.id] || '🏃'}</span>
              <span style={s.zoneName}>{z.name_zh}</span>
              <span style={s.waitCount}>等候：{waiting.length} 人</span>
            </div>

            <div style={s.row}>
              {/* Now serving */}
              <div style={s.nowBox}>
                <div style={s.nowLabel}>現正服務</div>
                <div style={s.nowNum}>{nowNum}</div>
              </div>

              {/* Next up */}
              <div style={s.nextBox}>
                <div style={s.nextLabel}>等候號碼</div>
                <div style={s.numRow}>
                  {nextNums.length === 0
                    ? <span style={s.noQueue}>隊伍暫空</span>
                    : nextNums.map(n => (
                      <span key={n} style={s.numChip}>{n}</span>
                    ))
                  }
                  {waiting.length > 5 &&
                    <span style={s.more}>+{waiting.length - 5}</span>
                  }
                </div>
              </div>
            </div>

            {/* Staff call button */}
            <button
              style={{
                ...s.callBtn,
                opacity: calling[z.id] ? 0.5 : 1,
                cursor: calling[z.id] ? 'wait' : 'pointer',
              }}
              onClick={() => callNext(z.id)}
              disabled={!!calling[z.id]}
            >
              {calling[z.id] ? '叫號中…' : '📢  叫下一位'}
            </button>
          </div>
        )
      })}
    </div>
  )
}

const s = {
  card: {
    background: '#1E293B', borderRadius: 16, padding: 24,
    border: '1px solid #334155', height: '100%',
  },
  sectionTitle: {
    fontSize: 20, fontWeight: 700, color: '#F1F5F9', marginBottom: 20,
    paddingBottom: 12, borderBottom: '1px solid #334155',
  },
  zoneBlock: {
    background: '#0F172A', borderRadius: 12, padding: 16,
    marginBottom: 16, border: '1px solid #334155',
  },
  zoneHead: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 },
  zoneIcon: { fontSize: 20 },
  zoneName: { fontSize: 15, fontWeight: 600, color: '#E2E8F0', flex: 1 },
  waitCount: { fontSize: 13, color: '#64748B' },
  row: { display: 'flex', gap: 12, marginBottom: 12 },
  nowBox: {
    background: '#1E293B', borderRadius: 10, padding: '10px 16px',
    textAlign: 'center', minWidth: 100, border: '1px solid #3B82F6',
  },
  nowLabel: { fontSize: 11, color: '#94A3B8', marginBottom: 4 },
  nowNum: { fontSize: 40, fontWeight: 800, color: '#3B82F6', lineHeight: 1, fontVariantNumeric: 'tabular-nums' },
  nextBox: { flex: 1, background: '#1E293B', borderRadius: 10, padding: '10px 14px', border: '1px solid #334155' },
  nextLabel: { fontSize: 11, color: '#94A3B8', marginBottom: 8 },
  numRow: { display: 'flex', flexWrap: 'wrap', gap: 6 },
  numChip: {
    background: '#334155', color: '#CBD5E1', borderRadius: 8,
    padding: '4px 10px', fontSize: 15, fontWeight: 600,
  },
  more: { color: '#64748B', fontSize: 13, alignSelf: 'center' },
  noQueue: { color: '#475569', fontSize: 13 },
  callBtn: {
    width: '100%', background: '#1D4ED8', color: '#fff',
    border: 'none', borderRadius: 8, padding: '10px 0',
    fontSize: 15, fontWeight: 600, cursor: 'pointer',
    transition: 'opacity 0.2s',
  },
}
