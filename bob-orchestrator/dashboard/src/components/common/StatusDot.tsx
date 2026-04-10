export function StatusDot({ active }: { active: boolean }) {
  return (
    <span style={{
      display: 'inline-block',
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: active ? 'var(--success)' : 'var(--text-muted)',
      boxShadow: active ? '0 0 6px var(--success)' : 'none',
    }} />
  );
}
