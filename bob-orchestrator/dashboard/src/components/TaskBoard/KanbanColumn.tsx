import type { Task, TaskState } from '../../api/types';
import { TaskCard } from './TaskCard';

const STATE_LABELS: Record<string, string> = {
  CREATED: 'Created',
  ASSIGNED: 'Assigned',
  IN_PROGRESS: 'In Progress',
  IN_REVIEW: 'In Review',
  ACCEPTED: 'Accepted',
  CLOSED: 'Closed',
};

export function KanbanColumn({
  state,
  tasks,
  onSelect,
}: {
  state: TaskState;
  tasks: Task[];
  onSelect: (task: Task) => void;
}) {
  return (
    <div style={{
      flex: '1 1 0',
      minWidth: 180,
      maxWidth: 280,
      display: 'flex',
      flexDirection: 'column',
      gap: '0.5rem',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '0.4rem 0.5rem',
        background: 'var(--bg-elevated)',
        borderRadius: 'var(--radius-sm)',
        fontSize: '0.75rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        color: 'var(--text-secondary)',
      }}>
        <span>{STATE_LABELS[state] || state}</span>
        <span style={{
          background: 'var(--bg-primary)',
          padding: '1px 6px',
          borderRadius: 10,
          fontSize: '0.7rem',
        }}>
          {tasks.length}
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', overflowY: 'auto', maxHeight: 'calc(100vh - 220px)' }}>
        {tasks.map(t => (
          <TaskCard key={t.id} task={t} onClick={() => onSelect(t)} />
        ))}
      </div>
    </div>
  );
}
