import { type CSSProperties } from 'react';

export function Badge({ label, color, small }: { label: string; color?: string; small?: boolean }) {
  const style: CSSProperties = {
    display: 'inline-block',
    padding: small ? '1px 6px' : '2px 8px',
    borderRadius: '4px',
    fontSize: small ? '0.65rem' : '0.75rem',
    fontWeight: 600,
    letterSpacing: '0.5px',
    background: color ? `${color}22` : 'var(--bg-elevated)',
    color: color || 'var(--text-secondary)',
    border: `1px solid ${color || 'var(--border)'}44`,
  };
  return <span style={style}>{label}</span>;
}
