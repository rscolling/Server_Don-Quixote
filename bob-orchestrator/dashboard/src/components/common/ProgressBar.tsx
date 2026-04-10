export function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const color = pct < 50 ? 'var(--success)' : pct < 80 ? 'var(--warning)' : 'var(--error)';

  return (
    <div style={{ marginBottom: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ color }}>${value.toFixed(2)} / ${max.toFixed(2)}</span>
      </div>
      <div style={{ background: 'var(--bg-elevated)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.3s' }} />
      </div>
    </div>
  );
}
