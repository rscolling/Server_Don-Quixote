import { useDashboard } from '../../context/DashboardContext';
import { StatusDot } from '../common/StatusDot';

export function Header() {
  const { state, wsState } = useDashboard();
  const uptime = state.busHealth?.uptime_seconds;
  const uptimeStr = uptime != null
    ? `${Math.floor(uptime / 3600)}h ${Math.floor((uptime % 3600) / 60)}m`
    : '--';

  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0.75rem 1.5rem',
      background: 'var(--bg-surface)',
      borderBottom: '1px solid var(--border)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <span style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--accent)' }}>BOB</span>
        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Agent Dashboard</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
        <span>Bus uptime: {uptimeStr}</span>
        <span>Tasks: {state.stats?.tasks.total ?? '--'}</span>
        <span>Agents: {state.stats?.agents.active ?? '--'}/{state.stats?.agents.total ?? '--'}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <StatusDot active={wsState === 'connected'} />
          {wsState === 'connected' ? 'Live' : wsState}
        </span>
      </div>
    </header>
  );
}
