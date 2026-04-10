import type { Task } from '../../api/types';
import { agentLabel, agentColor, PRIORITY_COLORS } from '../../api/types';
import { Badge } from '../common/Badge';
import { timeAgo } from '../common/TimeAgo';

export function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const isRework = task.state === 'REWORK';

  return (
    <div
      onClick={onClick}
      style={{
        padding: '0.6rem 0.75rem',
        background: 'var(--bg-surface)',
        border: `1px solid ${isRework ? 'var(--warning)' : 'var(--border)'}`,
        borderRadius: 'var(--radius)',
        cursor: 'pointer',
        transition: 'border-color 0.15s',
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = isRework ? 'var(--warning)' : 'var(--border)')}
    >
      <div style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: 6, lineHeight: 1.3 }}>
        {task.title.length > 60 ? task.title.slice(0, 60) + '...' : task.title}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        {task.assignee && (
          <Badge label={agentLabel(task.assignee)} color={agentColor(task.assignee)} small />
        )}
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: PRIORITY_COLORS[task.priority] || '#888',
          display: 'inline-block',
        }} />
        <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginLeft: 'auto' }}>
          {timeAgo(task.created_at)}
        </span>
        {isRework && <Badge label="REWORK" color="var(--warning)" small />}
      </div>
    </div>
  );
}
