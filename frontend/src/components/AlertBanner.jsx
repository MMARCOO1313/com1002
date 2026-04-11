const SEV_STYLE = {
  info:     { bg: '#1A2E3E', border: '#3B82F6', icon: 'ℹ️' },
  warning:  { bg: '#2E2A0F', border: '#FBBF24', icon: '⚠️' },
  critical: { bg: '#2E0F0F', border: '#EF4444', icon: '🚨' },
}

export default function AlertBanner({ alerts = [] }) {
  if (alerts.length === 0) return null

  const latest = alerts[0]
  const sev = SEV_STYLE[latest.severity] || SEV_STYLE.info

  return (
    <div style={{
      margin: '0 24px',
      padding: '8px 16px',
      background: sev.bg,
      border: `1px solid ${sev.border}`,
      borderRadius: 8,
      display: 'flex',
      alignItems: 'center',
      gap: 10,
    }}>
      <span style={{ fontSize: 18 }}>{sev.icon}</span>
      <span style={{ color: sev.border, fontWeight: 600, fontSize: 13 }}>{latest.message}</span>
      <span style={{ marginLeft: 'auto', color: '#666', fontSize: 11 }}>
        {new Date(latest.time).toLocaleTimeString('en-GB')}
      </span>
      {alerts.length > 1 && (
        <span style={{ background: '#333', padding: '1px 8px', borderRadius: 8, fontSize: 10, color: '#AAA' }}>
          +{alerts.length - 1} more
        </span>
      )}
    </div>
  )
}
