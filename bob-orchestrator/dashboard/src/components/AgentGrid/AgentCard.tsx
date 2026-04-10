import type { Agent, Task } from '../../api/types';
import { agentLabel, agentColor } from '../../api/types';
import { StatusDot } from '../common/StatusDot';
import { Badge } from '../common/Badge';
import { timeAgo } from '../common/TimeAgo';

export function AgentCard({ agent, currentTask }: { agent: Agent; currentTask?: Task }) {
  const color = agentColor(agent.shorthand);

  return (
    <div style={{
      padding: '1rem',
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      borderTop: `3px solid ${color}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: '1.1rem', fontWeight: 700, color, letterSpacing: '1px' }}>
          {agentLabel(agent.shorthand)}
        </span>
        <StatusDot active={agent.is_active} />
      </div>
      <div style={{ fontSize: '0.85rem', fontWeight: 500, marginBottom: 4 }}>{agent.name}</div>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: 8 }}>{agent.role}</div>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: 8 }}>
        Last seen: {timeAgo(agent.last_seen)}
      </div>
      {currentTask && (
        <div style={{ fontSize: '0.75rem', padding: '4px 8px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', marginBottom: 8 }}>
          Working on: {currentTask.title.slice(0, 40)}{currentTask.title.length > 40 ? '...' : ''}
        </div>
      )}
      {agent.capabilities.length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {agent.capabilities.slice(0, 5).map(c => (
            <Badge key={c.name} label={c.name} small />
          ))}
        </div>
      )}
    </div>
  );
}
