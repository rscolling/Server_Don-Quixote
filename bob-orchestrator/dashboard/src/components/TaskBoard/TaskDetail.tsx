import type { Task } from '../../api/types';
import { agentLabel, agentColor, PRIORITY_COLORS } from '../../api/types';
import { Badge } from '../common/Badge';
import { TimeAgo } from '../common/TimeAgo';

export function TaskDetail({ task, onClose }: { task: Task; onClose: () => void }) {
  const debate = task.metadata?.debate;

  return (
    <div style={{
      position: 'fixed', top: 0, right: 0, bottom: 0,
      width: 420, maxWidth: '90vw',
      background: 'var(--bg-surface)',
      borderLeft: '1px solid var(--border)',
      padding: '1.5rem',
      overflowY: 'auto',
      zIndex: 100,
      boxShadow: '-4px 0 20px rgba(0,0,0,0.3)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '1rem' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: 600, flex: 1 }}>{task.title}</h3>
        <button onClick={onClose} style={{ fontSize: '1.2rem', color: 'var(--text-secondary)', padding: '0 0.5rem' }}>×</button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: '1rem', flexWrap: 'wrap' }}>
        <Badge label={task.state} color="var(--info)" />
        <Badge label={task.priority.toUpperCase()} color={PRIORITY_COLORS[task.priority]} />
        {task.assignee && <Badge label={agentLabel(task.assignee)} color={agentColor(task.assignee)} />}
      </div>

      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
        Created: <TimeAgo date={task.created_at} /> &nbsp;|&nbsp; Updated: <TimeAgo date={task.updated_at} />
      </div>

      <div style={{ fontSize: '0.85rem', lineHeight: 1.5, marginBottom: '1.5rem', whiteSpace: 'pre-wrap' }}>
        {task.description || 'No description'}
      </div>

      {debate && (
        <div style={{ marginBottom: '1.5rem' }}>
          <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 8, color: 'var(--accent)' }}>Debate Info</h4>
          <div style={{ fontSize: '0.8rem', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Tier:</span><span>{debate.debate_tier}</span>
            <span style={{ color: 'var(--text-secondary)' }}>Type:</span><span>{debate.task_type}</span>
            <span style={{ color: 'var(--text-secondary)' }}>Round:</span><span>{debate.current_round}/{debate.max_rounds}</span>
            <span style={{ color: 'var(--text-secondary)' }}>Primary:</span><span>{agentLabel(debate.primary_agent)}</span>
            <span style={{ color: 'var(--text-secondary)' }}>Critics:</span>
            <span>{(debate.critic_agents || []).map((a: string) => agentLabel(a)).join(', ')}</span>
            {debate.final_critic && (
              <><span style={{ color: 'var(--text-secondary)' }}>Final:</span><span>{agentLabel(debate.final_critic)}</span></>
            )}
          </div>
        </div>
      )}

      {task.watchers.length > 0 && (
        <div style={{ marginBottom: '1rem' }}>
          <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 4 }}>Watchers</h4>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {task.watchers.map(w => <Badge key={w} label={agentLabel(w)} small />)}
          </div>
        </div>
      )}

      {task.file_paths.length > 0 && (
        <div>
          <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 4 }}>Files</h4>
          {task.file_paths.map((f, i) => (
            <div key={i} style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{f}</div>
          ))}
        </div>
      )}
    </div>
  );
}
