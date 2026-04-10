import { useMemo } from 'react';
import { useDashboard } from '../../context/DashboardContext';
import { AgentCard } from './AgentCard';

export function AgentGrid() {
  const { state } = useDashboard();

  const currentTasks = useMemo(() => {
    const map: Record<string, typeof state.tasks[0]> = {};
    for (const t of state.tasks) {
      if (t.assignee && (t.state === 'IN_PROGRESS' || t.state === 'IN_REVIEW')) {
        if (!map[t.assignee] || new Date(t.updated_at) > new Date(map[t.assignee].updated_at)) {
          map[t.assignee] = t;
        }
      }
    }
    return map;
  }, [state.tasks]);

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
      gap: '1rem',
    }}>
      {state.agents.map(agent => (
        <AgentCard
          key={agent.shorthand}
          agent={agent}
          currentTask={currentTasks[agent.shorthand]}
        />
      ))}
      {state.agents.length === 0 && (
        <div style={{ color: 'var(--text-secondary)', padding: '2rem', textAlign: 'center' }}>
          No agents registered
        </div>
      )}
    </div>
  );
}
