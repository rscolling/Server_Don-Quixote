import { useMemo, useState } from 'react';
import { useDashboard } from '../../context/DashboardContext';
import { KANBAN_COLUMNS, type Task } from '../../api/types';
import { KanbanColumn } from './KanbanColumn';
import { TaskFilters } from './TaskFilters';
import { TaskDetail } from './TaskDetail';

export function TaskBoard() {
  const { state } = useDashboard();
  const [selected, setSelected] = useState<Task | null>(null);

  const filtered = useMemo(() => {
    let tasks = state.tasks;
    const f = state.taskFilters;
    if (f.assignee) tasks = tasks.filter(t => t.assignee === f.assignee);
    if (f.priority) tasks = tasks.filter(t => t.priority === f.priority);
    if (f.user) {
      const u = f.user.toLowerCase();
      tasks = tasks.filter(t => {
        const meta = JSON.stringify(t.metadata || {}).toLowerCase();
        const desc = t.description.toLowerCase();
        const watchers = (t.watchers || []).join(' ').toLowerCase();
        return meta.includes(u) || desc.includes(u) || watchers.includes(u);
      });
    }
    if (f.search) {
      const q = f.search.toLowerCase();
      tasks = tasks.filter(t => t.title.toLowerCase().includes(q) || t.description.toLowerCase().includes(q));
    }
    return tasks;
  }, [state.tasks, state.taskFilters]);

  const columns = useMemo(() => {
    const map: Record<string, Task[]> = {};
    for (const col of KANBAN_COLUMNS) map[col] = [];
    for (const t of filtered) {
      // REWORK tasks go into IN_REVIEW column
      const col = t.state === 'REWORK' ? 'IN_REVIEW' : t.state;
      if (map[col]) map[col].push(t);
    }
    return map;
  }, [filtered]);

  return (
    <div>
      <TaskFilters />
      <div style={{ display: 'flex', gap: '0.75rem', overflowX: 'auto', paddingBottom: '1rem' }}>
        {KANBAN_COLUMNS.map(col => (
          <KanbanColumn
            key={col}
            state={col}
            tasks={columns[col] || []}
            onSelect={setSelected}
          />
        ))}
      </div>
      {selected && <TaskDetail task={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
